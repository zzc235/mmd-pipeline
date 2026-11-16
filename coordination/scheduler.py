"""调度器命令行：把 board 的动作暴露成可脚本化的子命令（确定性、无 Agent）。

    python -m coordination.scheduler init   --board coordination/board.db
    python -m coordination.scheduler add-task --board ... --task M01 --module M01 --lane A1 --status ready
    python -m coordination.scheduler claim  --board ... --lane A1 --agent A1
    python -m coordination.scheduler submit --board ... --task M01 --evidence evidence.json
    python -m coordination.scheduler verify-begin --board ...
    python -m coordination.scheduler decide --board ... --task M01 --decision RETURN_FIX
    python -m coordination.scheduler merge-begin / merge-done --task M01 --merge-commit abc123
    python -m coordination.scheduler reap / status

所有输出都是单行 JSON（便于 dispatcher 和测试断言），不改任何产物。
"""
from __future__ import annotations

import argparse
import json
import sys

from . import board as board_mod
from . import evidence as evidence_mod


def _out(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="coordination.scheduler")
    ap.add_argument("command", choices=("init", "add-task", "claim", "start", "heartbeat",
                                        "submit", "verify-begin", "decide", "merge-begin",
                                        "merge-done", "reap", "status", "events"))
    ap.add_argument("--board", default="coordination/board.db")
    ap.add_argument("--task", default="")
    ap.add_argument("--module", default="")
    ap.add_argument("--lane", default="")
    ap.add_argument("--agent", default="")
    ap.add_argument("--status", default="ready")
    ap.add_argument("--resource", default="none")
    ap.add_argument("--evidence", default="")
    ap.add_argument("--decision", default="")
    ap.add_argument("--reason", default="")
    ap.add_argument("--merge-commit", default="")
    ap.add_argument("--lease", type=int, default=900)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    b = board_mod.Board(args.board)
    b.init()
    try:
        if args.command == "init":
            _out({"state": "ok", "board": b.path})
        elif args.command == "add-task":
            if not (args.task and args.module and args.lane):
                raise SystemExit("add-task 需要 --task --module --lane")
            _out(b.add_task(args.task, args.module, args.lane, status=args.status,
                            resource=args.resource))
        elif args.command == "claim":
            _out(b.claim(args.lane, args.agent, lease_seconds=args.lease) or
                 {"state": "IDLE", "lane": args.lane, "agent": args.agent})
        elif args.command == "start":
            _out(b.start(args.task, lease_seconds=args.lease))
        elif args.command == "heartbeat":
            b.heartbeat(args.task, lease_seconds=args.lease)
            _out({"state": "ok"})
        elif args.command == "submit":
            with open(args.evidence, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            try:
                _out(b.submit(args.task, payload))
            except evidence_mod.EvidenceError as exc:
                _out({"state": "REJECTED", "reason_code": exc.reason_code, "why": str(exc)})
                return 2
        elif args.command == "verify-begin":
            _out(b.verify_begin() or {"state": "IDLE"})
        elif args.command == "decide":
            _out(b.decide(args.task, args.decision, args.reason))
        elif args.command == "merge-begin":
            task = b.merge_begin()
            _out(task or {"state": "IDLE"})
        elif args.command == "merge-done":
            _out(b.merge_done(args.task, args.merge_commit))
        elif args.command == "reap":
            _out({"reaped": b.reap()})
        elif args.command == "status":
            _out({"tasks": [dict(r) for r in b.db.execute(
                "SELECT task_id, status, owner, lane, attempt, claim_count, "
                "verification_rounds, return_count FROM tasks ORDER BY task_id")],
                "queued": b.queued_count(),
                "active_submission": b.active_submission().get("task_id")})
        elif args.command == "events":
            _out({"events": b.events()})
    except board_mod.BoardError as exc:
        _out({"state": "REJECTED", "reason_code": exc.reason_code or "BOARD_ERROR", "why": str(exc)})
        return 2
    finally:
        b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
