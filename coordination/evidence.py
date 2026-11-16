"""evidence/1 证据哈希：规范化 + 计算（依据 `coordination/evidence_hash_v1.md`）。

为什么单独一个模块：这个 hash 是"能不能进验证"的唯一凭据。它必须确定性——
同一份证据在任何工作树、任何机器、任何时间算出同一个值；并且必须挡住
"只改说明""重跑同一条测试""换个说法"这三类假新证据（13 §5.1）。

所以这里**只做规范化与拒绝**，不做任何统计：
    * 键递归升序、无缩进、UTF-8、ensure_ascii=False —— 序列化唯一
    * `files` / `artifacts` 按 path 升序，`tests` 按 (cmd, exit) 升序
    * `known_risks` 空白折叠、去空、按码点升序、去重
    * 路径归一：`./mmdpipe\\pmx.py` 与 `mmdpipe/pmx.py` 同值
    * NaN / ±Inf / -0.0：前两者拒绝（不可复现的数没有资格当证据），后者记 0.0

可选键（缺席则哈希与加它们之前**逐字节相同**，旧记录一个都不失效）：
    * `hash_basis`：枚举 `lf_normalized_v1`；缺席 = 旧基数（原始字节）
    * `measurements`：JSON 对象，原样进 canonical（D-072）；序列化超 16 KiB 拒
    * `commit`：7–40 位小写 hex（D0 13:49 (b)）；**不检查该 commit 是否存在**
    * `scope`：空白折叠；折成空串等同缺席

**能力边界（别把 exit 0 读成"全都对"）**：本模块只认**形状**，不重算
`files[]` / `artifacts[]` 与磁盘是否一致——那是生产者自证的反面。`check` 过
只说明"这份文件是规范字节、schema 合规"，不说明"里面的 sha256 没被换掉"。
"""
from __future__ import annotations

import hashlib
import json
import math
import re

SPEC = "evidence/1"
STATUSES = ("PASS", "PARTIAL", "BLOCKED")
# 允许的哈希基数。省略 = 旧基数（按原始字节算）；写了就必须是这里的一个值。
HASH_BASES = ("lf_normalized_v1",)
# commit 形状（D0 2026-11-16 13:49 定 (b)）：7–40 位小写 hex。
# **不查它是否存在**——那要 shell 出去调 git，规范实现不该有外部依赖。
COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
# measurements 序列化后的字节上限（D-072）：超了就该拆成 artifact 文件
MEASUREMENTS_LIMIT = 16 * 1024
# 真值档（`14 号令 §3-I`）：这份数是在什么尺度上测出来的。**可选**——老记录不带它，
# 加了也不改它们的哈希；带了就必须是枚举里的拼法（大小写不改，错一个字就拒）。
#   T0 单元/合成  T1 真实小场景  T2 代表性逐帧  T3 交付尺度
#   T_DESCRIPTIVE 只能描述、不能当结论（缓存回放读数就落这一档）
TRUTH_TIERS = ("T0", "T1", "T2", "T3", "T_DESCRIPTIVE")
TIER_MEANING = {
    "T0": "单元/合成：证明逻辑，不证明场景",
    "T1": "真实小场景：证明能跑通，不证明尺度",
    "T2": "代表性逐帧：能出「结论级变化」",
    "T3": "交付尺度：M08 只认这一档",
    "T_DESCRIPTIVE": "只作描述：不得作为结论依据（含 cache_replay 读数）",
}
#: 只有这一档能进交付验收
DELIVERY_TIER = "T3"


class EvidenceError(ValueError):
    """证据不合规。`reason_code` 直接进 D0 的回执（默认 MISSING_EVIDENCE）。"""

    def __init__(self, message, reason_code="MISSING_EVIDENCE"):
        super().__init__(message)
        self.reason_code = reason_code


def norm_path(path: str) -> str:
    """相对路径归一：反斜杠→正斜杠、去掉 `./` 与结尾 `/`、不留盘符前缀。"""
    if not isinstance(path, str) or not path.strip():
        raise EvidenceError("路径必须是非空字符串：%r" % (path,))
    p = path.strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    if len(p) > 1 and p.endswith("/"):
        p = p.rstrip("/")
    if not p:
        raise EvidenceError("路径归一后为空：%r" % (path,))
    return p


def _check_floats(node, where="root"):
    """递归拒绝 NaN / ±Inf；-0.0 归一成 0.0。"""
    if isinstance(node, dict):
        return {k: _check_floats(v, "%s.%s" % (where, k)) for k, v in node.items()}
    if isinstance(node, (list, tuple)):
        return [_check_floats(v, "%s[%d]" % (where, i)) for i, v in enumerate(node)]
    if isinstance(node, bool):
        return node
    if isinstance(node, float):
        if math.isnan(node) or math.isinf(node):
            raise EvidenceError("%s 是不可复现的数值（NaN/Inf），不能进 hash" % where)
        return 0.0 if node == 0.0 else node
    return node


def _sorted_unique(rows, key, what):
    out = {}
    for row in rows:
        if not isinstance(row, dict):
            raise EvidenceError("%s 的每一项必须是对象" % what)
        k = key(row)
        if k in out:
            raise EvidenceError("%s 里 path 重复：%s" % (what, k))
        out[k] = row
    return [out[k] for k in sorted(out)]


def normalize(obj: dict) -> dict:
    """把一份证据规范化成唯一形态。不合规直接抛 EvidenceError。"""
    if not isinstance(obj, dict):
        raise EvidenceError("证据必须是 JSON 对象")
    # 先在**整份输入**上拒绝 NaN/Inf：不可复现的数哪怕藏在自定义字段里也不许进 hash。
    _check_floats(obj)
    if obj.get("spec") != SPEC:
        raise EvidenceError("spec 必须是 %r，收到 %r" % (SPEC, obj.get("spec")), "WRONG_SPEC")
    if not isinstance(obj.get("task_id"), str) or not obj["task_id"].strip():
        raise EvidenceError("task_id 必须是非空字符串")
    attempt = obj.get("attempt")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 0:
        raise EvidenceError("attempt 必须是非负整数")
    status = obj.get("status")
    if status not in STATUSES:
        raise EvidenceError("status 只能是 %s" % "/".join(STATUSES))

    files = _sorted_unique(obj.get("files") or [], lambda r: norm_path(r.get("path")), "files")
    for row in files:
        row["path"] = norm_path(row["path"])
        row.setdefault("tracked", True)
        if not isinstance(row.get("sha256"), str) or len(row["sha256"]) != 64:
            raise EvidenceError("files[%s].sha256 必须是 64 位 hex" % row["path"])

    tests = []
    for row in obj.get("tests") or []:
        if not isinstance(row, dict) or not isinstance(row.get("cmd"), str):
            raise EvidenceError("tests 的每一项必须有 cmd")
        # D-094（D0 2026-11-16 14:02）：`tests[]` 行是**重建**的，schema 外的字段会被
        # 静默丢掉——于是"我声明了的字段"和"进了哈希的字段"不是同一个集合，而写记录的人
        # 只能靠最后一步 `check` 打出的 exit 5 猜自己哪儿错了。**必须变成错误，不许沉默。**
        extra = sorted(set(row) - set(TESTS_KEYS))
        if extra:
            raise EvidenceError(
                "tests[%s] 有 schema 外的字段：%s（只允许 %s；这些字段不会进哈希，"
                "要留说明请放 measurements）"
                % (row["cmd"], "、".join(extra), "/".join(TESTS_KEYS)),
                "WRONG_TESTS_FIELD")
        for field in ("exit", "passed", "failed", "skipped"):
            v = row.get(field, 0)
            if isinstance(v, bool) or not isinstance(v, int):
                raise EvidenceError("tests[%s].%s 必须是整数" % (row["cmd"], field))
        tests.append({"cmd": row["cmd"], "exit": row.get("exit", 0),
                      "passed": row.get("passed", 0), "failed": row.get("failed", 0),
                      "skipped": row.get("skipped", 0)})
    tests.sort(key=lambda r: (r["cmd"], r["exit"]))

    artifacts = _sorted_unique(obj.get("artifacts") or [],
                               lambda r: norm_path(r.get("path")), "artifacts")
    for row in artifacts:
        row["path"] = norm_path(row["path"])
        if not isinstance(row.get("sha256"), str) or len(row["sha256"]) != 64:
            raise EvidenceError("artifacts[%s].sha256 必须是 64 位 hex" % row["path"])
        row.setdefault("version", "")

    risks = []
    for item in obj.get("known_risks") or []:
        if not isinstance(item, str):
            raise EvidenceError("known_risks 的每一项必须是字符串")
        text = " ".join(item.split())
        if text:
            risks.append(text)
    risks = sorted(set(risks))

    interface = obj.get("interface")
    if interface is not None and not isinstance(interface, str):
        raise EvidenceError("interface 必须是字符串或 null")

    # 哈希基数（D0 2026-11-16 定：文本先 \r\n → \n 再 sha256）。
    # **可选**：不给就是旧基数（原始字节），哈希与加这个字段之前逐字节相同；
    # 给了就必须是枚举里的值——自由文本等于没标准，所以不认识的基数直接抛。
    hash_basis = obj.get("hash_basis")
    if hash_basis is not None and not isinstance(hash_basis, str):
        raise EvidenceError("hash_basis 必须是字符串或 null")
    if isinstance(hash_basis, str):
        text = " ".join(hash_basis.split())
        if text and text not in HASH_BASES:
            raise EvidenceError("hash_basis 只能是 %s，或省略表示旧基数；收到 %r"
                                % ("/".join(HASH_BASES), text), "WRONG_HASH_BASIS")
        hash_basis = text or None
    else:
        hash_basis = None

    # measurements（D-072，2026-11-16）：**可选** JSON 对象，原样进 canonical 参与哈希。
    # 为什么要有：之前「数」只能塞进正文，而正文不进 hash —— 最要紧的那批数
    # （eval_policy、网格自检 0.9933/0.9867/77.01%）全落在哈希之外，等于没被证明。
    # 为什么限 16 KiB：证据是给人核的，不是数据库；超了说明该拆成 artifact 文件。
    measurements = obj.get("measurements")
    if measurements is not None:
        if not isinstance(measurements, dict):
            raise EvidenceError("measurements 必须是 JSON 对象（收到 %s）"
                                % type(measurements).__name__, "BAD_MEASUREMENTS")
        blob = canonical_bytes(measurements)
        if len(blob) > MEASUREMENTS_LIMIT:
            raise EvidenceError("measurements 序列化后 %d 字节，超过上限 %d 字节——"
                                "大块数据请放 artifacts[] 并在这里放摘要"
                                % (len(blob), MEASUREMENTS_LIMIT), "BAD_MEASUREMENTS")

    # commit（D0 13:49 选 (b)）：**可选**，7–40 位小写 hex。
    # 为什么单独两个键而不是塞进 measurements.provenance（2号 的 (a)）：
    # 出处不是"测量值"——measurements 一旦能装任何东西就会变成什么都装，
    # 而下一个读证据的人不会去 measurements 里找出处（就像今天已经看到
    # "落在哈希外的数等于没有"）。commit 可核验、每个消费者都要读。
    # **不对称的空值语义，要照做**：`scope` 为空 = 没写范围（缺席）；
    # `commit` 为空 = "我以为我填了但它是空的"，那是缺陷不是声明 ⇒ 抛。
    commit = obj.get("commit")
    if commit is not None:
        if not isinstance(commit, str):
            raise EvidenceError("commit 必须是字符串", "WRONG_COMMIT")
        # 不 strip：哈希串上的空白是手误，静默吃掉它会让同一份内容两种写法同值；
        # 直接拒，写的人一次就发现。
        if not COMMIT_RE.match(commit):
            raise EvidenceError("commit 必须是 7–40 位小写 hex，收到 %r" % (commit,),
                                "WRONG_COMMIT")

    # scope：**可选**，空白折叠（同 known_risks），折成空串等同缺席、不进 canonical。
    scope = obj.get("scope")
    if scope is not None:
        if not isinstance(scope, str):
            raise EvidenceError("scope 必须是字符串或 null", "WRONG_SCOPE")
        scope = " ".join(scope.split()) or None

    # truth_tier（14 号令 §3-I）：**可选**，枚举内逐字匹配。
    # 为什么可选：162 条历史记录没有它，若设成必填，`check_file` 会把它们全判 exit 3
    # ——迁移历史等于篡改历史（D-157 的教训）。不写 = 「这份记录没声明尺度」，
    # 那本身就是可读的事实，而缺省的语义由闸门决定（M08 缺档即拒）。
    truth_tier = obj.get("truth_tier")
    if truth_tier is not None:
        if not isinstance(truth_tier, str):
            raise EvidenceError("truth_tier 必须是字符串或 null", "WRONG_TRUTH_TIER")
        text = truth_tier.strip()
        if text not in TRUTH_TIERS:
            raise EvidenceError("truth_tier 只能是 %s；收到 %r（逐字匹配，大小写不改）"
                                % (" / ".join(TRUTH_TIERS), truth_tier), "WRONG_TRUTH_TIER")
        truth_tier = text

    normalized = {
        "spec": SPEC,
        "task_id": obj["task_id"],
        "attempt": attempt,
        "status": status,
        "files": files,
        "tests": tests,
        "artifacts": artifacts,
        "known_risks": risks,
        "interface": interface,
    }
    if hash_basis is not None:
        normalized["hash_basis"] = " ".join(hash_basis.split())
    if measurements is not None:
        normalized["measurements"] = measurements
    if commit is not None:
        normalized["commit"] = commit
    if scope is not None:
        normalized["scope"] = scope
    if truth_tier is not None:
        normalized["truth_tier"] = truth_tier
    return _check_floats(normalized)


def canonical_bytes(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def digest(obj: dict) -> str:
    """返回 `evidence/1:<sha256>`。"""
    return SPEC + ":" + hashlib.sha256(canonical_bytes(normalize(obj))).hexdigest()


def validate(obj: dict) -> dict:
    """规范化并返回；不合规抛 EvidenceError。"""
    return normalize(obj)


# ---------------------------------------------------------------- 提交前自查（D-080）
EXIT_OK = 0
EXIT_SCHEMA = 3
EXIT_UNREADABLE = 4
# D0 2026-11-16 13:53 定死：`NOT_CANONICAL` 单独一个退出码 **5**，不与时 3 共用。
# 理由（2号 提、D0 背书）：今天所有"失败与不一致不同形"的修法里，**只有退出码
# 分离是调用方能机械判的**——`reason_code` 得读输出才知道，而脚本作者一定会把 3
# 当一种情况处理。3 = 能读能解析但违反 schema；5 = schema 没问题，但磁盘上那份
# 不是规范字节（篡改 / 自建序列化 / 手改过）。
EXIT_NOT_CANONICAL = 5
REASON_OK = "OK"
REASON_SCHEMA = "SCHEMA_INVALID"
REASON_NOT_CANONICAL = "NOT_CANONICAL"
REASON_UNREADABLE = "UNREADABLE"

# 进哈希的顶层键（`normalize()` 之后能出现在 canonical 里的全部）
HASHED_KEYS = ("spec", "task_id", "attempt", "status", "files", "tests", "artifacts",
               "known_risks", "interface", "hash_basis", "measurements", "commit", "scope",
               "truth_tier")
# `tests[]` 每行只有这五个字段进 canonical（行会被**重建**，其余字段被丢掉）。
# `files[]` / `artifacts[]` 的行是**整行保留**的，多写字段会进哈希，所以不在此列。
TESTS_KEYS = ("cmd", "exit", "passed", "failed", "skipped")


def explain_not_canonical(raw, obj, normal) -> list:
    """说清"磁盘字节 vs 规范字节"的差从哪来——否则 exit 5 只是个哑码。

    分三类，因为三类的处理办法完全不同：
      1. **序列化本身不同**：连裸 `canonical_bytes(obj)`（不经过 normalize）都不等于
         磁盘字节 ⇒ 自建格式化（缩进、`", "` 分隔符、键序没排）。
         改法：落盘前就用 `canonical_bytes()`。
      2. **顶层多写了不进哈希的键**（`summary` 这类）。内容是对的，但"文件 sha256 ==
         digest"这条等式不成立。
      3. 都没命中 ⇒ 字段值被规范化改写过（`known_risks` 折叠、路径归一、`-0.0→0.0`、
         行重排）。这时磁盘那份是"人写的"而不是"算出来的"。

    `tests[]` 行多写字段**不在此列**：D-094 之后那是 `WRONG_TESTS_FIELD`（exit 3），
    在 `normalize()` 里就抛了，走不到这里。
    """
    notes = []
    try:
        if raw != canonical_bytes(obj):
            notes.append("序列化本身不是规范形态（缩进/分隔符/键序）——"
                         "落盘前请直接用 canonical_bytes()")
    except (TypeError, ValueError):
        pass
    extra_top = sorted(set(obj) - set(normal))
    if extra_top:
        notes.append("顶层多了不进哈希的键：%s" % "、".join(extra_top))
    if not notes:
        notes.append("字段值被规范化改写过（known_risks 折叠、路径归一、行重排），"
                     "磁盘那份看着是手写/自建的而非算出来的")
    return notes


def check_file(path: str) -> tuple:
    """读一份 canonical 证据文件并自查，返回 (退出码, reason_code, 说明)。

    判两件事，缺一不可：
      1. **schema**：能 `normalize()`（`interface` 是字符串、`commit` 是 hex…）；
      2. **字节**：磁盘上的字节必须**就是** canonical 序列化结果——否则「文件 sha256 == digest」
         这条大家用来核验的等式不成立，等于这份记录没法被别人复算。

    退出码（D-080 + D0 13:53）：`0` 合规 / `3` schema 违规 / `5` 非规范字节 / `4` 读不到。
    **不做什么**：不重算 `files[]`/`artifacts[]` 与磁盘是否一致——那是生产者自证的反面。
    所以 exit 0 只等于"形状对、字节规范"，不等于"里面的 sha256 没被换掉"。
    """
    import os
    if not os.path.exists(path):
        return EXIT_UNREADABLE, REASON_UNREADABLE, "读不到：%s 不存在" % path
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        return EXIT_UNREADABLE, REASON_UNREADABLE, "读不到：%s（%s）" % (path, exc)
    try:
        obj = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        return EXIT_UNREADABLE, REASON_UNREADABLE, "不是合法 JSON：%s（%s）" % (path, exc)
    try:
        normal = normalize(obj)
    except EvidenceError as exc:
        return EXIT_SCHEMA, REASON_SCHEMA, "schema 违规（%s）：%s" % (exc.reason_code, exc)
    blob = canonical_bytes(normal)
    digest = SPEC + ":" + hashlib.sha256(blob).hexdigest()
    if raw != blob:
        notes = explain_not_canonical(raw, obj, normal)
        return (EXIT_NOT_CANONICAL, REASON_NOT_CANONICAL,
                "不是 canonical 字节：磁盘 %d 字节 vs 规范 %d 字节；规范 digest 应为 %s"
                % (len(raw), len(blob), digest) + "".join("\n  " + n for n in notes))
    return EXIT_OK, REASON_OK, digest


def main(argv=None) -> int:
    """`python -m coordination.evidence check <file>`（D-080 的提交前自查入口）。"""
    from .cli import ensure_utf8_stdio
    ensure_utf8_stdio()
    import argparse
    ap = argparse.ArgumentParser(
        prog="coordination.evidence",
        description="evidence/1 提交前自查",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="退出码（四个码分开是调用方唯一能机械判的东西）：\n"
               "  0  OK              磁盘字节 == 规范字节，digest 自洽\n"
               "  3  SCHEMA_INVALID  能读能解析，但违反 schema（类型/约束不符）\n"
               "  5  NOT_CANONICAL   schema 没问题，但磁盘上那份不是规范字节\n"
               "                     （篡改 / 自建序列化 / 手改过）\n"
               "  4  UNREADABLE      读不出或不是合法 JSON\n"
               "\n"
               "能力边界：check 只认形状与字节规范，**不重算** files[]/artifacts[]\n"
               "与磁盘是否一致。exit 0 不等于 artifact 没被换掉。")
    sub = ap.add_subparsers(dest="cmd", required=True)
    chk = sub.add_parser("check", help="校验一份 canonical 证据文件")
    chk.add_argument("file")
    args = ap.parse_args(argv)
    if args.cmd == "check":
        code, reason, message = check_file(args.file)
        print("%s %s" % (reason, message))
        return code
    return 2


if __name__ == "__main__":
    import sys
    raise SystemExit(main())
