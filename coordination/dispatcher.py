"""分流器：按四条 lane 给四个席位派工，输出 `dispatch.json`（不启动任何 AI）。

依据 `13_自动调度与分流器规范.md` §7.1 与 §8：
本程序**只算下一个任务**，不打开会话、不写状态。要真正自动启动需要 runner，
在那之前"半自动"是唯一诚实的说法——`dispatch.json` 交给对应席位执行。

分流规则（不做 work stealing）：
    A1 → M01/M02      A2 → M03/M04      A3 → M05/M06      A4 → M07/M08
空闲席位只拿本 lane 的任务；本 lane 没有可派的就报 IDLE，不去抢别人的活。
"""
from __future__ import annotations

import argparse
import json
import os

from . import board as board_mod
from . import paths as paths_mod

LANES = {
    "A1": ("M01", "M02"),
    "A2": ("M03", "M04"),
    "A3": ("M05", "M06"),
    "A4": ("M07", "M08"),
}
QUEUE_LIMIT = board_mod.QUEUE_LIMIT


def lane_of(module: str) -> str:
    for lane, modules in LANES.items():
        if module in modules:
            return lane
    raise ValueError("模块 %s 不属于任何 lane（白名单只有 M01–M08）" % module)


def plan(b: board_mod.Board, now=None) -> dict:
    """算一份派工计划。只读，不改状态。"""
    rows = []
    queued = b.queued_count()
    pending = b.pending_count()
    backpressure = pending >= QUEUE_LIMIT
    for lane, modules in LANES.items():
        agent = lane
        busy = b.active_task_of(agent)
        if busy:
            rows.append({"lane": lane, "agent": agent, "action": "busy",
                         "task_id": busy["task_id"], "status": busy["status"]})
            continue
        if backpressure:
            rows.append({"lane": lane, "agent": agent, "action": "paused",
                         "reason": "queued_submission=%d（上限 %d）" % (queued, QUEUE_LIMIT)})
            continue
        pick = b.db.execute(
            "SELECT task_id, module, resource FROM tasks WHERE lane=? AND status='ready' "
            "ORDER BY task_id", (lane,)).fetchall()
        chosen = None
        candidates = []
        for row in pick:
            if row["module"] not in modules:
                continue
            candidates.append(dict(row))
        candidates.sort(key=lambda r: (-b.unlocks(r["task_id"]), r["task_id"]))
        for cand in candidates:
            with b.tx() as c:                      # 只读判断依赖与资源，事务内不写
                ok_deps = b._deps_ok(c, cand["task_id"])
                ok_res = b._resource_free(c, cand["resource"], b.now())
            if ok_deps and ok_res:
                chosen = cand
                break
        if chosen:
            rows.append({"lane": lane, "agent": agent, "action": "claim",
                         "task_id": chosen["task_id"], "module": chosen["module"],
                         "resource": chosen["resource"]})
        else:
            rows.append({"lane": lane, "agent": agent, "action": "idle"})
    actionable = [r for r in rows if r["action"] == "claim"]
    return {
        "queued_submission": queued,
        "backpressure": backpressure,
        "state": "DISPATCH" if actionable else "IDLE",
        "assignments": rows,
        "note": "半自动：本文件只给计划，不启动任何 AI（13 §8）",
    }


def write(plan_dict: dict, path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(plan_dict, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="coordination.dispatcher")
    ap.add_argument("--board", default=None, help="缺省用主工作树 out/subai/coordination/board.db")
    ap.add_argument("--out", default=None, help="缺省写主工作树 out/subai/coordination/dispatch.json")
    ap.add_argument("--write", action="store_true", help="把计划写入 --out")
    args = ap.parse_args(argv)
    b = board_mod.Board(args.board)
    b.init()
    try:
        plan_dict = plan(b)
    finally:
        b.close()
    if args.write:
        write(plan_dict, args.out or paths_mod.dispatch_path())
    print(json.dumps(plan_dict, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
