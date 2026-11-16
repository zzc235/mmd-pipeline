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
        """子进程环境钉成**最坏情况** `PYTHONIOENCODING=gbk`，父进程按 UTF-8 严格解码。

        这是 2026-11-16 那次 main 变红的教训：只钉测试侧会把红搬到默认环境。
        钉最坏环境 + 严格解码，才能一条测试同时管住「产品侧有没有 `reconfigure`」。
        """
        env = dict(os.environ)
        env.pop("PYTHONIOENCODING", None)
        env["PYTHONIOENCODING"] = "gbk"
        return subprocess.run([sys.executable, "-m", "coordination.lock", *args],
                              cwd=ROOT, capture_output=True, env=env,
                              text=True, encoding="utf-8", timeout=60)

    def test_cli_acquire_status_release(self):
        out = self.run_cli("acquire", "--lock", self.dir, "--owner", MINE, "--note", "CLI")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("ACQUIRED", out.stdout)
        st = self.run_cli("status", "--lock", self.dir)
        self.assertEqual(st.returncode, 0)
        self.assertTrue(st.stdout.strip(), "CLI 没有任何输出（None 与空串同一类坑）")
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


class TestHeartbeatAndReclaim(_TmpLock, unittest.TestCase):
    """2026-11-16 14:19 的三处加固：记真正干活的 PID / 心跳 / 回收必须「搬走」。

    起因是一次真实误判：`status` 报 `PID=28940` 已死，**但 Blender 还活着**（另一个 PID）。
    按「PID 死了」判过期就会把别人正在用的锁拿走。所以三条必须同时成立才允许回收。
    """

    def test_pid_alive_is_safe_probe(self):
        """**不许用 `os.kill(pid, 0)` 探活**：Windows 上那是 TerminateProcess，会杀掉对方。

        2026-11-16 自报：第一版就是这么写的，测试里传了自己的 PID，测试进程当场消失、
        一个字节输出都没有——看起来像"无声崩溃"，其实是自己在自杀。
        """
        self.assertTrue(lock.pid_alive(os.getpid()), "自己的 PID 必须是活的")
        self.assertFalse(lock.pid_alive(0))
        self.assertFalse(lock.pid_alive("不是数字"))
        # 一个**不存在**的 PID 必须返回 False，而且不能把任何东西弄死
        self.assertFalse(lock.pid_alive(4000000))
        self.assertTrue(lock.pid_alive(os.getpid()), "探完一个不存在的 PID，自己还得活着")

    def test_acquire_writes_heartbeat_and_records_work_pid(self):
        lock.acquire(MINE, "跑 Blender", self.dir, work_pids=["123456"])
        raw = lock.read_owner(self.dir)["raw"]
        self.assertIn("PID=", raw)
        self.assertIn("123456", raw)          # 真正干活的 PID 也记进去了
        self.assertTrue(os.path.isfile(os.path.join(self.dir, lock.HEARTBEAT_FILE)))
        self.assertLess(lock.heartbeat_age_seconds(self.dir), 5.0)

    def test_missing_heartbeat_is_infinite_not_zero(self):
        """从来没写过心跳 = `inf`。返回 0 会让「从没跳过」看起来「刚刚还活着」。"""
        self.owner_file(MINE + "|PID=999999|2026-11-16T00:00:00+08:00|无心跳")
        self.assertEqual(lock.heartbeat_age_seconds(self.dir), float("inf"))

    def test_touch_refreshes_and_refuses_other_s_owner(self):
        lock.acquire(MINE, "长跑", self.dir)
        os.utime(os.path.join(self.dir, lock.HEARTBEAT_FILE), (0, 0))   # 假装很久没跳
        self.assertGreater(lock.heartbeat_age_seconds(self.dir), 1000.0)
        lock.touch(MINE, self.dir)
        self.assertLess(lock.heartbeat_age_seconds(self.dir), 5.0)
        with self.assertRaises(lock.NotOwner):
            lock.touch(OTHER, self.dir)

    # ---------------------------------------------------------------- 应当被拒
    def test_reclaim_refused_while_blender_runs(self):
        """**这条是主负控**：PID 已死、心跳也过期，但系统里还有 blender → 不许回收。"""
        self.owner_file(MINE + "|PID=999999|2026-11-16T00:00:00+08:00|假的")
        os.utime(os.path.join(self.dir, "owner.txt"), (0, 0))
        with open(os.path.join(self.dir, lock.HEARTBEAT_FILE), "w", encoding="utf-8") as fh:
            fh.write("x\n")
        os.utime(os.path.join(self.dir, lock.HEARTBEAT_FILE), (0, 0))
        with self.assertRaises(lock.LockHeld) as ctx:
            lock.reclaim(self.dir, stale_minutes=1, blender_pids=[4242])
        self.assertIn("blender", str(ctx.exception))
        self.assertTrue(os.path.isdir(self.dir), "拒绝时不许动锁目录")
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "owner.txt")))

    def test_reclaim_refused_while_owner_pid_alive(self):
        self.owner_file(MINE + "|PID=%d|2026-11-16T00:00:00+08:00|就是我" % os.getpid())
        with open(os.path.join(self.dir, lock.HEARTBEAT_FILE), "w", encoding="utf-8") as fh:
            fh.write("x\n")
        os.utime(os.path.join(self.dir, lock.HEARTBEAT_FILE), (0, 0))
        with self.assertRaises(lock.LockHeld):
            lock.reclaim(self.dir, stale_minutes=1, blender_pids=[])

    def test_reclaim_refused_while_heartbeat_fresh(self):
        """心跳还很新 → 不许回收，哪怕 PID 已死、没有 blender（可能刚换了个进程在干）。"""
        self.owner_file(MINE + "|PID=999999|2026-11-16T00:00:00+08:00|假的")
        with open(os.path.join(self.dir, lock.HEARTBEAT_FILE), "w", encoding="utf-8") as fh:
            fh.write("x\n")
        with self.assertRaises(lock.LockHeld) as ctx:
            lock.reclaim(self.dir, stale_minutes=10, blender_pids=[])
        self.assertIn("心跳", str(ctx.exception))

    # ---------------------------------------------------------------- 应当成功
    def test_reclaim_moves_instead_of_deleting(self):
        """三条都成立时回收：**搬走**，`owner.txt` 原样保留作为证据。"""
        self.owner_file(MINE + "|PID=999999|2026-11-16T10:00:00+08:00|留下的证据")
        with open(os.path.join(self.dir, lock.HEARTBEAT_FILE), "w", encoding="utf-8") as fh:
            fh.write("x\n")
        os.utime(os.path.join(self.dir, lock.HEARTBEAT_FILE), (0, 0))
        info = lock.reclaim(self.dir, stale_minutes=1, blender_pids=[])
        self.assertFalse(os.path.isdir(self.dir))
        self.assertTrue(os.path.isdir(info["moved_to"]))
        kept = os.path.join(info["moved_to"], "owner.txt")
        self.assertTrue(os.path.isfile(kept), "证据必须留着")
        with open(kept, encoding="utf-8") as fh:
            self.assertIn("留下的证据", fh.read())
        self.assertTrue(info["moved_to"].replace("\\", "/").count("/_reclaimed/") == 1)
        # 搬走之后就能重新取锁了
        lock.acquire(OTHER, "接手", self.dir)

    def run_cli(self, *args):
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "gbk"          # 最坏环境：子进程钉 GBK，父进程按 UTF-8 解
        return subprocess.run([sys.executable, "-m", "coordination.lock", *args],
                              cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                              env=env, timeout=120)

    def test_cli_touch_and_reclaim_exit_codes(self):
        lock.acquire(MINE, "长跑", self.dir)
        out = self.run_cli("touch", "--lock", self.dir, "--owner", MINE)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertTrue(out.stdout.strip(), "CLI 没有任何输出（None 与空串同色坑）")
        # 心跳新鲜 → 回收必须被拒（exit 3）
        out = self.run_cli("reclaim", "--lock", self.dir, "--stale-minutes", "10")
        self.assertEqual(out.returncode, lock.EXIT_CONFLICT, out.stdout + out.stderr)
        self.assertIn("LOCK_HELD", out.stdout)


if __name__ == "__main__":
    unittest.main()
