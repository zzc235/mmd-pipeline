"""`coordination.lock`：fail-closed 的互斥锁与三条「应当被拒」的路径。

背景（2026-11-16，一天撞出两次事故）：
  * `New-Item -Force` 在目录已存在时不报错 ⇒ 以为取到了锁，两个人真并行跑过 Blender；
  * `finally { Remove-Item -Recurse -Force }` 无条件删 ⇒ 删掉别人的锁，等于替人宣布"跑完了"。

所以这里的每条拒绝都要有测试：**取别人的锁要抛、释放别人的锁要抛、残缺锁不许当空闲**。
"""
import datetime as dt
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from coordination import lock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MINE = "模块负责4|A4"
OTHER = "模块负责1|A1"


class _TmpLock(object):
    """临时锁目录的公共夹具（不带 test_*，免得子类把它们重复跑一遍）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="m00_lock_")
        self.dir = os.path.join(self.tmp, "blender.lock")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def owner_file(self, text):
        os.makedirs(self.dir, exist_ok=True)
        with open(os.path.join(self.dir, "owner.txt"), "w", encoding="utf-8") as fh:
            fh.write(text + "\n")

    # ---------------------------------------------------------------- 应当被拒
    def test_acquire_twice_raises_and_keeps_first_owner(self):
        lock.acquire(MINE, "第一次", self.dir)
        with self.assertRaises(lock.LockHeld) as ctx:
            lock.acquire(OTHER, "第二次", self.dir)
        self.assertIn(MINE, str(ctx.exception))
        # 持有者没被覆盖
        self.assertEqual(lock.read_owner(self.dir)["ident"], MINE)

    def test_release_someone_elses_lock_raises_and_does_not_delete(self):
        lock.acquire(OTHER, "别人的", self.dir)
        with self.assertRaises(lock.NotOwner) as ctx:
            lock.release(MINE, self.dir)
        self.assertIn(OTHER, str(ctx.exception))
        self.assertTrue(os.path.isdir(self.dir), "不该删掉别人的锁")
        self.assertEqual(lock.read_owner(self.dir)["ident"], OTHER)

    def test_incomplete_lock_is_not_treated_as_free(self):
        os.makedirs(self.dir)                      # 目录在、owner.txt 不在
        with self.assertRaises(lock.IncompleteLock):
            lock.status(self.dir)
        with self.assertRaises(lock.IncompleteLock):
            lock.acquire(MINE, "想取", self.dir)    # 也不许当空闲抢走
        with self.assertRaises(lock.IncompleteLock):
            lock.release(MINE, self.dir)

    def test_owner_requires_module_and_worktree(self):
        with self.assertRaises(ValueError):
            lock.acquire("只有模块名", "", self.dir)

    # ---------------------------------------------------------------- 正常路径
    def test_acquire_status_release(self):
        info = lock.acquire(MINE, "打包", self.dir)
        self.assertIn("PID=", info["raw"])
        st = lock.status(self.dir)
        self.assertTrue(st["held"])
        self.assertEqual(st["ident"], MINE)
        self.assertEqual(st["note"], "打包")
        self.assertGreaterEqual(st["held_seconds"], 0.0)
        lock.release(MINE, self.dir)
        self.assertFalse(os.path.isdir(self.dir))
        self.assertFalse(lock.status(self.dir)["held"])

    def test_status_reports_hold_duration(self):
        self.owner_file("%s|PID=1234|%s|跑长活" % (
            MINE, (dt.datetime.now().astimezone() - dt.timedelta(seconds=42)).isoformat(timespec="seconds")))
        st = lock.status(self.dir)
        self.assertGreaterEqual(st["held_seconds"], 40.0)
        self.assertIn("已占用", lock.render_status(st))

    def test_wait_acquires_after_holder_releases(self):
        lock.acquire(OTHER, "别人先跑", self.dir)

        def _release_soon():
            time.sleep(0.4)
            lock.release(OTHER, self.dir)

        t = threading.Thread(target=_release_soon)
        t.start()
        info = lock.acquire(MINE, "我等", self.dir, wait_s=3.0, poll_s=0.05)
        t.join()
        self.assertEqual(lock.read_owner(self.dir)["ident"], MINE)
        self.assertIn(MINE, info["raw"])

    def test_wait_timeout_raises(self):
        lock.acquire(OTHER, "占着", self.dir)
        with self.assertRaises(lock.LockHeld):
            lock.acquire(MINE, "等不到", self.dir, wait_s=0.3, poll_s=0.05)


class TestLockFS(_TmpLock, unittest.TestCase):
    """CLI 退出码：0 正常 / 3 冲突 / 4 状态不可判定。"""

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "coordination.lock", *args],
                              cwd=ROOT, capture_output=True,
                              text=True, encoding="utf-8", timeout=60)

    def test_cli_acquire_status_release(self):
        out = self.run_cli("acquire", "--lock", self.dir, "--owner", MINE, "--note", "CLI")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("ACQUIRED", out.stdout)
        st = self.run_cli("status", "--lock", self.dir)
        self.assertEqual(st.returncode, 0)
        self.assertIn("持有", st.stdout)
        rel = self.run_cli("release", "--lock", self.dir, "--owner", MINE)
        self.assertEqual(rel.returncode, 0)
        self.assertIn("RELEASED", rel.stdout)

    def test_cli_acquire_while_held_exits_3_and_prints_owner(self):
        self.owner_file("%s|PID=99|%s|占着" % (OTHER, dt.datetime.now().astimezone().isoformat(timespec="seconds")))
        out = self.run_cli("acquire", "--lock", self.dir, "--owner", MINE)
        self.assertEqual(out.returncode, lock.EXIT_CONFLICT, out.stdout + out.stderr)
        self.assertIn("LOCK_HELD", out.stdout)
        self.assertIn(OTHER, out.stdout)

    def test_cli_release_not_your_lock_exits_3(self):
        lock.acquire(OTHER, "别人的", self.dir)
        out = self.run_cli("release", "--lock", self.dir, "--owner", MINE)
        self.assertEqual(out.returncode, lock.EXIT_CONFLICT, out.stdout + out.stderr)
        self.assertIn("LOCK_NOT_YOURS", out.stdout)
        self.assertTrue(os.path.isdir(self.dir))

    def test_cli_incomplete_lock_exits_4(self):
        os.makedirs(self.dir)
        out = self.run_cli("status", "--lock", self.dir)
        self.assertEqual(out.returncode, lock.EXIT_UNKNOWN, out.stdout + out.stderr)
        self.assertIn("LOCK_UNKNOWN", out.stdout)

    def test_cli_usage_error_exits_2(self):
        out = self.run_cli("acquire", "--lock", self.dir, "--owner", "没有分隔符")
        self.assertEqual(out.returncode, lock.EXIT_USAGE, out.stdout + out.stderr)

    def test_cli_status_on_free_lock_exits_0(self):
        out = self.run_cli("status", "--lock", self.dir)
        self.assertEqual(out.returncode, 0)
        self.assertIn("空闲", out.stdout)


if __name__ == "__main__":
    unittest.main()
