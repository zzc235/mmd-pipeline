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
    # **可选且只在不写时才补默认**：给了就进 hash，不给就完全不出现——
    # 这样改动之前算出来的证据哈希一个都不变（有测试钉住）。
    hash_basis = obj.get("hash_basis")
    if hash_basis is not None and not isinstance(hash_basis, str):
        raise EvidenceError("hash_basis 必须是字符串或 null")
    if isinstance(hash_basis, str) and not hash_basis.strip():
        hash_basis = None

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
