"""阶段 F：submit / verify 前的**机器闸门包**（gate bundle）。

D0 不再读「看起来完整」的提交，只读闸门结果（`14 号令 §3-F`）。

闸门包（`gate`）字段与判定：

| 字段 | 缺失/不合规 ⇒ |
|---|---|
| `evidence_check_exit` | 非 0 ⇒ `GATE_FAILED` |
| `coverage_check` | 不是 `PASS` ⇒ `MISSING_EVIDENCE` |
| `acceptance_result` | 缺失 ⇒ `GATE_FAILED`；值为 `FAIL` ⇒ `GATE_FAILED` |
| `truth_tier` | 缺失 ⇒ `EVIDENCE_SCOPE_MISMATCH`；不是 T0–T3 ⇒ 同上 |
| `fresh_solve_confirmed` + 声称物理结论 | `false` ⇒ `FRESH_SOLVE_REQUIRED` |
| `module_provenance` | 模块路径不在当前 worktree ⇒ `PROVENANCE_INVALID` |
| `artifacts` 只指向 `reports/` 且无快照 | ⇒ `SNAPSHOT_INVALID` |
| `resource_lease_valid` | `false` ⇒ `LEASE_EXPIRED` |

向后兼容：老证据（没有 `truth_tier`、也没有 `gate`）走 `legacy` 通道并**记事件**
`gate.legacy_skipped`——不是静默放行，是「这份提交没有闸门，历史可见」。
"""
from __future__ import annotations

import os
import re

from .evidence import DELIVERY_TIER, TIER_MEANING, TRUTH_TIERS

PHYSICS_KEYWORDS = ("穿透", "penetration", "位移", "displacement", "重叠", "overlap",
                    "物理", "physics", "深度", "depth")
# 结构性字段/纯路径不算「声称物理结论」，否则 `mmdpipe/depth_probe.py` 这种路径会误触发。
STRUCTURAL_KEYS = frozenset({
    "gate", "spec", "task_id", "attempt", "status", "interface",
    "files", "artifacts", "snapshot_paths", "module_provenance",
    "base", "head", "repo", "sha256", "run_id", "reason_code",
})
_PATH_LIKE = re.compile(r"^[A-Za-z0-9_.\-/\\:]+$")


class GateRejected(Exception):
    def __init__(self, reason_code: str, detail: str, extra: dict | None = None):
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail
        self.extra = extra or {}


def _iter_claim_strings(obj, key=None):
    """递归取「可能是结论」的字符串：列表/字典都要走进去（老坑：只扫顶层 str 会漏 known_risks）。"""
    if isinstance(obj, str):
        if key in STRUCTURAL_KEYS:
            return
        text = obj.strip()
        # 纯路径（含分隔符或扩展名）不是结论文本
        if _PATH_LIKE.match(text) and ("/" in text or "\\" in text):
            return
        yield text
    elif isinstance(obj, dict):
        for sub_key, sub_val in obj.items():
            yield from _iter_claim_strings(sub_val, sub_key)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _iter_claim_strings(item, key)


def _claims_physics(payload) -> bool:
    blob = " ".join(_iter_claim_strings(payload)).lower()
    for token in PHYSICS_KEYWORDS:
        if token.lower() in blob:
            return True
    return False


def check_bundle(bundle: dict | None, payload: dict | None = None,
                 worktree: str | None = None) -> dict:
    """校验闸门包。返回 {ok, reason_code, detail, checks}；不抛异常，便于汇总。"""
    payload = payload or {}
    checks = []

    def fail(code: str, detail: str) -> dict:
        checks.append({"ok": False, "code": code, "detail": detail})
        return {"ok": False, "reason_code": code, "detail": detail, "checks": checks}

    if not isinstance(bundle, dict) or not bundle:
        return fail("GATE_FAILED", "缺闸门包（gate bundle）")

    exit_code = bundle.get("evidence_check_exit")
    if exit_code != 0:
        return fail("GATE_FAILED", "evidence check exit=%r（必须 0）" % (exit_code,))
    checks.append({"ok": True, "code": "evidence_check", "detail": "exit=0"})

    coverage = str(bundle.get("coverage_check") or "").upper()
    if coverage != "PASS":
        return fail("MISSING_EVIDENCE", "coverage_check=%r（必须 PASS）" % (bundle.get("coverage_check"),))
    checks.append({"ok": True, "code": "coverage", "detail": "PASS"})

    acceptance = str(bundle.get("acceptance_result") or "").upper()
    if acceptance not in ("PASS", "FAIL", "NOT_APPLICABLE"):
        return fail("GATE_FAILED", "acceptance_result 缺失或非法：%r" % (bundle.get("acceptance_result"),))
    if acceptance == "FAIL":
        return fail("GATE_FAILED", "acceptance_result=FAIL")
    checks.append({"ok": True, "code": "acceptance", "detail": acceptance})

    raw_tier = bundle.get("truth_tier")
    tier = raw_tier.strip() if isinstance(raw_tier, str) else ""
    if tier not in TRUTH_TIERS:
        return fail("EVIDENCE_SCOPE_MISMATCH", "truth_tier 缺失或非法：%r（允许 %s；逐字匹配）"
                    % (raw_tier, "/".join(TRUTH_TIERS)))
    checks.append({"ok": True, "code": "truth_tier", "detail": tier})

    # 交付尺度：M08 只认 T3（14 号令 §3-I）。别的模块接受 T0–T3，
    # 但 T_DESCRIPTIVE 永远只能描述——它进不了任何结论。
    task_id = str(bundle.get("task_id") or payload.get("task_id") or "")
    if task_id.upper().startswith("M08") and tier != DELIVERY_TIER:
        return fail("EVIDENCE_SCOPE_MISMATCH",
                    "%s 只收 %s，收到 %s（%s）" % (task_id, DELIVERY_TIER, tier,
                                                 TIER_MEANING.get(tier, "未定义的档")))
    # 缓存回放的读数按 D-154 只能作描述：报 T2/T3 等于把回放当重解。
    if str(bundle.get("pose_source") or "").lower() == "cache_replay" and tier != "T_DESCRIPTIVE":
        return fail("EVIDENCE_SCOPE_MISMATCH",
                    "pose_source=cache_replay 只能报 T_DESCRIPTIVE，收到 %s" % tier)
    checks.append({"ok": True, "code": "tier_scope", "detail": "%s/%s" % (task_id or "-", tier)})

    if _claims_physics(payload) and not bundle.get("fresh_solve_confirmed"):
        return fail("FRESH_SOLVE_REQUIRED", "提交声称物理结论，但 fresh_solve_confirmed 不为真")
    checks.append({"ok": True, "code": "fresh_solve",
                   "detail": "%r" % (bundle.get("fresh_solve_confirmed"),)})

    provenance = bundle.get("module_provenance") or {}
    root = os.path.abspath(worktree or os.getcwd())
    outside = []
    for key, value in provenance.items():
        if key == "sha256" or not isinstance(value, str) or not value:
            continue
        if not os.path.abspath(value).lower().startswith(root.lower()):
            outside.append("%s=%s" % (key, value))
    if outside:
        return fail("PROVENANCE_INVALID", "模块路径不在当前 worktree（%s）：%s"
                    % (root, "; ".join(outside)))
    checks.append({"ok": True, "code": "provenance", "detail": "%d 项在 %s" % (len(provenance), root)})

    snaps_bad = []
    for art in bundle.get("snapshot_paths") or []:
        if not isinstance(art, dict):
            continue
        path = art.get("path") or ""
        if path.replace("\\", "/").startswith("reports/") and not art.get("snapshot"):
            snaps_bad.append(path)
    if snaps_bad:
        return fail("SNAPSHOT_INVALID", "artifact 只指向 reports/ 且没有快照：%s" % ", ".join(snaps_bad[:5]))
    checks.append({"ok": True, "code": "snapshots", "detail": "%d 条" % len(bundle.get("snapshot_paths") or [])})

    if bundle.get("resource_lease_valid") is False:
        return fail("LEASE_EXPIRED", "resource_lease_valid=false")
    checks.append({"ok": True, "code": "lease", "detail": "%r" % (bundle.get("resource_lease_valid"),)})

    return {"ok": True, "reason_code": "EVIDENCE_COMPLETE", "detail": "闸门全过", "checks": checks}


def wants_gate(payload: dict) -> bool:
    """这份提交是否要求闸门：带 `truth_tier` 或带 `gate` 就要求；都没有走 legacy。"""
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("gate")) or bool(payload.get("truth_tier"))


def enforce(payload: dict, bundle: dict | None = None, worktree: str | None = None) -> dict:
    """按「要不要闸门」决定：要就校验，不过就抛 `GateRejected`。"""
    if not wants_gate(payload) and bundle is None:
        return {"ok": True, "legacy": True, "reason_code": "DOC_ONLY",
                "detail": "老证据未带 truth_tier/gate，按 legacy 通道放行并记事件"}
    result = check_bundle(bundle if bundle is not None else payload.get("gate"), payload, worktree)
    if not result["ok"]:
        raise GateRejected(result["reason_code"], result["detail"], {"checks": result["checks"]})
    return result
