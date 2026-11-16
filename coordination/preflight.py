"""阶段 G：**开工前置闸门**（preflight）——在跑 Blender 之前就挡住必然返工的活。

`gates.py` 管「提交回来的证据能不能过」，`preflight.py` 管「这份活该不该开始」。
两者的 reason_code 同属 `decision_taxonomy.json` 的闭集，D0 只读代码不读叙事。

| 检查 | 不过 ⇒ | 具体判据 |
|---|---|---|
| 产地 `provenance` | `PROVENANCE_INVALID` | 任一模块路径不在当前 worktree 根下 |
| 能力 `needs`/`cap` | `CAP_UNMET` | 未声明 cap；或 `needs > cap`（含负值/非数） |
| 计划跳过 `skipped` | `GATE_FAILED` | `skipped != 0`——计划里就打算跳过的活不许开工 |
| 资源租约 `lease` | `LEASE_EXPIRED` | 未持锁 / 心跳超过 stale 分钟 / owner 不匹配 |
| 产物归属 `outputs` | `OWNERSHIP_VIOLATION` | 目标路径已存在，且既没有新 `run_id` 也没有 `overwrite` 裁决id |

语义约定：**「通过」统一用 `EVIDENCE_COMPLETE`**（与 `gates.py` 一致），`state` 为
`READY` / `BLOCKED`；`BLOCKED` 时 `reason_code` 取**固定顺序里第一个**不过的检查，
`checks[]` 里给全部结论，D0 一次就能看全所有拦路项。

fail-closed：请求里缺 `provenance`/`cap` 不当成「没问题」，而是当成没声明 ⇒ 拦。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

from . import lock, paths, provenance

REASON_PASS = "EVIDENCE_COMPLETE"
DEFAULT_STALE_MINUTES = lock.DEFAULT_STALE_MINUTES


def _norm(path: str) -> str:
    return os.path.abspath(path).replace("\\", "/").lower()


def _check_provenance(request: dict, worktree: str) -> dict:
    # 与 gates 共用同一实现：worktree + 显式声明的 external_roots（M06 的外部树走这条）。
    result = provenance.check(request.get("provenance"), worktree,
                              request.get("external_roots"))
    return {"name": "provenance", "ok": result["ok"], "code": result["reason_code"],
            "detail": result["detail"]}


def _as_number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _check_capacity(request: dict) -> dict:
    needs = _as_number(request.get("needs"))
    cap = _as_number(request.get("cap"))
    if cap is None:
        return {"name": "capacity", "ok": False, "code": "CAP_UNMET",
                "detail": "未声明 cap（本期上限），按 fail-closed 拦下"}
    if needs is None:
        return {"name": "capacity", "ok": False, "code": "CAP_UNMET",
                "detail": "needs 缺失或不是数字：%r" % (request.get("needs"),)}
    if needs > cap:
        return {"name": "capacity", "ok": False, "code": "CAP_UNMET",
                "detail": "needs=%g > cap=%g（差 %g 条没处放）" % (needs, cap, needs - cap)}
    return {"name": "capacity", "ok": True, "code": REASON_PASS,
            "detail": "needs=%g <= cap=%g" % (needs, cap)}


def _check_skipped(request: dict) -> dict:
    skipped = _as_number(request.get("skipped"))
    if skipped is None:
        return {"name": "skipped", "ok": True, "code": REASON_PASS, "detail": "未声明，按 0"}
    if skipped != 0:
        return {"name": "skipped", "ok": False, "code": "GATE_FAILED",
                "detail": "计划跳过 %g 条——跳过的活不算做完" % skipped}
    return {"name": "skipped", "ok": True, "code": REASON_PASS, "detail": "skipped=0"}


def _check_lease(request: dict) -> dict:
    if request.get("lease") is False:
        return {"name": "lease", "ok": True, "code": REASON_PASS, "detail": "本任务不要求租约"}
    lease_dir = request.get("lease_dir") or paths.lock_dir()
    stale_minutes = _as_number(request.get("stale_minutes")) or DEFAULT_STALE_MINUTES
    try:
        info = lock.status(lease_dir)
    except lock.LockError as exc:      # 锁目录在但 owner.txt 读不到 ⇒ 半截锁，同样 fail-closed
        return {"name": "lease", "ok": False, "code": "LEASE_EXPIRED",
                "detail": "锁状态不可读（%s）：%s" % (lease_dir, exc)}
    if not info.get("held"):
        return {"name": "lease", "ok": False, "code": "LEASE_EXPIRED",
                "detail": "没有持锁（%s）" % lease_dir}
    age = info.get("heartbeat_age")
    if age is None or age > stale_minutes * 60.0:
        return {"name": "lease", "ok": False, "code": "LEASE_EXPIRED",
                "detail": "心跳过期：%r 秒（上限 %g 分钟）" % (age, stale_minutes)}
    expect = request.get("expect_owner")
    ident = info.get("ident") or ""
    if expect and expect not in ident:
        return {"name": "lease", "ok": False, "code": "LEASE_EXPIRED",
                "detail": "持锁人 %r 与期望 %r 不符" % (ident, expect)}
    return {"name": "lease", "ok": True, "code": REASON_PASS,
            "detail": "持锁 %r，心跳 %.1f 秒前" % (ident, age)}


def _check_outputs(request: dict) -> dict:
    outputs = request.get("outputs") or []
    if isinstance(outputs, str):
        outputs = [outputs]
    run_id = str(request.get("run_id") or "")
    overwrite = str(request.get("overwrite") or "")
    exists, blocked = [], []
    for raw in outputs:
        if not isinstance(raw, str) or not raw:
            continue
        path = raw
        if not os.path.isabs(path):
            path = os.path.join(str(request.get("worktree") or os.getcwd()), path)
        if not os.path.exists(path):
            continue
        exists.append(raw)
        fresh_run = bool(run_id) and run_id in _norm(raw)
        if not fresh_run and not overwrite:
            blocked.append(raw)
    if blocked:
        return {"name": "outputs", "ok": False, "code": "OWNERSHIP_VIOLATION",
                "detail": "目标已存在且无新 run_id / 无 overwrite 裁决：%s" % ", ".join(sorted(blocked)[:5])}
    if exists:
        return {"name": "outputs", "ok": True, "code": REASON_PASS,
                "detail": "%d 条已存在，已由 run_id/overwrite 认领" % len(exists)}
    return {"name": "outputs", "ok": True, "code": REASON_PASS, "detail": "目标路径均不存在"}


CHECKS = (_check_provenance, _check_capacity, _check_skipped, _check_lease, _check_outputs)


def check(request: dict, worktree: str | None = None) -> dict:
    """跑全套前置检查。返回 {state, reason_code, task_id, detail, checks}；不抛异常。"""
    request = dict(request or {})
    root = worktree or request.get("worktree") or os.getcwd()
    request["worktree"] = root
    checks = []
    for fn in CHECKS:
        if fn is _check_provenance:
            checks.append(fn(request, root))
        else:
            checks.append(fn(request))
    failures = [c for c in checks if not c["ok"]]
    if failures:
        first = failures[0]
        return {"state": "BLOCKED", "reason_code": first["code"],
                "task_id": request.get("task_id"), "detail": first["detail"],
                "blockers": failures, "checks": checks}
    return {"state": "READY", "reason_code": REASON_PASS,
            "task_id": request.get("task_id"), "detail": "前置全部满足",
            "blockers": [], "checks": checks}


def render(result: dict) -> str:
    lines = ["%s  %s  %s" % (result["state"], result.get("task_id") or "-", result["reason_code"])]
    for check_ in result["checks"]:
        lines.append("  [%s] %-10s %s" % ("ok" if check_["ok"] else "NO", check_["name"], check_["detail"]))
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="coordination.preflight",
                                 description="开工前置闸门：READY / BLOCKED")
    ap.add_argument("--spec", required=True, help="请求 JSON（provenance/needs/cap/skipped/lease/outputs...）")
    ap.add_argument("--worktree", default=None, help="worktree 根（默认 cwd）")
    ap.add_argument("--json", action="store_true", help="输出完整 JSON")
    args = ap.parse_args(argv)

    # `utf-8-sig`：PS 5.1 的 `Set-Content -Encoding UTF8` 会写 BOM，用 utf-8 读会
    # `Unexpected UTF-8 BOM` 崩掉（A3 2026-11-16 17:32 实测踩到）。这不是闸门该有的死法。
    with io.open(args.spec, "r", encoding="utf-8-sig") as fh:
        request = json.load(fh)
    result = check(request, worktree=args.worktree)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render(result))
    return 0 if result["state"] == "READY" else 4


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
