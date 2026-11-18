# -*- coding: utf-8 -*-
"""统一任务执行入口的纯协调层回归。

不启动 Blender、不跑长跑；只验证状态归属、spec 占位符、命令分发和派工资源预留。
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from coordination import board as board_mod
from coordination import dispatcher as dispatcher_mod
from coordination import run_task as run_task_mod


def make_qualified_repo(root, name):
    """建一个干净的临时 git 仓库，供 dispatcher worktree 资格预检当夹具。

    底座与 S3 的 test_dispatcher_worktrees.make_repo 一致：内容随 name 变化，
    避免同内容+同作者+同秒提交产生相同 hash。task 未设 base_commit 时 plan 会
    取该仓库 HEAD 做 base，is-ancestor(HEAD, HEAD) 恒真，预检合格。
    """
    path = os.path.join(root, name)
    os.makedirs(path, exist_ok=True)
    assert subprocess.run(["git", "-C", path, "init", "-q"]).returncode == 0
    with open(os.path.join(path, "f.txt"), "w", encoding="utf-8") as fh:
        fh.write(name + "\n")
    assert subprocess.run(["git", "-C", path, "add", "."]).returncode == 0
    assert subprocess.run(["git", "-C", path, "-c", "user.email=a@b", "-c", "user.name=t",
                           "commit", "-qm", "init"]).returncode == 0
    return path


class RunTaskCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="mm_run_task_")
        self.board = board_mod.Board(os.path.join(self.dir, "board.db"))
        self.board.init()

    def tearDown(self):
        self.board.close()
        shutil.rmtree(self.dir, ignore_errors=True)


class TestEnsureClaim(RunTaskCase):
    def test_claim_picks_target_task_in_lane(self):
        self.board.add_task("M01", "M01", "A1", status="ready")
        self.board.add_task("M02", "M02", "A1", status="ready")
        got = run_task_mod.ensure_claim(self.board, "M02", "A1", claim=True, lease_seconds=60)
        self.assertEqual(got["task_id"], "M02")
        self.assertEqual(got["owner"], "A1")

    def test_returned_task_requires_fresh_claim(self):
        self.board.add_task("M01", "M01", "A1", status="returned")
        with self.assertRaises(run_task_mod.RunTaskError) as ctx:
            run_task_mod.ensure_claim(self.board, "M01", "A1", claim=False, lease_seconds=60)
        self.assertEqual(ctx.exception.code, "OWNERSHIP_VIOLATION")

    def test_wrong_agent_cannot_execute(self):
        self.board.add_task("M01", "M01", "A1", status="claimed")
        self.board.db.execute("UPDATE tasks SET owner='A1' WHERE task_id='M01'")
        with self.assertRaises(run_task_mod.RunTaskError):
            run_task_mod.ensure_claim(self.board, "M01", "A2", claim=False, lease_seconds=60)


class TestPreflightSpecFormat(unittest.TestCase):
    def test_placeholders_are_expanded_recursively(self):
        got = run_task_mod._format_value(
            {"outputs": ["out/{task_id}/{run_id}/a.json"],
             "nested": {"agent": "{agent}", "num": 2}},
            {"task_id": "M02", "run_id": "r1", "agent": "A1"})
        self.assertEqual(got["outputs"], ["out/M02/r1/a.json"])
        self.assertEqual(got["nested"]["agent"], "A1")
        self.assertEqual(got["nested"]["num"], 2)

    def test_missing_placeholder_is_refused(self):
        with self.assertRaises(run_task_mod.RunTaskError) as ctx:
            run_task_mod._format_value("out/{run_id}", {"task_id": "M02"})
        self.assertEqual(ctx.exception.code, "MISSING_EVIDENCE")


class TestExecuteCommand(unittest.TestCase):
    def test_cpu_command_uses_injected_runner_without_lock(self):
        seen = []
        def runner(command):
            seen.append(command)
            return 7
        got = run_task_mod.execute_command(["python", "-c", "print(1)"],
                                           owner="", note="", use_guard=False,
                                           worktree=".", wait_s=0,
                                           heartbeat_every=0, runner=runner)
        self.assertEqual(got["rc"], 7)
        self.assertEqual(seen, [["python", "-c", "print(1)"]])

    def test_guard_mode_requires_owner_shape(self):
        with self.assertRaises(run_task_mod.RunTaskError) as ctx:
            run_task_mod.execute_command(["x"], owner="A1", note="n", use_guard=True,
                                         worktree=".", wait_s=0,
                                         heartbeat_every=0, runner=lambda _cmd: 0)
        self.assertEqual(ctx.exception.code, "RUN_USAGE")


class TestDispatcherResourceReservation(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="mm_dispatch_res_")
        self.board = board_mod.Board(os.path.join(self.dir, "board.db"))
        self.board.init()

    def tearDown(self):
        self.board.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_plan_reserves_blender_for_first_claim(self):
        self.board.add_task("M02", "M02", "A1", status="ready", resource="blender")
        self.board.add_task("M05", "M05", "A3", status="ready", resource="blender")
        wt = make_qualified_repo(self.dir, "wt_dispatch")
        plan = dispatcher_mod.plan(self.board, repo=wt,
                                   worktrees={"A1": wt, "A2": wt, "A3": wt, "A4": wt})
        actions = {row["lane"]: row["action"] for row in plan["assignments"]}
        self.assertEqual(actions["A1"], "claim")
        self.assertEqual(actions["A3"], "idle")
        claimed = [row for row in plan["assignments"] if row["action"] == "claim"]
        self.assertEqual(len(claimed), 1)


if __name__ == "__main__":
    unittest.main()
