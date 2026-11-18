# -*- coding: utf-8 -*-
"""入口层闸门接线回归（2026-11-18 M02 第二次执行暴露）。

两个真实缺陷，都用「修复前 RED / 修复后 GREEN」的契约钉死：

A. ``run_task`` / ``scheduler submit`` 没把闸门包传给 ``board.submit(gate=)``，
   于是任何带 ``truth_tier`` 的 evidence 经入口提交都 ``GATE_FAILED: 缺闸门包``。
   ``board.submit`` 本身支持 gate，这是纯入口接线缺失。
B. ``--`` 后的命令数组没展开 ``{run_id}`` 占位符，产物落到字面的 ``{run_id}`` 目录；
   spec 内部的占位符由 ``_format_value`` 展开，命令却直接透传。

这些用例不启动 Blender、不触碰真实 board；所有写操作落临时目录。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from coordination import board as board_mod
from coordination import run_task as run_task_mod
from coordination import scheduler as scheduler_mod


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _evidence(task_id="M02", attempt=1, with_tier=True):
    ev = {
        "spec": "evidence/1",
        "task_id": task_id,
        "attempt": attempt,
        "status": "PASS",
        "files": [{"path": "mmdpipe/pmx.py", "sha256": _sha("pmx"), "tracked": True}],
        "tests": [{"cmd": "blender -b -P fake.py", "exit": 0,
                   "passed": 1, "failed": 0, "skipped": 0}],
        "artifacts": [],
        "known_risks": [],
    }
    if with_tier:
        ev["truth_tier"] = "T1"
    return ev


class GateWiringCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="mm_gate_wiring_")
        self.db_path = os.path.join(self.dir, "board.db")
        seed = board_mod.Board(self.db_path)
        seed.init()
        seed.add_task("M02", "M02", "A1", status="ready", resource="none")
        seed.close()
        # 一个真实存在的源码路径，供闸门包的 provenance 检查。
        self.src = os.path.join(self.dir, "mmdpipe", "pmx.py")
        os.makedirs(os.path.dirname(self.src), exist_ok=True)
        with open(self.src, "w", encoding="utf-8") as fh:
            fh.write("# fake source\n")
        self.ev_path = os.path.join(self.dir, "evidence.json")
        self.gate_path = os.path.join(self.dir, "gate.json")
        self.spec_path = os.path.join(self.dir, "spec.json")
        with open(self.ev_path, "w", encoding="utf-8") as fh:
            json.dump(_evidence(), fh)
        with open(self.gate_path, "w", encoding="utf-8") as fh:
            json.dump(self._gate_bundle(), fh)
        with open(self.spec_path, "w", encoding="utf-8") as fh:
            json.dump({}, fh)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _gate_bundle(self):
        return {
            "task_id": "M02",
            "evidence_check_exit": 0,
            "coverage_check": "PASS",
            "acceptance_result": "NOT_APPLICABLE",
            "truth_tier": "T1",
            "resource_lease_valid": True,
            "module_provenance": {"src": self.src},
            "snapshot_paths": [],
        }

    def _argv(self, *extra):
        return [
            "--board", self.db_path,
            "--task", "M02", "--agent", "A1",
            "--worktree", self.dir, "--spec", self.spec_path,
            "--claim", "--start", *extra,
            "--", "python", "job.py", "out/{run_id}/x.json",
        ]

    def _run_main(self, argv):
        """每次 Board() 返回指向同一 db 的独立实例（main 的 finally 会 close 它）。"""
        real_board_cls = board_mod.Board  # patch 前先存原始类，避免递归
        def fresh_board(*_a, **_kw):
            return real_board_cls(self.db_path)
        patches = (
            mock.patch.object(run_task_mod.board_mod, "Board", new=fresh_board),
            mock.patch.object(run_task_mod, "verify_worktree",
                              return_value={"root": self.dir, "dirty": False,
                                            "base": "", "head": "h" * 40}),
            mock.patch.object(run_task_mod.preflight_mod, "check",
                              return_value={"state": "READY", "reason_code": "OK", "detail": "t"}),
            mock.patch.object(run_task_mod, "execute_command",
                              return_value={"rc": 0, "command": []}),
        )
        out = io.StringIO()
        with patches[0], patches[1], patches[2], patches[3]:
            with redirect_stdout(out):
                rc = run_task_mod.main(argv)
        lines = [x for x in out.getvalue().strip().splitlines() if x.strip().startswith("{")]
        result = json.loads(lines[-1]) if lines else {}
        return rc, result

    def _queue_count(self):
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            return con.execute("SELECT COUNT(*) FROM submission_queue").fetchone()[0]
        finally:
            con.close()

    # ---- 缺陷 A：gate 必须被读入并透传 ----

    def test_run_task_passes_gate_to_submit(self):
        argv = self._argv("--evidence", self.ev_path, "--gate", self.gate_path)
        rc, result = self._run_main(argv)
        self.assertEqual(rc, 0, result)
        self.assertEqual(result["state"], "RUN_OK")
        self.assertEqual(result["submit"]["state"], "submitted")
        self.assertEqual(self._queue_count(), 1)

    def test_run_task_without_gate_still_rejected_for_tiered_evidence(self):
        """不带 --gate 时，带 truth_tier 的 evidence 仍被 board 拒（fail-closed 保留）。"""
        argv = self._argv("--evidence", self.ev_path)
        rc, result = self._run_main(argv)
        self.assertEqual(result["state"], "REJECTED")
        self.assertEqual(result["reason_code"], "GATE_FAILED")
        self.assertEqual(self._queue_count(), 0)

    def test_scheduler_submit_has_gate_argument(self):
        args = scheduler_mod.build_parser().parse_args(
            ["submit", "--task", "M02", "--evidence", self.ev_path, "--gate", self.gate_path])
        self.assertEqual(args.gate, self.gate_path)
        args2 = scheduler_mod.build_parser().parse_args(
            ["submit", "--task", "M02", "--evidence", self.ev_path])
        self.assertEqual(args2.gate, "")

    # ---- 缺陷 B：命令中的 {run_id} 必须展开 ----

    def test_dry_run_expands_run_id_in_command(self):
        argv = self._argv("--dry-run", "--run-id", "RID42")
        rc, result = self._run_main(argv)
        self.assertEqual(rc, 0, result)
        self.assertIn("out/RID42/x.json", result["command"])
        self.assertNotIn("{run_id}", " ".join(result["command"]))

    def test_missing_placeholder_in_command_is_refused(self):
        argv = [
            "--board", self.db_path, "--task", "M02", "--agent", "A1",
            "--worktree", self.dir, "--spec", self.spec_path, "--claim", "--dry-run",
            "--run-id", "RID42", "--", "python", "job.py", "out/{unknown_key}/x.json",
        ]
        rc, result = self._run_main(argv)
        self.assertEqual(result["state"], "REJECTED")
        self.assertEqual(result["reason_code"], "MISSING_EVIDENCE")


if __name__ == "__main__":
    unittest.main()
