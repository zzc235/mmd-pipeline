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
"""
from __future__ import annotations

import hashlib
import json
import math

SPEC = "evidence/1"
STATUSES = ("PASS", "PARTIAL", "BLOCKED")
# 允许的哈希基数。省略 = 旧基数（按原始字节算）；写了就必须是这里的一个值。
HASH_BASES = ("lf_normalized_v1",)
# measurements 序列化后的字节上限（D-072）：超了就该拆成 artifact 文件
MEASUREMENTS_LIMIT = 16 * 1024


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


def check_file(path: str) -> tuple:
    """读一份 canonical 证据文件并自查，返回 (退出码, 说明)。

    判两件事，缺一不可：
      1. **schema**：能 `normalize()`（`interface` 是字符串、`measurements` 是对象…）；
      2. **字节**：磁盘上的字节必须**就是** canonical 序列化结果——否则「文件 sha256 == digest」
         这条大家用来核验的等式不成立，等于这份记录没法被别人复算。

    退出码按 D-080：`0` 合规 / `3` schema 或 canonical 违规 / `4` 读不到。
    """
    import os
    if not os.path.exists(path):
        return EXIT_UNREADABLE, "读不到：%s 不存在" % path
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        return EXIT_UNREADABLE, "读不到：%s（%s）" % (path, exc)
    try:
        obj = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        return EXIT_UNREADABLE, "不是合法 JSON：%s（%s）" % (path, exc)
    try:
        normal = normalize(obj)
    except EvidenceError as exc:
        return EXIT_SCHEMA, "schema 违规（%s）：%s" % (exc.reason_code, exc)
    blob = canonical_bytes(normal)
    digest = SPEC + ":" + hashlib.sha256(blob).hexdigest()
    if raw != blob:
        return EXIT_SCHEMA, ("不是 canonical 字节：磁盘 %d 字节 vs 规范 %d 字节；"
                             "规范 digest 应为 %s" % (len(raw), len(blob), digest))
    return EXIT_OK, digest


def main(argv=None) -> int:
    """`python -m coordination.evidence check <file>`（D-080 的提交前自查入口）。"""
    import argparse
    ap = argparse.ArgumentParser(prog="coordination.evidence",
                                 description="evidence/1 提交前自查")
    sub = ap.add_subparsers(dest="cmd", required=True)
    chk = sub.add_parser("check", help="校验一份 canonical 证据文件")
    chk.add_argument("file")
    args = ap.parse_args(argv)
    if args.cmd == "check":
        code, message = check_file(args.file)
        prefix = {EXIT_OK: "OK", EXIT_SCHEMA: "SCHEMA_INVALID",
                  EXIT_UNREADABLE: "UNREADABLE"}[code]
        print("%s %s" % (prefix, message))
        return code
    return 2


if __name__ == "__main__":
    import sys
    raise SystemExit(main())
