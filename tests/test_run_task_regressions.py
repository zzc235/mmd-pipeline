# -*- coding: utf-8 -*-
"""2026-11-17 架构审阅发现的协调层回归契约。

这些用例不启动 Blender、不触碰真实 board；所有写操作都落在临时目录。
预期：修复前多数用例为 RED，修复后同一组用例必须全部转 GREEN。
"""
import io
import json
import os
import shutil
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from coordination import board as board_mod
from coordination import run_task as run_task_mod
from coordination import sync_board as sync_board_mod


class RunTaskMainCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="mm_run_task_contract_")
        self.board = board_mod.Board(os.path.join(self.dir, "board.db"))
        self.board.init()
        self.spec = os.path.join(self.dir, "preflight.json")
        with open(self.spec, "w", encoding="utf-8") as fh:
            json.dump({}, fh)

    def tearDown(self):
        self.board.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def add_task(self, resource="none"):
        self.board.add_task("M02", "M02", "A1", status="ready", resource=resource)

    def argv(self, *extra):
        return [
            "--board", self.board.path,
            "--task", "M02", "--agent", "A1",
            "--worktree", self.dir, "--spec", self.spec,
            "--claim", *extra,
            "--", "python", "fake-job.py",
        ]

    def snapshot(self):
        return {
            "task": self.board.task("M02"),
            "events": [row["type"] for row in self.board.events()],
            "resources": [dict(row) for row in self.board.db.execute(
                "SELECT resource, holder, lease_until, task_id FROM resources ORDER BY resource")],
        }

    def ready_preflight(self, spec, worktree):
        return {"state": "READY", "reason_code": "EVIDENCE_COMPLETE", "detail": "test"}

    def fake_worktree(self, worktree, base="", head="", allow_dirty=False):
        return {"root": worktree, "head": head or "a" * 40,
                "base": base, "dirty": bool(allow_dirty)}

    def test_dry_run_has_zero_board_side_effects(self):
        """dry-run 不得 claim/start、发号、占资源或执行命令。"""
        self.add_task()
        before = self.snapshot()
        stdout = io.StringIO()
        with mock.patch.object(run_task_mod, "verify_worktree", side_effect=self.fake_worktree), \
             mock.patch.object(run_task_mod.preflight_mod, "check", side_effect=self.ready_preflight), \
             mock.patch.object(run_task_mod, "execute_command", return_value={"rc": 0}) as execute:
            with redirect_stdout(stdout):
                rc = run_task_mod.main(self.argv("--dry-run"))
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(stdout.getvalue())["state"], "DRY_RUN")
        execute.assert_not_called()
        self.assertEqual(self.snapshot(), before, "dry-run 改写了 board 逻辑状态")

    def test_preflight_rejection_does_not_leave_task_running(self):
        """任何开工前拒绝都必须保持原状态，不能留下 running/资源占用。"""
        self.add_task(resource="blender")
        before = self.snapshot()
        blocked = {"state": "BLOCKED", "reason_code": "CAP_UNMET", "detail": "test"}
        stdout = io.StringIO()
        with mock.patch.object(run_task_mod, "verify_worktree", side_effect=self.fake_worktree), \
             mock.patch.object(run_task_mod.preflight_mod, "check", return_value=blocked), \
             mock.patch.object(run_task_mod, "execute_command") as execute:
            with redirect_stdout(stdout):
                rc = run_task_mod.main(self.argv())
        self.assertEqual(rc, 4)
        execute.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_command_failure_is_recorded_and_fail_closed(self):
        """执行失败必须留下 RUN_FAILED，并进入 blocked，等待显式处置。"""
        self.add_task()
        stdout = io.StringIO()
        with mock.patch.object(run_task_mod, "verify_worktree", side_effect=self.fake_worktree), \
             mock.patch.object(run_task_mod.preflight_mod, "check", side_effect=self.ready_preflight), \
             mock.patch.object(run_task_mod, "execute_command", return_value={"rc": 7, "command": ["x"]}):
            with redirect_stdout(stdout):
                rc = run_task_mod.main(self.argv())
        self.assertEqual(rc, 7)
        self.assertEqual(json.loads(stdout.getvalue())["state"], "COMMAND_FAILED")
        self.assertEqual(self.board.task("M02")["status"], "blocked")
        self.assertIsNone(self.board.task("M02")["owner"])
        self.assertIn("RUN_FAILED", [row["type"] for row in self.board.events()])

    def test_no_lock_is_rejected_for_non_none_resource(self):
        """--no-lock 只允许 resource=none；拒绝时不得先 claim/start。"""
        self.add_task(resource="blender")
        before = self.snapshot()
        stdout = io.StringIO()
        with mock.patch.object(run_task_mod, "verify_worktree", side_effect=self.fake_worktree), \
             mock.patch.object(run_task_mod.preflight_mod, "check", side_effect=self.ready_preflight), \
             mock.patch.object(run_task_mod, "execute_command", return_value={"rc": 0}) as execute:
            with redirect_stdout(stdout):
                rc = run_task_mod.main(self.argv("--no-lock"))
        self.assertEqual(rc, 4)
        self.assertEqual(json.loads(stdout.getvalue())["reason_code"], "RUN_USAGE")
        execute.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_board_lease_is_heartbeated_while_command_runs(self):
        """文件锁心跳不等于 board 心跳；1.2 秒任务必须续过 1 秒租约。"""
        self.add_task()
        lease_alive = []

        def fake_subprocess_run(command, cwd=None):
            time.sleep(1.2)
            task = self.board.task("M02")
            lease = datetime.fromisoformat(task["lease_until"])
            lease_alive.append(lease >= datetime.now(timezone.utc))
            return SimpleNamespace(returncode=0)

        stdout = io.StringIO()
        with mock.patch.object(run_task_mod, "verify_worktree", side_effect=self.fake_worktree), \
             mock.patch.object(run_task_mod.preflight_mod, "check", side_effect=self.ready_preflight), \
             mock.patch.object(run_task_mod.subprocess, "run", side_effect=fake_subprocess_run):
            with redirect_stdout(stdout):
                rc = run_task_mod.main(self.argv("--lease", "1", "--heartbeat-every", "0.05"))
        self.assertEqual(rc, 0)
        self.assertEqual(lease_alive, [True], "命令仍在执行时 board 租约已经过期")

    def test_board_heartbeat_extends_resource_lease(self):
        """任务心跳必须同时续 resources 表，不能只续 tasks 行。"""
        clock = [datetime(2026, 11, 17, tzinfo=timezone.utc)]
        b = board_mod.Board(os.path.join(self.dir, "resource_heartbeat.db"),
                            clock=lambda: clock[0])
        try:
            b.init()
            b.add_task("M02", "M02", "A1", status="ready", resource="blender")
            b.claim("A1", "A1", lease_seconds=1)
            b.start("M02", lease_seconds=1)
            before = b.db.execute(
                "SELECT lease_until FROM resources WHERE task_id='M02'").fetchone()[0]
            clock[0] += timedelta(seconds=2)
            b.heartbeat("M02", lease_seconds=5)
            task_lease = b.task("M02")["lease_until"]
            resource_lease = b.db.execute(
                "SELECT lease_until FROM resources WHERE task_id='M02'").fetchone()[0]
            self.assertEqual(resource_lease, task_lease)
            self.assertGreater(resource_lease, before)
        finally:
            b.close()

    def test_allow_dirty_still_reports_dirty_true(self):
        """允许脏树继续跑，不等于把脏树伪报成干净。"""
        def fake_git(worktree, *args):
            if args == ("rev-parse", "--show-toplevel"):
                return worktree
            if args == ("rev-parse", "HEAD"):
                return "a" * 40
            if args == ("status", "--porcelain"):
                return " M coordination/run_task.py"
            raise AssertionError(args)

        with mock.patch.object(run_task_mod, "_git", side_effect=fake_git):
            result = run_task_mod.verify_worktree(self.dir, allow_dirty=True)
        self.assertTrue(result["dirty"])

    def test_non_ancestor_base_is_rejected(self):
        """正控：dispatcher 即使派错基线，run_task 的最后一道 base 闸门仍必须有效。"""
        def fake_git(worktree, *args):
            if args == ("rev-parse", "--show-toplevel"):
                return worktree
            if args == ("rev-parse", "HEAD"):
                return "b" * 40
            if args == ("status", "--porcelain"):
                return ""
            raise AssertionError(args)

        with mock.patch.object(run_task_mod, "_git", side_effect=fake_git), \
             mock.patch.object(run_task_mod.subprocess, "run", return_value=SimpleNamespace(returncode=1)):
            with self.assertRaises(run_task_mod.RunTaskError) as ctx:
                run_task_mod.verify_worktree(self.dir, base="a" * 40)
        self.assertEqual(ctx.exception.code, "PROVENANCE_INVALID")


class SyncBoardCheckDriftCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="mm_sync_check_contract_")
        self.board = board_mod.Board(os.path.join(self.dir, "board.db"))
        self.board.init()
        self.status_path = os.path.join(self.dir, "task_status.json")
        self.decisions_path = os.path.join(self.dir, "decisions.jsonl")
        self.graph_path = os.path.join(self.dir, "task_graph.json")
        with open(self.status_path, "w", encoding="utf-8") as fh:
            json.dump({"tasks": {
                "M00": {"status": "PASS", "next": ""},
                "M01": {"status": "PARTIAL", "next": ""},
            }}, fh)
        rows = [
            {"decision_id": "D-TEST-000", "task_id": "M00", "decision": "ACCEPT_MERGE"},
            {"decision_id": "D-TEST-001", "task_id": "M01", "decision": "ACCEPT_INTERFACE"},
        ]
        with open(self.decisions_path, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")
        with open(self.graph_path, "w", encoding="utf-8") as fh:
            json.dump({
                "resources": {"M00": "none", "M01": "blender"},
                "dependencies": {"M01": [{"task": "M00", "artifact": ""}]},
            }, fh)
        sync_board_mod.sync(self.status_path, self.decisions_path, self.board.path,
                            repo=self.dir, mode="bootstrap", graph_path=self.graph_path)

    def tearDown(self):
        self.board.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def check(self):
        return sync_board_mod.sync(self.status_path, self.decisions_path, self.board.path,
                                   repo=self.dir, mode="check", graph_path=self.graph_path)

    def assert_drift_detected(self, needle):
        result = self.check()
        self.assertEqual(result["state"], "PHASE_B_CHECK_CONFLICT")
        self.assertIn(needle, json.dumps(result.get("conflicts", []), ensure_ascii=False))

    def test_check_detects_resource_drift(self):
        with self.board.tx() as c:
            c.execute("UPDATE tasks SET resource='none' WHERE task_id='M01'")
        self.assert_drift_detected("resource")

    def test_check_detects_dependency_drift(self):
        with self.board.tx() as c:
            c.execute("DELETE FROM deps WHERE task_id='M01'")
        self.assert_drift_detected("deps")


if __name__ == "__main__":
    unittest.main()
