"""协调层（M00）契约测试：13 §10 的 12 条 + evidence_hash 的 H1–H6。

跑法（在任一 worktree 根）：
    python -m unittest discover -s tests        # 与其他模块的测试一起跑
    python -m unittest tests.test_coordination -v
"""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from coordination import board as board_mod
from coordination import dispatcher as dispatcher_mod
from coordination import evidence as evidence_mod
from coordination import gate as gate_mod
from coordination import paths as paths_mod

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
        p1 = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, encoding="utf-8", errors="replace")
        p2 = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, encoding="utf-8", errors="replace")
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


class TestStateMachineHardening(BoardCase):
    def test_returned_task_can_be_claimed_again(self):
        self.board.add_task("M01", "M01", "A1", status="ready")
        self.board.claim("A1", "A1")
        self.board.start("M01")
        self.board.submit("M01", evidence("M01", 1))
        self.board.verify_begin()
        self.assertEqual(self.board.decide("M01", "RETURN_FIX")["state"], "returned")
        again = self.board.claim("A1", "A1")
        self.assertIsNotNone(again)
        self.assertEqual(again["task_id"], "M01")
        self.assertEqual(again["status"], "claimed")

    def test_blocked_task_without_deps_is_not_auto_unlocked(self):
        self.board.add_task("M02", "M02", "A1", status="blocked")
        self.assertEqual(self.board.recompute_deps(), [])
        self.assertEqual(self.board.task("M02")["status"], "blocked")

    def test_blocked_task_with_satisfied_task_dep_unlocks_without_artifact(self):
        self.board.add_task("M01", "M01", "A1", status="completed")
        self.board.add_task("M02", "M02", "A1", status="blocked")
        self.board.add_dep("M02", "M01", "")
        self.assertEqual(self.board.recompute_deps(), ["M02"])
        self.assertEqual(self.board.task("M02")["status"], "ready")

    def test_same_artifact_id_with_different_bytes_is_rejected(self):
        self.board.add_artifact("a1", "M01", "x.json", sha("old"))
        with self.assertRaises(board_mod.BoardError) as ctx:
            self.board.add_artifact("a1", "M01", "x.json", sha("new"))
        self.assertEqual(ctx.exception.reason_code, "SNAPSHOT_INVALID")
        self.assertEqual(self.board.db.execute(
            "SELECT sha256 FROM artifacts WHERE artifact_id='a1'").fetchone()["sha256"], sha("old"))

    def test_readonly_board_does_not_create_database(self):
        path = os.path.join(self.dir, "missing", "board.db")
        with self.assertRaises(Exception):
            board_mod.Board(path, readonly=True)
        self.assertFalse(os.path.exists(path))


class TestSyncBootstrap(BoardCase):
    def _fixtures(self, extra_status=None):
        doc = {"tasks": {
            "M00": {"status": "PASS", "reason": "r", "next": "", "updated": "2026-11-16T00:00+08:00"},
            "M01": {"status": "PARTIAL", "reason": "r", "next": "", "updated": "2026-11-16T00:00+08:00"},
        }}
        if extra_status:
            doc["tasks"].update(extra_status)
        status_path = os.path.join(self.dir, "task_status.json")
        decisions_path = os.path.join(self.dir, "decisions.jsonl")
        with open(status_path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        rows = [
            {"decision_id": "D-20261116-001", "task_id": "M00", "decision": "ACCEPT_MERGE",
             "reason_code": "EVIDENCE_COMPLETE", "evidence": ["abc1234"], "logged_at": "x"},
            {"decision_id": "D-20261116-002", "task_id": "M01", "decision": "ACCEPT_INTERFACE",
             "reason_code": "MISSING_EVIDENCE", "logged_at": "x"},
        ]
        with open(decisions_path, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        graph_path = os.path.join(self.dir, "task_graph.json")
        with open(graph_path, "w", encoding="utf-8") as fh:
            json.dump({"dependencies": {"M01": [{"task": "M00", "artifact": ""}]},
                       "resources": {"M00": "none", "M01": "blender"}}, fh)
        return status_path, decisions_path, graph_path

    def test_bootstrap_once_and_repeated_bootstrap_rejected(self):
        from coordination import sync_board
        status_path, decisions_path, graph_path = self._fixtures()
        got = sync_board.sync(status_path, decisions_path, self.board.path, mode="bootstrap",
                              graph_path=graph_path)
        self.assertEqual(got["state"], "PHASE_B_OK")
        self.assertEqual(self.board.task("M01")["resource"], "blender")
        self.assertEqual(sync_board.bootstrap_done(self.board), True)
        with self.assertRaises(board_mod.BoardError):
            sync_board.sync(status_path, decisions_path, self.board.path, mode="bootstrap",
                            graph_path=graph_path)
        check = sync_board.sync(status_path, decisions_path, self.board.path, mode="check",
                                graph_path=graph_path)
        self.assertEqual(check["state"], "PHASE_B_CHECK_OK")


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
                                 cwd=other, capture_output=True, text=True, encoding="utf-8", timeout=60)
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

    def test_hash_basis_absent_keeps_old_digest(self):
        """不写 `hash_basis` 时，规范化结果与加这个字段之前**逐字节相同**。

        参考值 `0863ecaa…` 是在改 `evidence.py` 之前算出来的：新增字段必须是
        **可选**的，否则今天所有已合并的证据哈希都会失效。
        """
        payload = {
            "spec": "evidence/1", "task_id": "M00", "attempt": 1, "status": "PASS",
            "files": [{"path": "a.py", "sha256": "0" * 64, "tracked": True}],
            "tests": [{"cmd": "x", "exit": 0, "passed": 1, "failed": 0, "skipped": 0}],
            "artifacts": [], "known_risks": [], "interface": "i",
        }
        self.assertNotIn("hash_basis", evidence_mod.normalize(payload))
        self.assertEqual(
            evidence_mod.digest(payload),
            "evidence/1:0863ecaa9f799f78b20ac87af69291dd5a971934c6662d62bb48d15566ac4186")

    def test_hash_basis_present_enters_hash(self):
        a = evidence()
        b = evidence()
        b["hash_basis"] = "lf_normalized_v1"
        self.assertIn("hash_basis", evidence_mod.normalize(b))
        self.assertNotEqual(evidence_mod.digest(a), evidence_mod.digest(b))

    def test_hash_basis_enum_enforced(self):
        """基数是**枚举**（D0 13:34）：不认识的写法必须抛，不许自由文本。"""
        for bad in ("raw_bytes_v1", "foo", "LF_NORMALIZED_V1", "lf_normalized_v1 "):
            payload = evidence()
            payload["hash_basis"] = bad
            if bad == "lf_normalized_v1 ":          # 只有空白差异应被折叠成合法值
                self.assertIn("hash_basis", evidence_mod.normalize(payload))
                continue
            with self.assertRaises(evidence_mod.EvidenceError):
                evidence_mod.digest(payload)

    def test_hash_basis_whitespace_collapsed(self):
        a = evidence()
        a["hash_basis"] = "  lf_normalized_v1  "
        b = evidence()
        b["hash_basis"] = "lf_normalized_v1"
        self.assertEqual(evidence_mod.digest(a), evidence_mod.digest(b))

    def test_hash_basis_type_checked(self):
        bad = evidence()
        bad["hash_basis"] = 1
        with self.assertRaises(evidence_mod.EvidenceError):
            evidence_mod.digest(bad)
        blank = evidence()
        blank["hash_basis"] = "   "
        self.assertNotIn("hash_basis", evidence_mod.normalize(blank))

    def test_hash_basis_reason_code(self):
        bad = evidence()
        bad["hash_basis"] = "raw_bytes_v1"
        with self.assertRaises(evidence_mod.EvidenceError) as ctx:
            evidence_mod.digest(bad)
        self.assertEqual(ctx.exception.reason_code, "WRONG_HASH_BASIS")

    # ---------------------------------------------------------- measurements（D-072）
    def test_measurements_absent_keeps_old_digest(self):
        """缺席时与加这个字段之前逐字节相同——旧证据哈希一个都不许变。"""
        payload = {
            "spec": "evidence/1", "task_id": "M00", "attempt": 1, "status": "PASS",
            "files": [{"path": "a.py", "sha256": "0" * 64, "tracked": True}],
            "tests": [{"cmd": "x", "exit": 0, "passed": 1, "failed": 0, "skipped": 0}],
            "artifacts": [], "known_risks": [], "interface": "i",
        }
        self.assertNotIn("measurements", evidence_mod.normalize(payload))
        self.assertEqual(
            evidence_mod.digest(payload),
            "evidence/1:0863ecaa9f799f78b20ac87af69291dd5a971934c6662d62bb48d15566ac4186")

    def test_measurements_enter_hash(self):
        a = evidence()
        b = evidence()
        b["measurements"] = {"eval_policy": {"warmup_frames": 2, "visited": 5}}
        self.assertEqual(evidence_mod.normalize(b)["measurements"], b["measurements"])
        self.assertNotEqual(evidence_mod.digest(a), evidence_mod.digest(b))
        # 改一个数就必须换一个 hash
        c = evidence()
        c["measurements"] = {"eval_policy": {"warmup_frames": 2, "visited": 6}}
        self.assertNotEqual(evidence_mod.digest(b), evidence_mod.digest(c))

    def test_measurements_nested_key_order_irrelevant(self):
        """嵌套 dict 的插入顺序不该影响 hash（canonical 是递归排序的）。"""
        a = evidence()
        a["measurements"] = {"outer": {"b": 1, "a": {"y": 2, "x": 3}}}
        b = evidence()
        b["measurements"] = {"outer": {"a": {"x": 3, "y": 2}, "b": 1}}
        self.assertEqual(evidence_mod.digest(a), evidence_mod.digest(b))

    def test_measurements_nan_rejected(self):
        bad = evidence()
        bad["measurements"] = {"mesh_v2_selftest": {"depth_median_m": float("nan")}}
        with self.assertRaises(evidence_mod.EvidenceError):
            evidence_mod.digest(bad)
        inf = evidence()
        inf["measurements"] = {"per_frame": [{"depth_m": float("-inf")}]}
        with self.assertRaises(evidence_mod.EvidenceError):
            evidence_mod.digest(inf)

    def test_measurements_non_object_rejected(self):
        for bad_value in ([1, 2, 3], "3.14", 42, True):
            bad = evidence()
            bad["measurements"] = bad_value
            with self.assertRaises(evidence_mod.EvidenceError) as ctx:
                evidence_mod.digest(bad)
            self.assertEqual(ctx.exception.reason_code, "BAD_MEASUREMENTS")

    def test_measurements_oversize_rejected_by_bytes(self):
        """上限按**序列化后的字节**判，不是按键数/字符数（D-072，2号 提的第 3 条）。"""
        big = evidence()
        # 单键塞满中文：字符数 ≈ 字节数的 1/3，按字符数判会放过它
        big["measurements"] = {"blob": "汉" * (evidence_mod.MEASUREMENTS_LIMIT // 2)}
        with self.assertRaises(evidence_mod.EvidenceError) as ctx:
            evidence_mod.digest(big)
        self.assertEqual(ctx.exception.reason_code, "BAD_MEASUREMENTS")
        # 刚好在上限内的要能过
        ok = evidence()
        payload = {"blob": "x" * 4096}
        self.assertLessEqual(len(evidence_mod.canonical_bytes(payload)),
                             evidence_mod.MEASUREMENTS_LIMIT)
        ok["measurements"] = payload
        self.assertIn("measurements", evidence_mod.normalize(ok))

    def test_measurements_negative_zero_normalized_inside(self):
        a = evidence()
        a["measurements"] = {"delta": -0.0}
        b = evidence()
        b["measurements"] = {"delta": 0.0}
        self.assertEqual(evidence_mod.digest(a), evidence_mod.digest(b))

    # ---------------------------------------------------------- commit / scope（D0 13:49 (b)）
    def test_commit_scope_absent_keeps_old_digest(self):
        """两个新键也必须可选：不写时与加它们之前逐字节相同（旧证据一个都不失效）。"""
        payload = {
            "spec": "evidence/1", "task_id": "M00", "attempt": 1, "status": "PASS",
            "files": [{"path": "a.py", "sha256": "0" * 64, "tracked": True}],
            "tests": [{"cmd": "x", "exit": 0, "passed": 1, "failed": 0, "skipped": 0}],
            "artifacts": [], "known_risks": [], "interface": "i",
        }
        normal = evidence_mod.normalize(payload)
        self.assertNotIn("commit", normal)
        self.assertNotIn("scope", normal)
        self.assertEqual(
            evidence_mod.digest(payload),
            "evidence/1:0863ecaa9f799f78b20ac87af69291dd5a971934c6662d62bb48d15566ac4186")

    def test_commit_enters_hash(self):
        a = evidence()
        b = evidence()
        b["commit"] = "f3fd0e1"
        self.assertEqual(evidence_mod.normalize(b)["commit"], "f3fd0e1")
        self.assertNotEqual(evidence_mod.digest(a), evidence_mod.digest(b))

    def test_commit_shape_enforced(self):
        """形状是硬约束：7–40 位小写 hex。每一条都应当被拒。"""
        for bad in ("", "f3fd0e",                      # 空串 / 太短
                    "F3FD0E1", "f3fd0e1z",              # 大写、非 hex
                    " f3fd0e1", "f3fd0e1 ",             # 空白不 strip，直接拒
                    "refs/heads/main", "0" * 41):       # 不是 hash / 太长
            payload = evidence()
            payload["commit"] = bad
            with self.assertRaises(evidence_mod.EvidenceError) as ctx:
                evidence_mod.digest(payload)
            self.assertEqual(ctx.exception.reason_code, "WRONG_COMMIT", repr(bad))
        payload = evidence()
        payload["commit"] = 1234567
        with self.assertRaises(evidence_mod.EvidenceError) as ctx:
            evidence_mod.digest(payload)
        self.assertEqual(ctx.exception.reason_code, "WRONG_COMMIT")

    def test_commit_bounds_accepted(self):
        """7 位与 40 位都在界内（边界要正面验，不能只验拒绝）。"""
        for ok in ("0" * 7, "a" * 40, "f3fd0e1"):
            payload = evidence()
            payload["commit"] = ok
            self.assertEqual(evidence_mod.normalize(payload)["commit"], ok)

    def test_commit_none_is_absent(self):
        payload = evidence()
        payload["commit"] = None
        self.assertNotIn("commit", evidence_mod.normalize(payload))

    def test_scope_whitespace_collapsed(self):
        a = evidence()
        a["scope"] = "  coordination/evidence.py\n\t tests/test_coordination.py  "
        b = evidence()
        b["scope"] = "coordination/evidence.py tests/test_coordination.py"
        self.assertEqual(evidence_mod.normalize(a)["scope"], b["scope"])
        self.assertEqual(evidence_mod.digest(a), evidence_mod.digest(b))

    def test_scope_blank_is_absent_not_empty_string(self):
        """`scope` 折成空串等同缺席——**不能**把 `scope: ""` 放进 canonical。

        这是 2号 最担心的不对称：若写成"有键就放"，同一份内容会有两种哈希。
        """
        for blank in ("", "   ", "\n\t "):
            payload = evidence()
            payload["scope"] = blank
            self.assertNotIn("scope", evidence_mod.normalize(payload))
        with_blank = evidence()
        with_blank["scope"] = "   "
        self.assertEqual(evidence_mod.digest(with_blank), evidence_mod.digest(evidence()))

    def test_scope_non_string_rejected(self):
        payload = evidence()
        payload["scope"] = ["a.py"]
        with self.assertRaises(evidence_mod.EvidenceError) as ctx:
            evidence_mod.digest(payload)
        self.assertEqual(ctx.exception.reason_code, "WRONG_SCOPE")

    def test_commit_and_scope_both_present(self):
        """同一条记录里两个键同时出现，各进各的位（别让一个盖掉另一个）。"""
        payload = evidence()
        payload["commit"] = "f3fd0e1"
        payload["scope"] = "coordination evidence"
        normal = evidence_mod.normalize(payload)
        self.assertEqual(normal["commit"], "f3fd0e1")
        self.assertEqual(normal["scope"], "coordination evidence")

    # ---------------------------------------------------------- D-094：未知字段必须抛
    def test_tests_unknown_field_rejected(self):
        """`tests[]` 行是**重建**的，schema 外字段原本会被悄悄扔掉（D-094）。

        静默丢 = 「声明了的字段」与「进了哈希的字段」不是同一个集合，而写记录的人只能靠
        最后一步 `check` 的 exit 5 猜。所以它必须是错误，并且要点名字段。
        """
        payload = evidence()
        payload["tests"][0]["note"] = "跑了两遍"
        with self.assertRaises(evidence_mod.EvidenceError) as ctx:
            evidence_mod.digest(payload)
        self.assertEqual(ctx.exception.reason_code, "WRONG_TESTS_FIELD")
        self.assertIn("note", str(ctx.exception))
        self.assertIn("cmd", str(ctx.exception))       # 允许的字段也要列出来

    def test_tests_five_fields_accepted(self):
        """正控：五个字段齐全（含缺省）都合规，缺省的按 0 补。"""
        payload = evidence()
        payload["tests"] = [{"cmd": "只给 cmd"}]
        normal = evidence_mod.normalize(payload)
        self.assertEqual(normal["tests"], [{"cmd": "只给 cmd", "exit": 0, "passed": 0,
                                            "failed": 0, "skipped": 0}])

    def test_files_artifact_extra_fields_still_kept(self):
        """`files[]`/`artifacts[]` 是整行保留的，多写字段照旧进哈希（D-094 只管 tests[]）。"""
        payload = evidence()
        payload["files"][0]["note"] = "整行保留"
        payload["artifacts"] = [{"path": "reports/x.json", "sha256": sha("x"),
                                 "version": "1", "note": "也保留"}]
        normal = evidence_mod.normalize(payload)
        self.assertEqual(normal["files"][0]["note"], "整行保留")
        self.assertEqual(normal["artifacts"][0]["note"], "也保留")
        plain = evidence()
        plain["artifacts"] = [{"path": "reports/x.json", "sha256": sha("x"), "version": "1"}]
        self.assertNotEqual(evidence_mod.digest(payload), evidence_mod.digest(plain))

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


class TestCoverageGate(unittest.TestCase):
    """D-20261116-022：files[] 必须覆盖 git diff base..HEAD，缺即 MISSING_EVIDENCE。"""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="mm00_repo_")
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "test")
        self.git("config", "commit.gpgsign", "false")
        (pathlib.Path(self.repo) / "a.py").write_text("a = 1\n", encoding="utf-8")
        self.git("add", "a.py")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD").strip()
        (pathlib.Path(self.repo) / "b.py").write_text("b = 2\n", encoding="utf-8")
        self.git("add", "b.py")
        self.git("commit", "-qm", "second")

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def git(self, *args):
        out = subprocess.run(["git", "-C", self.repo, *args], capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def test_changed_files_is_from_git(self):
        self.assertEqual(gate_mod.changed_files(self.base, repo=self.repo), ["b.py"])

    def test_missing_file_rejected(self):
        files = [{"path": "a.py", "sha256": sha("a"), "tracked": True}]
        with self.assertRaises(gate_mod.CoverageError) as ctx:
            gate_mod.check_coverage(files, self.base, repo=self.repo)
        self.assertEqual(ctx.exception.missing, ["b.py"])
        self.assertEqual(ctx.exception.reason_code, "MISSING_EVIDENCE")

    def test_full_coverage_passes(self):
        files = [{"path": "a.py", "sha256": sha("a"), "tracked": True},
                 {"path": "b.py", "sha256": sha("b"), "tracked": True}]
        result = gate_mod.check_coverage(files, self.base, repo=self.repo)
        self.assertEqual(result["changed"], ["b.py"])

    def test_windows_separator_still_covers(self):
        files = [{"path": ".\\b.py", "sha256": sha("b"), "tracked": True}]
        self.assertEqual(gate_mod.check_coverage(files, self.base, repo=self.repo)["changed"], ["b.py"])

    def test_bad_base_is_evidence_error_not_pass(self):
        with self.assertRaises(evidence_mod.EvidenceError):
            gate_mod.check_coverage([], "deadbeef", repo=self.repo)

    def test_deleted_file_is_reported_not_required(self):
        """删除的文件没有内容可算 sha256：不进 files[] 要求，但要单独列出并留痕。"""
        (pathlib.Path(self.repo) / "a.py").unlink()
        self.git("add", "-A")
        self.git("commit", "-qm", "delete a")
        files = [{"path": "b.py", "sha256": sha("b"), "tracked": True}]
        result = gate_mod.check_coverage(files, self.base, repo=self.repo)
        self.assertIn("a.py", result["deleted"])
        self.assertNotIn("a.py", result["changed"])

    def test_three_dot_ignores_base_branch_commits(self):
        """三点式：base 分支上别人合进来的提交不算我的改动（M00 attempt 2 的教训）。

        base = 已经前进的"main"（多了一个别人提交的 other.py），head = 我的分支（停在共同祖先）。
        两点式会把 other.py 算成"我漏填的文件"，三点式不会。
        """
        branch = self.git("rev-parse", "--abbrev-ref", "HEAD").strip()
        self.git("branch", "side")                     # 我的分支：与 base 的共同祖先
        (pathlib.Path(self.repo) / "other.py").write_text("other = 1\n", encoding="utf-8")
        self.git("add", "other.py")
        self.git("commit", "-qm", "someone else")
        self.assertEqual(gate_mod.changed_files(branch, head="side", repo=self.repo), [])

    def test_submit_enforces_gate(self):
        board = board_mod.Board(os.path.join(tempfile.mkdtemp(prefix="mm00_gate_"), "b.db"))
        board.init()
        try:
            board.add_task("M01", "M01", "A1", status="ready", base_commit=self.base)
            board.claim("A1", "A1")
            board.start("M01")
            partial = evidence(files=[{"path": "a.py", "sha256": sha("a"), "tracked": True}])
            with self.assertRaises(evidence_mod.EvidenceError):
                board.submit("M01", partial, repo=self.repo)
            self.assertEqual(board.db.execute(
                "SELECT COUNT(*) FROM submission_queue").fetchone()[0], 0)
            full = evidence(files=[{"path": "a.py", "sha256": sha("a"), "tracked": True},
                                   {"path": "b.py", "sha256": sha("b"), "tracked": True}])
            self.assertEqual(board.submit("M01", full, repo=self.repo)["state"], "submitted")
        finally:
            board.close()


class TestSharedBoardPath(unittest.TestCase):
    """board.db 是四棵工作树共享的单实例（D-20261116-012），不是每棵树各存一份。"""

    def test_worktrees_agree_on_one_path(self):
        main_root = paths_mod.main_worktree_root(ROOT)
        if not main_root:
            self.skipTest("不在 git 工作树里")
        here = paths_mod.board_path(start=ROOT)
        there = paths_mod.board_path(start=main_root)
        self.assertEqual(here, there)
        self.assertTrue(here.replace("\\", "/").endswith("/out/subai/coordination/board.db"))

    def test_two_processes_same_cwd_agree(self):
        code = ("import sys;sys.path.insert(0,%r);from coordination import paths;"
                "print(paths.board_path())") % ROOT
        a = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8")
        b = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8")
        # 先钉住"两次都真的出了东西"：两个 None 比起来也是 None == None，那是假绿
        self.assertEqual(a.returncode, 0, a.stderr)
        self.assertEqual(b.returncode, 0, b.stderr)
        self.assertTrue(a.stdout.strip(), "第一次运行没有输出，比较无意义")
        self.assertTrue(b.stdout.strip(), "第二次运行没有输出，比较无意义")
        self.assertEqual(a.stdout.strip(), b.stdout.strip())


class TestEvidenceCheck(unittest.TestCase):
    """`python -m coordination.evidence check <file>`（D-080 的提交前自查入口）。

    退出码（D0 13:53 定死）：0 合规 / 3 SCHEMA_INVALID / **5 NOT_CANONICAL** / 4 UNREADABLE。
    **3 与 5 必须分开**，因为只有退出码是调用方能机械判的；`reason_code` 要在输出里另给一列。
    **D-080 点名要的拒绝例**：`interface` 是对象 → 必须 exit 3。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="m00_evcheck_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, payload, canonical=True, name="ev.json"):
        path = os.path.join(self.tmp, name)
        if canonical:
            blob = evidence_mod.canonical_bytes(evidence_mod.normalize(payload))
        else:
            blob = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        with open(path, "wb") as fh:
            fh.write(blob)
        return path

    def run_cli(self, path):
        return subprocess.run([sys.executable, "-m", "coordination.evidence", "check", path],
                              cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                              timeout=60)

    def test_canonical_file_is_ok(self):
        path = self.write(evidence())
        code, reason, message = evidence_mod.check_file(path)
        self.assertEqual(code, evidence_mod.EXIT_OK)
        self.assertEqual(reason, evidence_mod.REASON_OK)
        self.assertEqual(message, evidence_mod.digest(evidence()))
        out = self.run_cli(path)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("OK evidence/1:", out.stdout)

    def test_interface_object_is_schema_violation(self):
        """D-080 点名要的这个拒绝例：`interface` 必须是版本串。"""
        payload = evidence()
        payload["interface"] = {"version": "cache_state/1", "struct": {"a": 1}}
        path = os.path.join(self.tmp, "obj.json")
        with open(path, "wb") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        code, reason, message = evidence_mod.check_file(path)
        self.assertEqual(code, evidence_mod.EXIT_SCHEMA)
        self.assertEqual(reason, evidence_mod.REASON_SCHEMA)
        self.assertIn("interface", message)
        out = self.run_cli(path)
        self.assertEqual(out.returncode, 3, out.stdout + out.stderr)
        self.assertIn("SCHEMA_INVALID", out.stdout)
        self.assertNotIn("NOT_CANONICAL", out.stdout)

    def test_non_canonical_bytes_are_rejected_with_their_own_code(self):
        """能规范化、但磁盘上那份不是规范字节 ⇒ **5 / NOT_CANONICAL**，不是 3。"""
        path = self.write(evidence(), canonical=False)
        code, reason, message = evidence_mod.check_file(path)
        self.assertEqual(code, evidence_mod.EXIT_NOT_CANONICAL)
        self.assertEqual(reason, evidence_mod.REASON_NOT_CANONICAL)
        self.assertIn("canonical", message)
        # 提示里要带上"规范 digest 应为 X"——否则看的人不知道对的值是什么
        self.assertIn(evidence_mod.digest(evidence()), message)
        out = self.run_cli(path)
        self.assertEqual(out.returncode, 5, out.stdout + out.stderr)
        self.assertIn("NOT_CANONICAL", out.stdout)

    def test_schema_and_byte_violations_are_different_shapes(self):
        """同类失败必须不同形：3 与 5 分家之后，脚本能机械判（这是分开的唯一理由）。"""
        schema_path = os.path.join(self.tmp, "schema.json")
        payload = evidence()
        payload["status"] = "基本好了"          # 类型/约束不符 ⇒ 3
        with open(schema_path, "wb") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        byte_path = self.write(evidence(), canonical=False)   # schema 对、字节不规范 ⇒ 5
        schema_code = evidence_mod.check_file(schema_path)[0]
        byte_code = evidence_mod.check_file(byte_path)[0]
        self.assertEqual(schema_code, evidence_mod.EXIT_SCHEMA)
        self.assertEqual(byte_code, evidence_mod.EXIT_NOT_CANONICAL)
        self.assertNotEqual(schema_code, byte_code)

    def test_missing_file_is_unreadable(self):
        code, reason, _ = evidence_mod.check_file(os.path.join(self.tmp, "nope.json"))
        self.assertEqual(code, evidence_mod.EXIT_UNREADABLE)
        self.assertEqual(reason, evidence_mod.REASON_UNREADABLE)
        out = self.run_cli(os.path.join(self.tmp, "nope.json"))
        self.assertEqual(out.returncode, 4)
        self.assertIn("UNREADABLE", out.stdout)

    def test_broken_json_is_unreadable(self):
        path = os.path.join(self.tmp, "broken.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        self.assertEqual(evidence_mod.check_file(path)[0], evidence_mod.EXIT_UNREADABLE)

    def test_measurements_roundtrip_through_check(self):
        payload = evidence()
        payload["measurements"] = {"eval_policy": {"visited": 5}, "selftest": {"rate": 0.9933}}
        path = self.write(payload)
        code, reason, message = evidence_mod.check_file(path)
        self.assertEqual(code, evidence_mod.EXIT_OK)
        self.assertEqual(reason, evidence_mod.REASON_OK)
        self.assertEqual(message, evidence_mod.digest(payload))

    def test_commit_and_scope_roundtrip_through_check(self):
        payload = evidence()
        payload["commit"] = "f3fd0e1"
        payload["scope"] = "coordination/evidence.py  tests/test_coordination.py"
        path = self.write(payload)
        self.assertEqual(evidence_mod.check_file(path)[0], evidence_mod.EXIT_OK)
        # check 读回后规范化必须与写它时同一份口径（commit 原样、scope 折叠）
        normal = evidence_mod.normalize(payload)
        self.assertEqual(normal["commit"], "f3fd0e1")
        self.assertEqual(normal["scope"], "coordination/evidence.py tests/test_coordination.py")

    def test_not_canonical_names_the_cause_not_just_the_state(self):
        """exit 5 不能只说"不是规范字节"——三类原因的处理办法完全不同，必须点名。"""
        # 类 1：自建格式化（缩进）
        pretty = os.path.join(self.tmp, "pretty.json")
        with open(pretty, "wb") as fh:
            fh.write(json.dumps(evidence(), ensure_ascii=False, indent=2).encode("utf-8"))
        code, reason, message = evidence_mod.check_file(pretty)
        self.assertEqual((code, reason), (evidence_mod.EXIT_NOT_CANONICAL,
                                          evidence_mod.REASON_NOT_CANONICAL))
        self.assertIn("序列化本身", message)

        # 类 2a：顶层多写了不进哈希的键
        extra_top = evidence()
        extra_top["summary"] = "说明不参与哈希"
        path = os.path.join(self.tmp, "extra_top.json")
        with open(path, "wb") as fh:
            fh.write(json.dumps(extra_top, ensure_ascii=False,
                                sort_keys=True, separators=(",", ":")).encode("utf-8"))
        code, _, message = evidence_mod.check_file(path)
        self.assertEqual(code, evidence_mod.EXIT_NOT_CANONICAL)
        self.assertIn("summary", message)

        # 类 2b：tests[] 行里多了字段 —— **D-094 之后这是 schema 违规（3），不再是 5**。
        # 静默丢换成抛错，正是为了让写的人当场知道，而不是等最后一步 check 打 exit 5 去猜。
        extra_tests = evidence()
        extra_tests["tests"][0]["note"] = "跑了两遍"
        path = os.path.join(self.tmp, "extra_tests.json")
        with open(path, "wb") as fh:
            fh.write(json.dumps(extra_tests, ensure_ascii=False,
                                sort_keys=True, separators=(",", ":")).encode("utf-8"))
        code, reason, message = evidence_mod.check_file(path)
        self.assertEqual((code, reason), (evidence_mod.EXIT_SCHEMA,
                                          evidence_mod.REASON_SCHEMA))
        self.assertIn("WRONG_TESTS_FIELD", message)
        self.assertIn("note", message)

    def test_legacy_tests_field_file_is_schema_violation_too(self):
        """D-094 之前落盘的老记录也一样判 3：schema 变严对盘上已有的文件同样生效，
        差别只在"现在能一眼看出是哪个字段"（消息里点名 `note`）。"""
        legacy = {"spec": "evidence/1", "task_id": "M01", "attempt": 1, "status": "PASS",
                  "files": [], "artifacts": [], "known_risks": [], "interface": None,
                  "tests": [{"cmd": "x", "exit": 0, "passed": 1, "failed": 0,
                             "skipped": 0, "note": "老记录"}]}
        path = os.path.join(self.tmp, "legacy.json")
        with open(path, "wb") as fh:
            fh.write(json.dumps(legacy, ensure_ascii=False,
                                sort_keys=True, separators=(",", ":")).encode("utf-8"))
        code, reason, message = evidence_mod.check_file(path)
        self.assertEqual(code, evidence_mod.EXIT_SCHEMA)
        self.assertIn("WRONG_TESTS_FIELD", message)
        self.assertIn("note", message)


    def test_canonical_file_has_no_diagnosis_noise(self):
        """正控：规范字节的文件不能说"序列化本身不是规范形态"。"""
        code, reason, message = evidence_mod.check_file(self.write(evidence()))
        self.assertEqual((code, reason), (evidence_mod.EXIT_OK, evidence_mod.REASON_OK))
        self.assertNotIn("序列化", message)

    def test_help_lists_four_exit_codes(self):
        """`--help` 必须写明四个码——调用方读的就是它。"""
        out = subprocess.run([sys.executable, "-m", "coordination.evidence", "--help"],
                             cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                             timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        for token in ("0", "3", "5", "4", "SCHEMA_INVALID", "NOT_CANONICAL", "UNREADABLE"):
            self.assertIn(token, out.stdout)
        # 能力边界也要写在 help 里，否则下一个人把 exit 0 读成"全都对"
        self.assertIn("不重算", out.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
