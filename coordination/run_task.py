"""统一任务执行入口：把 board 状态、preflight、锁、运行号和执行命令串成一条链。

这个模块是**协调层**，不 import bpy。它不理解 M02/M04/M08 的业务语义，只保证
任何长跑都必须经过同一条机械路径：

    Board 只读预检
    → worktree/base/dirty 校验
    → preflight
    → Board claim/start + 登记 run_id
    → lock guard（资源不是 none 时）
    → 执行命令，同时续 board 任务/资源租约
    → 可选证据提交；命令失败则 RUN_FAILED + blocked

用法：

    python -m coordination.run_task \
        --task M02 --agent A1 --worktree E:/code/mmdpipe-ai/A1 \
        --spec out/subai/M02/preflight.json --base <commit> --head <commit> \
        --evidence out/subai/M02/evidence.json \
        --claim -- python run_pipeline.py --pmx ... --out ...

`--` 之后是要执行的原始命令。命令不会由 shell 解释，避免中文路径、竖线、空格被 shell 改写。
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import threading
import uuid

from . import board as board_mod
from . import lock as lock_mod
from . import preflight as preflight_mod


class RunTaskError(RuntimeError):
    def __init__(self, message, code="RUN_REFUSED"):
        super().__init__(message)
        self.code = code


def _git(worktree: str, *args: str) -> str:
    proc = subprocess.run(["git", "-C", worktree, *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=30)
    if proc.returncode != 0:
        raise RunTaskError("git %s 失败：%s" % (" ".join(args), proc.stderr.strip()),
                           "PROVENANCE_INVALID")
    return proc.stdout.strip()


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def verify_worktree(worktree: str, base: str = "", head: str = "",
                    allow_dirty: bool = False) -> dict:
    """确认代码视角与声明一致。长跑前看的是 git 视角，不看工作树感觉。"""
    root = _git(worktree, "rev-parse", "--show-toplevel")
    if not _same_path(root, worktree):
        raise RunTaskError("worktree 不是 git 根：声明 %s，实际 %s" % (worktree, root),
                           "PROVENANCE_INVALID")
    actual_head = _git(worktree, "rev-parse", "HEAD")
    if head and actual_head != head:
        raise RunTaskError("head 不符：声明 %s，实际 %s" % (head, actual_head),
                           "PROVENANCE_INVALID")
    dirty = _git(worktree, "status", "--porcelain")
    if dirty and not allow_dirty:
        raise RunTaskError("worktree 未提交：%d 行变更；生产运行必须显式 --allow-dirty"
                           % len([ln for ln in dirty.splitlines() if ln.strip()]),
                           "OWNERSHIP_VIOLATION")
    base_commit = base or ""
    if base_commit:
        ok = subprocess.run(["git", "-C", worktree, "merge-base", "--is-ancestor",
                             base_commit, actual_head],
                            capture_output=True, timeout=30)
        if ok.returncode != 0:
            raise RunTaskError("base %s 不在当前 HEAD 祖先链上" % base_commit,
                               "PROVENANCE_INVALID")
    return {"root": os.path.abspath(root), "head": actual_head, "base": base_commit,
            "dirty": bool(dirty)}


def _format_value(value, context: dict):
    if isinstance(value, str):
        try:
            return value.format(**context)
        except KeyError as exc:
            raise RunTaskError("preflight spec 占位符 %s 没有值" % exc, "MISSING_EVIDENCE")
    if isinstance(value, list):
        return [_format_value(item, context) for item in value]
    if isinstance(value, dict):
        return {key: _format_value(item, context) for key, item in value.items()}
    return value


def load_preflight_spec(path: str, context: dict) -> dict:
    with open(path, "r", encoding="utf-8-sig") as fh:
        raw = json.load(fh)
    spec = _format_value(raw, dict(context))
    if not isinstance(spec, dict):
        raise RunTaskError("preflight spec 必须是对象", "SCHEMA_INVALID")
    return spec


def ensure_claim(b: board_mod.Board, task_id: str, agent: str, claim: bool,
                 lease_seconds: int) -> dict:
    task = b.task(task_id)
    if not task:
        raise RunTaskError("board 没有任务 %s" % task_id, "DEPENDENCY_UNMET")
    if claim:
        got = b.claim(task["lane"], agent, lease_seconds=lease_seconds,
                      modules=(task["module"],))
        if not got or got.get("task_id") != task_id:
            raise RunTaskError("claim 没拿到目标任务 %s（计划/状态已变化）" % task_id,
                               "OWNERSHIP_VIOLATION")
        return got
    if task["status"] == "returned" or task.get("owner") != agent:
        raise RunTaskError("任务 %s 不归 %s 持有；先由 dispatcher 派工或显式 --claim"
                           % (task_id, agent), "OWNERSHIP_VIOLATION")
    if task["status"] not in ("claimed", "running"):
        raise RunTaskError("任务 %s 当前状态 %s，不能执行" % (task_id, task["status"]),
                           "OWNERSHIP_VIOLATION")
    return task


@contextlib.contextmanager
def _board_heartbeat(b, task_id, lease_seconds, every):
    """命令运行期间同时续 board 任务/资源租约；文件锁心跳不能代替这一层。"""
    stop = threading.Event()
    state = {"error": None}

    def beat():
        while not stop.wait(max(0.01, float(every))):
            try:
                b.heartbeat(task_id, lease_seconds=lease_seconds)
            except Exception as exc:  # 心跳失败先记账，命令结束后 fail-closed
                state["error"] = str(exc)
                return

    thread = None
    if every and float(every) > 0:
        thread = threading.Thread(target=beat, daemon=True)
        thread.start()
    try:
        yield
    finally:
        stop.set()
        if thread is not None:
            thread.join(timeout=5.0)
    if state["error"]:
        raise RunTaskError("board 租约心跳失败：%s" % state["error"], "LEASE_EXPIRED")


def execute_command(command, *, owner: str, note: str, use_guard: bool,
                    worktree: str, wait_s: float, heartbeat_every: float,
                    runner=None) -> dict:
    """执行生产命令；Blender 类资源强制走 lock guard。"""
    command = list(command or [])
    if not command:
        raise RunTaskError("缺少 `--` 之后的执行命令", "RUN_USAGE")
    if use_guard:
        if not owner or "|" not in owner:
            raise RunTaskError("锁模式要求 owner 为 `模块|工作树`", "RUN_USAGE")
        result = lock_mod.guard(owner, command, note=note, wait_s=wait_s,
                                heartbeat_every=heartbeat_every, runner=runner)
        rc = result["rc"]
        if result.get("lock_lost") and rc == 0:
            rc = lock_mod.EXIT_LOCK_LOST
        result["command"] = command
        return result
    proc = subprocess.run(command, cwd=worktree) if runner is None else runner(command)
    if isinstance(proc, int):
        return {"rc": int(proc), "command": command, "guard": False}
    return {"rc": int(getattr(proc, "returncode", 0)), "command": command,
            "guard": False}


def _split_dashdash(argv) -> tuple:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" not in argv:
        return argv, []
    cut = argv.index("--")
    return argv[:cut], argv[cut + 1:]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="coordination.run_task",
                                 description="唯一生产任务执行入口")
    ap.add_argument("--board", default=None)
    ap.add_argument("--task", required=True)
    ap.add_argument("--agent", required=True)
    ap.add_argument("--owner", default="",
                    help="锁 owner；缺省为 agent（如 A1，不带竖线时用 --no-lock 或自行给 --owner）")
    ap.add_argument("--worktree", required=True)
    ap.add_argument("--spec", required=True, help="preflight spec JSON")
    ap.add_argument("--base", default="")
    ap.add_argument("--head", default="")
    ap.add_argument("--repo", default="", help="证据覆盖校验仓库，缺省为 --worktree")
    ap.add_argument("--evidence", default="", help="执行成功后提交的证据 JSON")
    ap.add_argument("--claim", action="store_true", help="先按 lane 原子认领目标任务")
    ap.add_argument("--start", action="store_true", help="claim 后进入 running")
    ap.add_argument("--allow-dirty", action="store_true")
    ap.add_argument("--run-id", default="", help="缺省由 board 发号")
    ap.add_argument("--lease", type=int, default=900)
    ap.add_argument("--wait", type=float, default=0.0)
    ap.add_argument("--heartbeat-every", type=float, default=120.0)
    ap.add_argument("--no-lock", action="store_true", help="仅纯 CPU 任务、且资源为 none 时使用")
    ap.add_argument("--dry-run", action="store_true", help="只输出计划，不执行/不提交")
    return ap


def main(argv=None) -> int:
    from .cli import ensure_utf8_stdio
    ensure_utf8_stdio()
    head_argv, command = _split_dashdash(argv)
    args = build_parser().parse_args(head_argv)
    b = board_mod.Board(args.board, readonly=args.dry_run)
    if not args.dry_run:
        b.init()
    try:
        if not command:
            raise RunTaskError("缺少 `--` 之后的执行命令", "RUN_USAGE")
        if args.lease <= 0:
            raise RunTaskError("--lease 必须是正数", "RUN_USAGE")

        task = b.task(args.task)
        if not task:
            raise RunTaskError("board 没有任务 %s" % args.task, "DEPENDENCY_UNMET")
        if args.claim:
            # 只读预检；真正的原子 claim 必须等所有无写入闸门通过之后再做。
            if task["status"] not in ("ready", "returned"):
                raise RunTaskError("任务 %s 当前状态 %s，不能认领" % (args.task, task["status"]),
                                   "OWNERSHIP_VIOLATION")
        else:
            task = ensure_claim(b, args.task, args.agent, False, args.lease)

        resource = task.get("resource") or "none"
        if args.no_lock and resource != "none":
            raise RunTaskError("--no-lock 只允许 resource=none 的任务", "RUN_USAGE")
        use_guard = resource != "none"
        owner = args.owner or args.agent
        if use_guard and (not owner or "|" not in owner):
            raise RunTaskError("锁模式要求 owner 为 `模块|工作树`", "RUN_USAGE")

        worktree_info = verify_worktree(args.worktree, base=args.base, head=args.head,
                                        allow_dirty=args.allow_dirty)
        # 候选号用于展开 preflight 路径，此时不写 board；真实执行前才登记 RUN_ISSUED。
        if args.dry_run:
            run_id = args.run_id or ("dryrun_" + uuid.uuid4().hex[:8])
        else:
            run_id = args.run_id or b.new_run_id(args.task)
        context = {"task_id": args.task, "agent": args.agent, "run_id": run_id,
                   "worktree": worktree_info["root"]}
        spec = load_preflight_spec(args.spec, context)
        outcome = preflight_mod.check(spec, worktree=worktree_info["root"])
        if outcome["state"] != "READY":
            raise RunTaskError(outcome["detail"], outcome["reason_code"])

        note = "%s %s %s" % (args.task, args.agent, run_id)
        result = {"state": "READY", "task_id": args.task, "run_id": run_id,
                  "resource": resource, "use_lock_guard": use_guard,
                  "preflight": outcome, "worktree": worktree_info,
                  "command": command}
        if args.dry_run:
            result["state"] = "DRY_RUN"
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0

        task = ensure_claim(b, args.task, args.agent, args.claim, args.lease)
        if args.start or args.claim:
            task = b.start(args.task, lease_seconds=args.lease)
        b.issue_run_id(args.task, run_id)

        try:
            with _board_heartbeat(b, args.task, args.lease, args.heartbeat_every):
                execution = execute_command(
                    command, owner=owner, note=note, use_guard=use_guard,
                    worktree=worktree_info["root"], wait_s=args.wait,
                    heartbeat_every=args.heartbeat_every)
        except Exception as exc:
            b.fail_run(args.task, run_id, 3, str(exc))
            raise RunTaskError("执行入口异常：%s" % exc, "GATE_FAILED")

        result["execution"] = execution
        if execution["rc"] != 0:
            rc = int(execution["rc"] or 3)
            result["failure"] = b.fail_run(args.task, run_id, rc)
            result["state"] = "COMMAND_FAILED"
            result["reason_code"] = "GATE_FAILED"
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return rc

        if args.evidence:
            try:
                with open(args.evidence, "r", encoding="utf-8-sig") as fh:
                    payload = json.load(fh)
            except (OSError, ValueError) as exc:
                raise RunTaskError("证据 JSON 读不了：%s" % exc, "MISSING_EVIDENCE")
            submit = b.submit(args.task, payload, base=args.base, head=args.head,
                              repo=args.repo or worktree_info["root"])
            result["submit"] = submit
        result["state"] = "RUN_OK"
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except RunTaskError as exc:
        payload = {"state": "REJECTED", "reason_code": exc.code, "why": str(exc)}
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 4
    except board_mod.BoardError as exc:
        payload = {"state": "REJECTED", "reason_code": exc.reason_code, "why": str(exc)}
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 3
    finally:
        b.close()


if __name__ == "__main__":
    sys.exit(main())
