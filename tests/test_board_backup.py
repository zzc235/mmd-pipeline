"""S4：board 在线备份与临时恢复验证的契约测试。

对应 reports/coordination/2026-11-18_小模型交接执行约束.md §5.4 的 8 项必加测试。
所有演练只用 tempfile，不碰真实 board，不写个人目录，不执行 bootstrap/resync。

跑法（在 integration 树根）：
    python -B -m unittest tests.test_board_backup -v
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from coordination import board as board_mod
from coordination import board_backup as bb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class BackupCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="mm_s4_")
        self.src = os.path.join(self.dir, "source.db")
        self.dst = os.path.join(self.dir, "backup.db")
        self.board = board_mod.Board(self.src)
        self.board.init()
        # 造出跨多张表的代表性状态：task / dep / artifact / run_id event / resource。
        self.board.add_task("M01", "M01", "A1", status="completed", resource="none",
                            base_commit="abc1234")
        self.board.add_task("M02", "M02", "A1", status="ready", resource="blender")
        self.board.add_dep("M02", "M01", "out/a.json", required_sha="deadbeef")
        self.board.add_artifact("a1", "M01", "out/a.json", "a" * 64)
        self.board.issue_run_id("M02", run_id="RUN_S4_FIXTURE_001")

    def tearDown(self):
        self.board.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def open_ro(self, path):
        return sqlite3.connect("file:%s?mode=ro" % os.path.abspath(path).replace("\\", "/"),
                               uri=True, timeout=5.0)

    def run_cli(self, *args, cwd=ROOT):
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
        return subprocess.run([sys.executable, "-B", "-m", "coordination.board_backup", *args],
                              cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env, timeout=90)


class TestBackupContract(BackupCase):
    def test_01_backup_then_integrity_ok(self):
        """① 正常临时 board 备份后 integrity_check=ok。"""
        manifest = bb.backup_board(self.src, self.dst)
        self.assertEqual(manifest["state"], "OK")
        self.assertEqual(manifest["backup_integrity"], "ok")
        result = bb.verify_backup(self.dst)
        self.assertEqual(result["state"], "OK")
        self.assertEqual(result["integrity"], "ok")

    def test_02_counts_and_representative_rows_match(self):
        """② 关键表行数、代表性任务/event/run_id 一致。"""
        manifest = bb.backup_board(self.src, self.dst)
        self.assertEqual(manifest["tables_source"], manifest["tables_backup"])
        for table in bb.REQUIRED_TABLES:
            self.assertIn(table, manifest["tables_backup"])
        self.assertTrue(manifest["representative_identical"])

        conn = self.open_ro(self.dst)
        try:
            rep = bb.representative(conn)
            self.assertEqual(rep["tasks"]["M01"][0], "completed")
            self.assertEqual(rep["tasks"]["M02"][0], "ready")
            self.assertTrue(any("RUN_S4_FIXTURE_001" in (e[2] or "")
                                for e in rep["events"]))
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM deps WHERE task_id='M02'").fetchone()[0], 1)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM artifacts WHERE artifact_id='a1'").fetchone()[0], 1)
        finally:
            conn.close()

    def test_03_missing_source_fails_without_target(self):
        """③ 源不存在时失败，且不产目标（不造空板备份）。"""
        missing = os.path.join(self.dir, "no-such-board.db")
        with self.assertRaises(bb.BackupError) as ctx:
            bb.backup_board(missing, self.dst)
        self.assertEqual(ctx.exception.state, "SOURCE_MISSING")
        self.assertFalse(os.path.exists(self.dst))

    def test_04_existing_target_refused_bytes_unchanged(self):
        """④ 目标已存在时拒绝覆盖，目标原字节不变。"""
        with open(self.dst, "wb") as fh:
            fh.write(b"KEEP-ME-EXACTLY")
        before = bb.file_sha256(self.dst)
        with self.assertRaises(bb.BackupError) as ctx:
            bb.backup_board(self.src, self.dst)
        self.assertEqual(ctx.exception.state, "DEST_EXISTS")
        self.assertEqual(bb.file_sha256(self.dst), before)
        with open(self.dst, "rb") as fh:
            self.assertEqual(fh.read(), b"KEEP-ME-EXACTLY")

    def test_05_wal_committed_data_enters_backup(self):
        """⑤ WAL 模式下已提交数据能进入备份（不先 checkpoint）。"""
        journal = self.board.db.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(journal.lower(), "wal")
        # 在备份前最后一刻写入一条只在 WAL 里的新提交。
        self.board.issue_run_id("M02", run_id="RUN_S4_WAL_LATEST")
        self.assertTrue(os.path.exists(self.src + "-wal"))

        manifest = bb.backup_board(self.src, self.dst)
        self.assertEqual(manifest["source_journal_mode"], "wal")
        conn = self.open_ro(self.dst)
        try:
            payloads = [r[0] or "" for r in conn.execute("SELECT payload_json FROM events")]
            self.assertTrue(any("RUN_S4_WAL_LATEST" in p for p in payloads))
        finally:
            conn.close()

    def test_06_backup_does_not_change_source(self):
        """⑥ 备份过程不改变源逻辑状态（字节 + 计数 + 事件数）。"""
        sha_before = bb.file_sha256(self.src)
        conn = self.open_ro(self.src)
        try:
            counts_before = bb.logical_counts(conn)
        finally:
            conn.close()
        manifest = bb.backup_board(self.src, self.dst)
        self.assertEqual(manifest["source_sha256_before"], manifest["source_sha256_after"])
        self.assertEqual(sha_before, bb.file_sha256(self.src))
        conn = self.open_ro(self.src)
        try:
            self.assertEqual(bb.logical_counts(conn), counts_before)
        finally:
            conn.close()

    def test_07_verify_is_readonly_and_explicit_path(self):
        """⑦ 恢复验证只在临时副本、显式传路径，且不写副本。"""
        manifest = bb.backup_board(self.src, self.dst)
        sha_before = bb.file_sha256(self.dst)
        # 换一个工作目录跑 CLI，证明路径是显式传入而非依赖 cwd / 默认 board。
        out = self.run_cli(
            "verify", "--backup", self.dst, "--expect-counts",
            os.path.join(self.dir, "counts.json"), cwd=self.dir)
        # 没写 counts.json 时应按 UNEXPECTED 停下，而不是静默成功。
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("UNEXPECTED", out.stderr)

        counts_path = os.path.join(self.dir, "counts.json")
        with open(counts_path, "w", encoding="utf-8") as fh:
            json.dump(manifest["tables_source"], fh)
        out = self.run_cli("verify", "--backup", self.dst, "--expect-counts", counts_path)
        self.assertEqual(out.returncode, 0, out.stderr)
        payload = json.loads(out.stdout)
        self.assertEqual(payload["state"], "OK")
        self.assertTrue(payload["expected_counts_matched"])
        self.assertEqual(bb.file_sha256(self.dst), sha_before)

    def test_08_cli_returns_explicit_exit_codes(self):
        """⑧ CLI/函数失败返回明确状态，不静默成功。"""
        ok = self.run_cli("backup", "--source", self.src, "--dest", self.dst)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(json.loads(ok.stdout)["state"], "OK")

        missing = os.path.join(self.dir, "absent.db")
        bad = self.run_cli("backup", "--source", missing,
                           "--dest", os.path.join(self.dir, "should-not-exist.db"))
        self.assertEqual(bad.returncode, bb.EXIT_SOURCE_MISSING)
        self.assertIn("SOURCE_MISSING", bad.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "should-not-exist.db")))

        dup = self.run_cli("backup", "--source", self.src, "--dest", self.dst)
        self.assertEqual(dup.returncode, bb.EXIT_DEST_EXISTS)
        self.assertIn("DEST_EXISTS", dup.stderr)

        nofile = self.run_cli("verify", "--backup", missing)
        self.assertEqual(nofile.returncode, bb.EXIT_SOURCE_MISSING)
        self.assertIn("SOURCE_MISSING", nofile.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
