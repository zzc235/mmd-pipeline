"""协调层（M00）契约测试：13 §10 的 12 条 + evidence_hash 的 H1–H6。

跑法（在任一 worktree 根）：
    python -m unittest discover -s tests        # 与其他模块的测试一起跑
    python -m unittest tests.test_coordination -v
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from coordination import board as board_mod
from coordination import dispatcher as dispatcher_mod
from coordination import evidence as evidence_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def evidence(task_id="M01", attempt=1, files=None, tests=None, artifacts=None,
             risks=None, summary="说明不参与哈希", status="PASS"):
    return {
        "spec": "evidence/1",
        "task_id": task_id,
        "attempt": attempt,
        "status": status,
        "summary": summary,
        "files": files if files is not None else [
            {"path": "mmdpipe/pmx.py", "sha256": sha("pmx"), "tracked": True}],
        "tests": tests if tests is not None else [
            {"cmd": "python -m unittest discover -s tests", "exit": 0,
             "passed": 12, "failed": 0, "skipped": 0}],
        "artifacts": artifacts or [],
        "known_risks": risks or [],
    }


class BoardCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="mm00_")
        self.board = board_mod.Board(os.path.join(self.dir, "board.db"))
        self.board.init()

    def tearDown(self):
        self.board.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def ready_task(self, task_id="M01", module="M01", lane="A1", resource="none"):
        return self.board.add_task(task_id, module, lane, status="ready", resource=resource)

    def run_to_verified(self, task_id="M01", module="M01", lane="A1", attempt=1):
        self.board.add_task(task_id, module, lane, status="ready")
        self.board.claim(lane, lane)
        self.board.start(task_id)
        self.board.submit(task_id, evidence(task_id=task_id, attempt=attempt))
        self.board.verify_begin()
        return self.board.decide(task_id, "ACCEPT_MERGE")


class TestClaim(BoardCase):
    def test_01_two_processes_claim_once(self):
        """13 §10-1：两个进程同时 claim 同一个 ready，只有一个成功。"""
        self.ready_task()
        cmd = [sys.executable, "-m", "coordination.scheduler", "claim",
               "--board", self.board.path, "--lane", "A1", "--agent", "A1"]
        p1 = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        p2 = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        outs = [p1.communicate(timeout=60)[0], p2.communicate(timeout=60)[0]]
        states = [json.loads(o.strip().splitlines()[-1]) for o in outs]
        claimed = [s for s in states if s.get("task_id") == "M01"]
        idles = [s for s in states if s.get("state") == "IDLE"]
        self.assertEqual(len(claimed), 1, states)
        self.assertEqual(len(idles), 1, states)
        self.assertEqual(self.board.task("M01")["status"], "claimed")

    def test_02_agent_cannot_hold_two(self):
        """13 §10-2：一个 Agent 不能同时持有两个 running。"""
        self.ready_task("M01")
        self.ready_task("M02", "M02")
        self.assertIsNotNone(self.board.claim("A1", "A1"))
        self.assertIsNone(self.board.claim("A1", "A1"))
        self.assertEqual(self.board.task("M02")["status"], "ready")

    def test_pick_order_prefers_unlocker(self):
        """派工优先级：解锁下游数量降序 → task_id 升序（固定可复现）。"""
        self.ready_task("M02", "M02")
        self.ready_task("M01", "M01")
        self.board.add_task("M09", "M09", "A1", status="blocked")
        self.board.add_dep("M09", "M01", "patch.json")
        self.board.add_dep("M09", "M02", "s2.json")
        self.board.add_dep("M09", "M02", "s2b.json")
        self.assertEqual(self.board.claim("A1", "A1")["task_id"], "M01")


class TestDeps(BoardCase):
    def test_03_missing_artifact_keeps_blocked(self):
        """13 §10-3：依赖产物缺失，任务保持 blocked，不被派工。"""
        self.board.add_task("M09", "M09", "A1", status="blocked")
        self.board.add_dep("M09", "M01", "patch.json", required_sha=sha("patch"))
        self.board.recompute_deps()
        self.assertEqual(self.board.task("M09")["status"], "blocked")
        plan = dispatcher_mod.plan(self.board)
        self.assertFalse([a for a in plan["assignments"] if a.get("task_id") == "M09"])

    def test_dep_with_artifact_unlocks(self):
        self.board.add_task("M01", "M01", "A1", status="ready")
        self.board.add_task("M09", "M09", "A1", status="blocked")
        self.board.add_dep("M09", "M01", "patch.json", required_sha=sha("patch"))
        self.board.add_artifact("a1", "M01", "patch.json", sha("patch"))
        self.board.recompute_deps()
        self.assertEqual(self.board.task("M09")["status"], "ready")


class TestSubmissionQueue(BoardCase):
    def test_04_two_finish_only_one_submitted(self):
        """13 §10-4：两个任务同时完成，只有一条进入 submitted。"""
        self.board.add_task("M01", "M01", "A1", status="ready")
        self.board.add_task("M03", "M03", "A2", status="ready")
        self.board.claim("A1", "A1")
        self.board.start("M01")
        self.board.claim("A2", "A2")
        self.board.start("M03")
        first = self.board.submit("M01", evidence("M01", 1))
        second = self.board.submit("M03", evidence("M03", 1))
        self.assertEqual(first["state"], "submitted")
        self.assertEqual(second["state"], "queued")
        self.assertEqual(self.board.task("M01")["status"], "submitted")
        self.assertEqual(self.board.task("M03")["status"], "queued_submission")

    def test_05_queue_full_pauses_dispatch(self):
        """13 §10-5：队列满 2，dispatcher 暂停派新任务。"""
        for task, lane in (("M01", "A1"), ("M03", "A2"), ("M05", "A3")):
            self.board.add_task(task, task, lane, status="ready")
        # 先让 A3 手上拿着活（否则背压生效后它连 claim 都拿不到）
        self.board.claim("A3", "A3")
        self.board.start("M05")
        self.board.claim("A1", "A1")
        self.board.start("M01")
        self.board.submit("M01", evidence("M01"))
        self.board.claim("A2", "A2")
        self.board.start("M03")
        self.board.submit("M03", evidence("M03"))
        third = self.board.submit("M05", evidence("M05"))
        self.assertEqual(third["state"], "BACKPRESSURE")
        self.assertEqual(self.board.task("M05")["status"], "running")   # 队列满时保持原地
        plan = dispatcher_mod.plan(self.board)
        self.assertTrue(plan["backpressure"])
        self.assertEqual([a for a in plan["assignments"] if a["action"] == "claim"], [])

    def test_06_duplicate_evidence_rejected(self):
        """13 §10-6：同一证据 hash 第二次提交被拒，不进 D0。"""
        self.board.add_task("M01", "M01", "A1", status="ready")
        self.board.claim("A1", "A1")
        self.board.start("M01")
        self.assertEqual(self.board.submit("M01", evidence("M01"))["state"], "submitted")
        self.board.verify_begin()
        self.board.decide("M01", "RETURN_FIX")      # 打回一次，任务回到可运行
        self.board.start("M01")
        dup = self.board.submit("M01", evidence("M01"))
        self.assertEqual(dup["state"], "DUPLICATE")
        self.assertEqual(dup["reason"], "NO_NEW_EVIDENCE")
        self.assertEqual(self.board.db.execute("SELECT COUNT(*) FROM submission_queue").fetchone()[0], 1)


class TestVerification(BoardCase):
    def test_07_third_round_never_verifies(self):
        """13 §10-7：同一任务两次验证失败，第三次不再进入 verifying。"""
        self.board.add_task("M01", "M01", "A1", status="ready")
        self.board.claim("A1", "A1")
        self.board.start("M01")
        self.board.submit("M01", evidence("M01", 1))
        self.board.verify_begin()
        self.assertEqual(self.board.decide("M01", "RETURN_FIX")["state"], "returned")
        self.board.start("M01")
        self.board.submit("M01", evidence("M01", 2))
        self.board.verify_begin()
        self.assertEqual(self.board.decide("M01", "RETURN_FIX")["state"], "blocked")
        # 第三次：任务已 blocked，提交被拒；即便强行进入也没有验证令牌
        self.assertEqual(self.board.task("M01")["status"], "blocked")
        self.assertIsNone(self.board.verify_begin())
        self.assertEqual(self.board.db.execute("SELECT COUNT(*) FROM verifications").fetchone()[0], 2)

    def test_08_one_merge_token(self):
        """13 §10-8：两个 verified 同时请求合并，只有一个拿到 merge token。"""
        self.run_to_verified("M01", "M01", "A1")
        self.run_to_verified("M03", "M03", "A2")
        first = self.board.merge_begin()
        self.assertIsNotNone(first)
        self.assertIsNone(self.board.merge_begin())
        done = self.board.merge_done(first["task_id"], "abc1234")
        self.assertEqual(done["state"], "completed")
        second = self.board.merge_begin()
        self.assertIsNotNone(second)
        self.assertNotEqual(second["task_id"], first["task_id"])

    def test_verified_goes_to_merge_queue(self):
        result = self.run_to_verified("M01", "M01", "A1")
        self.assertEqual(result["state"], "verified")
        self.assertEqual(self.board.task("M01")["status"], "verified")
        self.assertEqual(self.board.db.execute(
            "SELECT state FROM merge_queue WHERE task_id='M01'").fetchone()[0], "queued")


class TestResources(BoardCase):
    def test_09_blender_busy_keeps_ready(self):
        """13 §10-9：Blender 被占用，第二个物理任务只保持 ready。"""
        self.board.add_task("M02", "M02", "A1", status="ready", resource="blender")
        self.board.add_task("M07", "M07", "A4", status="ready", resource="blender")
        self.assertIsNotNone(self.board.claim("A1", "A1"))
        self.assertIsNone(self.board.claim("A4", "A4"))
        self.assertEqual(self.board.task("M07")["status"], "ready")

    def test_resource_released_after_lease_expiry(self):
        clock = [datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc)]
        b = board_mod.Board(os.path.join(self.dir, "clock.db"), clock=lambda: clock[0])
        b.init()
        b.add_task("M02", "M02", "A1", status="ready", resource="blender")
        b.add_task("M07", "M07", "A4", status="ready", resource="blender")
        self.assertIsNotNone(b.claim("A1", "A1", lease_seconds=60))
        clock[0] += timedelta(seconds=120)
        self.assertEqual(b.reap(), ["M02"])
        self.assertIsNotNone(b.claim("A4", "A4"))
        b.close()


class TestRecovery(BoardCase):
    def test_10_lease_expiry_not_stuck(self):
        """13 §10-10：Agent 崩溃 / 租约过期，任务回收，不永久 running。"""
        clock = [datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc)]
        b = board_mod.Board(os.path.join(self.dir, "lease.db"), clock=lambda: clock[0])
        b.init()
        b.add_task("M01", "M01", "A1", status="ready")
        b.claim("A1", "A1", lease_seconds=60)
        b.start("M01", lease_seconds=60)
        clock[0] += timedelta(seconds=90)
        self.assertEqual(b.reap(), ["M01"])
        task = b.task("M01")
        self.assertEqual(task["status"], "ready")
        self.assertEqual(task["claim_count"], 1)
        self.assertIsNone(task["lease_until"])
        b.close()

    def test_claim_limit_fails_task(self):
        clock = [datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc)]
        b = board_mod.Board(os.path.join(self.dir, "limit.db"), clock=lambda: clock[0])
        b.init()
        b.add_task("M01", "M01", "A1", status="ready")
        for _ in range(3):
            b.claim("A1", "A1", lease_seconds=30)
            clock[0] += timedelta(seconds=60)
            b.reap()
        self.assertEqual(b.task("M01")["status"], "failed")
        b.close()

    def test_12_rerun_is_idempotent(self):
        """13 §10-12：重跑 scheduler，状态与事件不重复、不丢。"""
        self.ready_task()
        self.board.init()
        before = len(self.board.events())
        dispatcher_mod.plan(self.board)
        dispatcher_mod.plan(self.board)
        self.board.recompute_deps()
        self.assertEqual(len(self.board.events()), before)
        self.assertEqual(self.board.db.execute("SELECT COUNT(*) FROM resources").fetchone()[0], 3)
        self.board.claim("A1", "A1")
        state = self.board.task("M01")["status"]
        self.board.recompute_deps()
        self.assertEqual(self.board.task("M01")["status"], state)


class TestGuards(BoardCase):
    def test_11_agent_cannot_write_completed(self):
        """13 §10-11：Agent 直接写 completed 被拒并记 W3。"""
        self.ready_task()
        with self.assertRaises(board_mod.BoardError):
            self.board.guard_agent_write("M01", "completed")
        w3 = [e for e in self.board.events() if e["type"] == "W3"]
        self.assertEqual(len(w3), 1)
        self.assertEqual(self.board.task("M01")["status"], "ready")

    def test_dispatch_does_not_start_agents(self):
        self.ready_task()
        plan = dispatcher_mod.plan(self.board)
        self.assertEqual(plan["state"], "DISPATCH")
        self.assertIn("不启动任何 AI", plan["note"])
        self.assertEqual(self.board.task("M01")["status"], "ready")


class TestEvidenceHash(unittest.TestCase):
    """H1–H6（coordination/evidence_hash_v1.md §6）。"""

    def test_H1_two_processes_two_trees(self):
        payload = evidence()
        here = evidence_mod.digest(payload)
        other = tempfile.mkdtemp(prefix="mm00_tree_")
        try:
            code = ("import json,sys;sys.path.insert(0,%r);"
                    "from coordination import evidence as e;"
                    "print(e.digest(json.loads(sys.argv[1])))") % ROOT
            out = subprocess.run([sys.executable, "-c", code, json.dumps(payload)],
                                 cwd=other, capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(out.stdout.strip(), here)
        finally:
            shutil.rmtree(other, ignore_errors=True)

    def test_H2_description_does_not_change_hash(self):
        a = evidence(summary="第一版说明")
        b = evidence(summary="完全换一种说法，加了时间戳 2026-11-16T12:00:00")
        b["message"] = "提交信息"
        b["note"] = "备注"
        self.assertEqual(evidence_mod.digest(a), evidence_mod.digest(b))

    def test_H3_any_sha_change_changes_hash(self):
        base = evidence()
        changed_file = evidence(files=[{"path": "mmdpipe/pmx.py", "sha256": sha("pmx2"), "tracked": True}])
        changed_art = evidence(artifacts=[{"path": "reports/x.json", "sha256": sha("art"), "version": "1"}])
        changed_art2 = evidence(artifacts=[{"path": "reports/x.json", "sha256": sha("art2"), "version": "1"}])
        digests = {evidence_mod.digest(base), evidence_mod.digest(changed_file),
                   evidence_mod.digest(changed_art), evidence_mod.digest(changed_art2)}
        self.assertEqual(len(digests), 4)

    def test_H4_path_normalization(self):
        a = evidence(files=[{"path": "./mmdpipe\\pmx.py", "sha256": sha("pmx"), "tracked": True}])
        b = evidence(files=[{"path": "mmdpipe/pmx.py", "sha256": sha("pmx"), "tracked": True}])
        self.assertEqual(evidence_mod.digest(a), evidence_mod.digest(b))

    def test_H5_test_counts_change_hash(self):
        a = evidence(tests=[{"cmd": "pytest", "exit": 0, "passed": 12, "failed": 0, "skipped": 0}])
        b = evidence(tests=[{"cmd": "pytest", "exit": 0, "passed": 13, "failed": 0, "skipped": 0}])
        self.assertNotEqual(evidence_mod.digest(a), evidence_mod.digest(b))

    def test_H6_nan_rejected(self):
        payload = evidence()
        payload["measurements"] = {"angle_deg": float("nan")}
        with self.assertRaises(evidence_mod.EvidenceError):
            evidence_mod.digest(payload)
        inf = evidence()
        inf["measurements"] = {"depth": float("inf")}
        with self.assertRaises(evidence_mod.EvidenceError):
            evidence_mod.digest(inf)

    def test_spec_and_status_validated(self):
        bad_spec = evidence()
        bad_spec["spec"] = "evidence/2"
        with self.assertRaises(evidence_mod.EvidenceError):
            evidence_mod.digest(bad_spec)
        bad_status = evidence()
        bad_status["status"] = "基本好了"
        with self.assertRaises(evidence_mod.EvidenceError):
            evidence_mod.digest(bad_status)

    def test_negative_zero_normalized(self):
        a = evidence()
        a["measurements"] = {"x": -0.0}
        b = evidence()
        b["measurements"] = {"x": 0.0}
        self.assertEqual(evidence_mod.digest(a), evidence_mod.digest(b))

    def test_known_risks_normalized(self):
        a = evidence(risks=["  F4  无真阳性 ", "", "F4 无真阳性"])
        b = evidence(risks=["F4 无真阳性"])
        self.assertEqual(evidence_mod.digest(a), evidence_mod.digest(b))


if __name__ == "__main__":
    unittest.main(verbosity=2)
