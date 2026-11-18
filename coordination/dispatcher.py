"""分流器：按 lane 给席位派工，输出 `dispatch.json`（不启动任何 AI）。

依据 `13_自动调度与分流器规范.md` §7.1 §8，**以及 `14_D0架构优化执行令.md` 阶段 D**：

分流规则（不做 work stealing）：
    P0 → M00（协调平台；默认席位 A4，**必须 D0 明确批准**，不许自动抢）
    A1 → M01/M02      A2 → M03/M04      A3 → M05/M06      A4 → M07/M08

两条硬规矩（阶段 D 新增，都是为了「不假装」）：
1. **board 空而状态表非空** ⇒ 输出 `MISCONFIGURED_EMPTY_BOARD`，不许报 `IDLE`。
   `IDLE` 的意思是「都干完了」，空 board 恰恰相反：一条活都没进库。
2. 派工输出必带 `base_commit`，供执行席创建/校准 worktree。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess

from . import board as board_mod
from . import paths as paths_mod

LANES = {
    "P0": ("M00",),
    "A1": ("M01", "M02"),
    "A2": ("M03", "M04"),
    "A3": ("M05", "M06"),
    "A4": ("M07", "M08"),
}
# lane 与「默认席位」不再同名假设：P0 的席位是 A4，但需要 D0 批准。
LANE_SEAT = {"P0": "A4", "A1": "A1", "A2": "A2", "A3": "A3", "A4": "A4"}
P0_APPROVAL_EVENT = "p0.approved"
QUEUE_LIMIT = board_mod.QUEUE_LIMIT


def lane_of(module: str) -> str:
    for lane, modules in LANES.items():
        if module in modules:
            return lane
    raise ValueError("模块 %s 不属于任何 lane（白名单只有 M00–M08）" % module)


def _git_head(repo: str | None = None) -> str:
    try:
        rc = subprocess.run(["git", "-C", repo or ".", "rev-parse", "HEAD"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return (rc.stdout or "").strip() if rc.returncode == 0 else ""


def p0_approval(b, task_id: str) -> dict:
    """P0 派工必须有 D0 的显式批准；返回批准记录（空 dict 表示没批）。"""
    for row in b.db.execute("SELECT ts, payload_json FROM events WHERE type=? AND task_id=?",
                            (P0_APPROVAL_EVENT, task_id)):
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except ValueError:
            payload = {}
        if payload.get("by") == "D0":
            return {"approved_at": row["ts"], "by": "D0",
                    "changed_scope": payload.get("changed_scope") or ""}
    return {}


def status_tasks_of(status_path: str | None) -> dict:
    """读状态表（只读，用来识别「board 空但状态表非空」）。"""
    import io
    if not status_path:
        status_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "task_status.json")
    try:
        with io.open(status_path, encoding="utf-8") as fh:
            doc = json.loads(fh.read())
    except (OSError, ValueError):
        return {}
    return doc.get("tasks") or {}


def plan(b: board_mod.Board, now=None, status_path: str | None = None,
         approve_p0: bool = False, repo: str | None = None) -> dict:
    """算一份派工计划。只读，不改状态。"""
    head = _git_head(repo)
    board_count = b.db.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"]
    status_tasks = status_tasks_of(status_path)
    if board_count == 0 and status_tasks:
        return {
            "state": "MISCONFIGURED_EMPTY_BOARD",
            "why": "task_status has tasks but board has none",
            "board_tasks": 0,
            "status_tasks": len(status_tasks),
            "base_commit": head,
            "fix": "python -m coordination.sync_board",
            "note": "board 是状态事实源；空库不是「空闲」，是没灌库（14 号令 §3-D.3）",
        }

    rows = []
    queued = b.queued_count()
    pending = b.pending_count()
    backpressure = pending >= QUEUE_LIMIT
    reserved_resources = set()
    for lane, modules in LANES.items():
        seat = LANE_SEAT[lane]
        busy = b.active_task_of(seat)
        if busy:
            rows.append({"lane": lane, "agent": seat, "action": "busy",
                         "task_id": busy["task_id"], "status": busy["status"],
                         "base_commit": busy.get("base_commit") or head})
            continue
        if backpressure:
            rows.append({"lane": lane, "agent": seat, "action": "paused",
                         "reason": "queued_submission=%d（上限 %d）" % (queued, QUEUE_LIMIT)})
            continue
        pick = b.db.execute(
            "SELECT task_id, module, resource, base_commit FROM tasks "
            "WHERE lane=? AND status='ready' ORDER BY task_id", (lane,)).fetchall()
        candidates = [dict(row) for row in pick if row["module"] in modules]
        candidates.sort(key=lambda r: (-b.unlocks(r["task_id"]), r["task_id"]))
        chosen = None
        for cand in candidates:
            # 纯只读判断：dispatcher 是计划层，既不 claim，也不该拿写锁或触碰 schema。
            # 但计划内已经有一条要拿同一资源时，下一条不能同时被派出——否则两条都会在 claim 时撞锁。
            resource = cand["resource"] or "none"
            ok_deps = b._deps_ok(b.db, cand["task_id"])
            ok_res = (b._resource_free(b.db, resource, b.now())
                      and resource not in reserved_resources)
            if ok_deps and ok_res:
                chosen = cand
                break
        if not chosen:
            rows.append({"lane": lane, "agent": seat, "action": "idle"})
            continue
        entry = {"lane": lane, "agent": seat, "action": "claim",
                 "task_id": chosen["task_id"], "module": chosen["module"],
                 "resource": chosen["resource"],
                 "base_commit": chosen.get("base_commit") or head}
        if chosen["resource"] and chosen["resource"] != "none":
            reserved_resources.add(chosen["resource"])
        if lane == "P0":
            approval = p0_approval(b, chosen["task_id"])
            if approve_p0 and not approval:
                approval = {"approved_at": None, "by": "D0",
                            "changed_scope": "命令行 --approve-p0"}
            if not approval:
                entry = {"lane": lane, "agent": seat, "action": "needs_approval",
                         "task_id": chosen["task_id"], "module": chosen["module"],
                         "reason": "P0 任务必须由 D0 明确批准（14 号令 §3-D.2）",
                         "reason_code": "HUMAN_REQUIRED",
                         "base_commit": chosen.get("base_commit") or head}
            else:
                entry["d0_approval"] = approval
                entry["changed_scope"] = approval.get("changed_scope") or ""
                entry["reason"] = "P0 派工：协调平台任务，需要 D0 批准后执行"
        rows.append(entry)

    actionable = [r for r in rows if r["action"] == "claim"]
    return {
        "queued_submission": queued,
        "backpressure": backpressure,
        "state": "DISPATCH" if actionable else "IDLE",
        "base_commit": head,
        "assignments": rows,
        "note": "半自动：本文件只给计划，不启动任何 AI（13 §8）",
    }


def write(plan_dict: dict, path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(plan_dict, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    return path


def main(argv=None) -> int:
    from .cli import ensure_utf8_stdio
    ensure_utf8_stdio()
    ap = argparse.ArgumentParser(prog="coordination.dispatcher")
    ap.add_argument("--board", default=None, help="缺省用主工作树 out/subai/coordination/board.db")
    ap.add_argument("--out", default=None, help="缺省写主工作树 out/subai/coordination/dispatch.json")
    ap.add_argument("--status", default=None, help="状态表路径（用来识别空 board）")
    ap.add_argument("--approve-p0", action="store_true", help="D0 现场批准 P0 派工")
    ap.add_argument("--repo", default=None, help="取 base_commit 的 git 仓库")
    ap.add_argument("--write", action="store_true", help="把计划写入 --out")
    args = ap.parse_args(argv)
    b = board_mod.Board(args.board, readonly=True)
    try:
        plan_dict = plan(b, status_path=args.status, approve_p0=args.approve_p0, repo=args.repo)
    finally:
        b.close()
    if args.write:
        write(plan_dict, args.out or paths_mod.dispatch_path())
    print(json.dumps(plan_dict, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
