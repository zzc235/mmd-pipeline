# -*- coding: utf-8 -*-
"""协调层 v2（14 号令 A–I）的检查点测试。

跑法（任一 worktree 根）：

    python -m unittest discover -s tests
    python -m unittest tests.test_coordination_architecture -v

覆盖十组「机器可判」的东西：闸门包（gates）、board 提交闸门、开工前置（preflight）、
Human gate、真值档（truth_tier）、证据快照、决策词表、派工 P0、待批项不许蒸发。
每条断言都对着一条**已知会假绿**的构造，不是对着"函数能跑"。
"""
import io
import json
import os
import shutil
import tempfile
import unittest

from coordination import board as board_mod
from coordination import dispatcher as dispatcher_mod
from coordination import evidence as evidence_mod
from coordination import evidence_store as store_mod
from coordination import gates as gates_mod
from coordination import human_gate as human_gate_mod
from coordination import lock as lock_mod
from coordination import preflight as preflight_mod
from coordination import status as status_mod
from coordination import taxonomy as taxonomy_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZERO = "0" * 64
# 「树外路径」必须按当前 worktree 现算，不能硬编码某一棵树：
# 写着 `E:\code\mmdpipe-ai\A1\...` 时，这组测试在 A1 worktree 里跑就恒红（那条路径在树**内**）。
# 取 ROOT 的父目录下的一支，任何 worktree（main / A1..A4）都稳定落在树外。
OUTSIDE = os.path.join(os.path.dirname(ROOT), "_outside_worktree")


def outside_path(*parts):
    """构造一条**确实在树外**的路径，并用判据自己的归一化函数当场断言。

    「树外」不许继续是一个需要相信的名字：换一个树根（`E:\dsh pr` / 别处）时，
    dirname 拼法未必还成立，那时应当红在这条断言上（说清「样本构造错了」），
    而不是红在判据上（看起来像「判据坏了」）。
    """
    path = os.path.join(OUTSIDE, *parts)
    assert not preflight_mod._norm(path).startswith(preflight_mod._norm(ROOT)), (
        "样本路径落在本 worktree 内，用例前提不成立：%s" % path)
    return path


def ev(task_id="M00", **extra):
    rec = {
        "spec": "evidence/1", "task_id": task_id, "attempt": 1, "status": "PASS",
        "files": [{"path": "mmdpipe/x.py", "sha256": ZERO}],
        "tests": [], "artifacts": [], "known_risks": [], "interface": "mmdpipe.mask@1",
    }
    rec.update(extra)
    return rec


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="coord-arch-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def path(self, *parts):
        return os.path.join(self.tmp, *parts)


# --------------------------------------------------------------- 阶段 F：闸门包
class GateBundleTest(TempDirTest):
    """`gates.check_bundle` 的每条判据都要有一个红样本 + 一个绿样本。"""

    def bundle(self, **extra):
        b = {
            "evidence_check_exit": 0, "coverage_check": "PASS",
            "acceptance_result": "PASS", "truth_tier": "T3",
            "snapshot_paths": [{"path": "out/subai/x.txt", "snapshot": "out/subai/_evidence_store/a/x.txt"}],
            "module_provenance": {"stage_file": os.path.join(ROOT, "mmdpipe", "stage.py")},
            "resource_lease_valid": True, "fresh_solve_confirmed": True,
        }
        b.update(extra)
        return b

    def code(self, bundle, payload=None):
        return gates_mod.check_bundle(bundle, payload or ev(), worktree=ROOT)["reason_code"]

    def test_truth_tier_missing_is_scope_mismatch(self):
        b = self.bundle()
        del b["truth_tier"]
        self.assertEqual(self.code(b), "EVIDENCE_SCOPE_MISMATCH")

    def test_reports_artifact_without_snapshot_is_invalid(self):
        b = self.bundle(snapshot_paths=[{"path": "reports/subai/x.txt"}])
        self.assertEqual(self.code(b), "SNAPSHOT_INVALID")

    def test_module_outside_worktree_is_provenance_invalid(self):
        b = self.bundle(module_provenance={"stage_file": outside_path("mmdpipe", "stage.py")})
        self.assertEqual(self.code(b), "PROVENANCE_INVALID")

    def test_physics_claim_needs_fresh_solve(self):
        # 关键回归：`known_risks` 是**列表**。只扫顶层 str 的实现会把这条判据
        # 静默变成"永远通过"——第一版就是这么假绿的。
        payload = ev(known_risks=["穿透 34 对未消解"])
        self.assertEqual(self.code(self.bundle(fresh_solve_confirmed=False), payload),
                         "FRESH_SOLVE_REQUIRED")
        self.assertEqual(self.code(self.bundle(), payload), "EVIDENCE_COMPLETE")

    def test_path_that_merely_contains_depth_is_not_a_claim(self):
        payload = ev(files=[{"path": "mmdpipe/depth_probe.py", "sha256": ZERO}])
        self.assertEqual(self.code(self.bundle(fresh_solve_confirmed=False), payload),
                         "EVIDENCE_COMPLETE")

    def test_evidence_check_exit_nonzero_is_gate_failed(self):
        self.assertEqual(self.code(self.bundle(evidence_check_exit=5)), "GATE_FAILED")

    def test_coverage_not_pass_is_missing_evidence(self):
        self.assertEqual(self.code(self.bundle(coverage_check="PARTIAL")), "MISSING_EVIDENCE")

    def test_acceptance_fail_is_gate_failed(self):
        self.assertEqual(self.code(self.bundle(acceptance_result="FAIL")), "GATE_FAILED")

    def test_lease_invalid_is_lease_expired(self):
        self.assertEqual(self.code(self.bundle(resource_lease_valid=False)), "LEASE_EXPIRED")

    def test_clean_bundle_passes(self):
        self.assertEqual(self.code(self.bundle()), "EVIDENCE_COMPLETE")

    def test_wants_gate(self):
        self.assertTrue(gates_mod.wants_gate({"truth_tier": "T3"}))
        self.assertTrue(gates_mod.wants_gate({"gate": {"evidence_check_exit": 0}}))
        self.assertFalse(gates_mod.wants_gate(ev()))


class BoardSubmitGateTest(TempDirTest):
    """闸门必须挂在唯一的提交入口上，否则"校验"只是建议。"""

    def setUp(self):
        super().setUp()
        self.board = board_mod.Board(self.path("board.db"))
        self.board.init()
        self.board.add_task("M00", "M00", "P0", status="running")
        self.board.add_task("M01", "M01", "P0", status="running")
        self.addCleanup(self.board.close)

    def test_gated_submit_rejected_before_queue(self):
        bundle = {"evidence_check_exit": 0, "coverage_check": "PASS",
                  "acceptance_result": "PASS"}          # 缺 truth_tier
        with self.assertRaises(board_mod.BoardError) as ctx:
            self.board.submit("M00", ev(gate=bundle))
        self.assertEqual(ctx.exception.reason_code, "EVIDENCE_SCOPE_MISMATCH")

    def test_legacy_submit_still_accepted_and_recorded(self):
        # 老证据（不带 truth_tier/gate）不静默放行：要走 legacy 通道并**记事件**
        result = self.board.submit("M01", ev("M01"))
        self.assertEqual(result.get("state"), "submitted")
        rows = self.board.db.execute(
            "SELECT COUNT(*) c FROM events WHERE type='gate.legacy_skipped'").fetchone()
        self.assertGreaterEqual(rows["c"], 1)


# --------------------------------------------------------------- 阶段 G：开工前置
class PreflightTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.lease = self.path("blender.lock")
        self.existing = self.path("out", "frame.txt")
        os.makedirs(os.path.dirname(self.existing))
        with io.open(self.existing, "w", encoding="utf-8") as fh:
            fh.write("已有产物\n")
        self.request = {
            "task_id": "M02",
            "provenance": {"stage_file": os.path.join(ROOT, "mmdpipe", "stage.py")},
            "needs": 8298, "cap": 20000, "skipped": 0,
            "lease_dir": self.lease,
            "outputs": [self.path("out2", "fresh.txt")],
        }

    def release_lease(self):
        if os.path.isdir(self.lease):
            lock_mod.release("模块负责1|A1", lock_dir=self.lease)

    def check(self, **extra):
        req = dict(self.request)
        req.update(extra)
        return preflight_mod.check(req, worktree=ROOT)

    def test_no_lease_blocks(self):
        result = self.check()
        self.assertEqual((result["state"], result["reason_code"]), ("BLOCKED", "LEASE_EXPIRED"))

    def test_ready_after_acquire(self):
        lock_mod.acquire("模块负责1|A1", note="preflight", lock_dir=self.lease)
        self.addCleanup(self.release_lease)
        self.assertEqual(self.check()["state"], "READY")

    def test_stale_heartbeat_blocks(self):
        lock_mod.acquire("模块负责1|A1", note="stale", lock_dir=self.lease)
        self.addCleanup(self.release_lease)
        hb = os.path.join(self.lease, "heartbeat")
        old = os.path.getmtime(hb) - 3600
        os.utime(hb, (old, old))
        self.assertEqual(self.check()["reason_code"], "LEASE_EXPIRED")

    def test_wrong_owner_blocks(self):
        lock_mod.acquire("模块负责1|A1", note="x", lock_dir=self.lease)
        self.addCleanup(self.release_lease)
        self.assertEqual(self.check(expect_owner="模块负责2|A2")["reason_code"], "LEASE_EXPIRED")

    def test_capacity_shortfall_blocks(self):
        # 真事：8298 条需求对着 4000 的护栏值，开工必然半套通道。
        result = self.check(cap=4000, lease=False)
        self.assertEqual(result["reason_code"], "CAP_UNMET")
        self.assertIn("4298", result["detail"])

    def test_undeclared_cap_blocks(self):
        self.assertEqual(self.check(cap=None, lease=False)["reason_code"], "CAP_UNMET")

    def test_planned_skip_blocks(self):
        self.assertEqual(self.check(skipped=12, lease=False)["reason_code"], "GATE_FAILED")

    def test_provenance_outside_worktree_blocks(self):
        result = self.check(lease=False,
                            provenance={"stage_file": outside_path("mmdpipe", "stage.py")})
        self.assertEqual(result["reason_code"], "PROVENANCE_INVALID")

    def test_missing_provenance_blocks(self):
        self.assertEqual(self.check(lease=False, provenance={})["reason_code"], "PROVENANCE_INVALID")

    def test_existing_output_without_claim_blocks(self):
        self.assertEqual(self.check(lease=False, outputs=[self.existing])["reason_code"],
                         "OWNERSHIP_VIOLATION")

    def test_existing_output_claimed_by_run_id_or_ruling(self):
        self.assertEqual(self.check(lease=False, outputs=[self.existing], run_id="frame")["state"],
                         "READY")
        self.assertEqual(self.check(lease=False, outputs=[self.existing],
                                    overwrite="D-20261116-100")["state"], "READY")

    def test_blockers_reported_all_at_once_with_stable_precedence(self):
        result = self.check(lease=False, provenance={}, cap=1)
        self.assertEqual(result["reason_code"], "PROVENANCE_INVALID")   # 顺序在最前
        self.assertEqual([c["name"] for c in result["blockers"]], ["provenance", "capacity"])

    def test_cli_exit_codes(self):
        spec = self.path("spec.json")
        with io.open(spec, "w", encoding="utf-8") as fh:
            json.dump(dict(self.request, lease=False), fh, ensure_ascii=False)
        self.assertEqual(preflight_mod.main(["--spec", spec, "--worktree", ROOT]), 0)
        with io.open(spec, "w", encoding="utf-8") as fh:
            json.dump(dict(self.request, lease=False, cap=10), fh, ensure_ascii=False)
        self.assertEqual(preflight_mod.main(["--spec", spec, "--worktree", ROOT]), 4)


# --------------------------------------------------------------- 阶段 H：Human gate
class HumanGateTest(TempDirTest):
    """待批项只能被 Human 显式回答关掉——D0 代关必须被拒。

    **用合成样本，不读线上的 decisions.jsonl**：这张清单会随 Human 真的回答而变短，
    把它写死进测试就等于「Human 一答，测试就红」——那是判据在报假警，不是在测行为。
    线上数据只用一条不变式来核：`human_gate` 清单与 `status.pending_human()` 逐条相同。
    """

    OPEN = "D-20990101-001"          # 待批（无人回答）
    CLOSED = "D-20990101-002"        # 待批，但后面有一条显式提到它 ⇒ 已关闭
    OTHER = "D-20990101-003"         # 另一条待批

    def pending_row(self, decision_id, next_action):
        return {"decision_id": decision_id, "task_id": "M99", "attempt": 1,
                "decision": "RULING", "reason_code": "HUMAN_REQUIRED",
                "status_after": "partial", "human_approval_required": True,
                "next_action": next_action, "logged_at": "2026-09-01T10:00:00+08:00"}

    def setUp(self):
        super().setUp()
        self.copy = self.path("decisions.jsonl")
        rows = [
            self.pending_row(self.OPEN, "要不要在合成样本上开工"),
            self.pending_row(self.CLOSED, "这条会被后面那条关掉"),
            {"decision_id": "D-20990101-004", "task_id": "M99", "decision": "BLOCK",
             "reason_code": "GATE_FAILED", "human_approval_required": False,
             "resolves": [self.CLOSED], "logged_at": "2026-09-01T11:00:00+08:00"},
            self.pending_row(self.OTHER, "第二条待批"),
        ]
        with io.open(self.copy, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.expected = [self.OPEN, self.OTHER]

    def rows(self, path=None):
        with io.open(path or self.copy, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def test_open_list_is_exactly_the_open_ones(self):
        self.assertEqual([row["id"] for row in human_gate_mod.list_open(self.copy)], self.expected)

    def test_explicitly_resolved_item_is_closed(self):
        # 只有「后续裁决显式提到它」才关；时间新不算回答。
        self.assertNotIn(self.CLOSED, [row["id"] for row in human_gate_mod.list_open(self.copy)])

    def test_open_list_matches_status_aggregation(self):
        # `status --check` 的 C6 就是在核这条一致性：两个出口不许各说一套。
        self.assertEqual([row["id"] for row in human_gate_mod.list_open(self.copy)],
                         [row.get("decision_id") for row in status_mod.pending_human(self.rows())])

    def test_live_list_matches_status_aggregation(self):
        live = os.path.join(ROOT, "coordination", "decisions.jsonl")
        self.assertEqual([row["id"] for row in human_gate_mod.list_open(live)],
                         [row.get("decision_id") for row in status_mod.pending_human(self.rows(live))])

    def test_agent_cannot_close(self):
        for by in ("D0", "总控", "模块负责1", ""):
            with self.assertRaises(human_gate_mod.HumanGateError) as ctx:
                human_gate_mod.resolve(self.OPEN, "ACCEPT_MERGE", by=by,
                                       decisions_path=self.copy)
            self.assertEqual(ctx.exception.code, "NOT_HUMAN")

    def test_unknown_answer_rejected(self):
        with self.assertRaises(human_gate_mod.HumanGateError) as ctx:
            human_gate_mod.resolve(self.OPEN, "APPROVE", by="Human", decisions_path=self.copy)
        self.assertEqual(ctx.exception.code, "BAD_DECISION")

    def test_dry_run_writes_nothing(self):
        before = os.path.getsize(self.copy)
        draft = human_gate_mod.resolve(self.OPEN, "RETURN_FIX", by="Human",
                                       decisions_path=self.copy, dry_run=True)
        self.assertTrue(draft["dry_run"])
        self.assertEqual(os.path.getsize(self.copy), before)

    def test_resolve_closes_exactly_one_and_keeps_history_bytes(self):
        original = self.rows()
        record = human_gate_mod.resolve(self.OPEN, "RETURN_FIX", by="Human",
                                        note="重出", decisions_path=self.copy)
        self.assertEqual(record["resolves"], [self.OPEN])
        self.assertFalse(record["human_approval_required"])
        rows = self.rows()
        self.assertEqual(len(rows), len(original) + 1)
        self.assertEqual(rows[:len(original)], original)          # 历史行逐字未变
        self.assertEqual([r["id"] for r in human_gate_mod.list_open(self.copy)], self.expected[1:])

    def test_cannot_close_twice(self):
        human_gate_mod.resolve(self.OPEN, "CANCEL", by="Human", decisions_path=self.copy)
        with self.assertRaises(human_gate_mod.HumanGateError) as ctx:
            human_gate_mod.resolve(self.OPEN, "BLOCK", by="Human", decisions_path=self.copy)
        self.assertEqual(ctx.exception.code, "ALREADY_CLOSED")

    def test_unknown_target(self):
        with self.assertRaises(human_gate_mod.HumanGateError) as ctx:
            human_gate_mod.resolve("D-20261116-999", "BLOCK", by="Human", decisions_path=self.copy)
        self.assertEqual(ctx.exception.code, "NOT_FOUND")

    def test_relayed_answer_is_marked_as_transcription(self):
        # Human 在会话里说了答案、由 D0 转抄落库：必须留下原话与「不是 D0 自主决定」这句，
        # 否则「D0 代关」和「D0 抄写」在记录里长得一模一样。
        quote = "会话 2026-11-16T16:44 原话：「纳入git」"
        record = human_gate_mod.resolve(self.OPEN, "ACCEPT_INTERFACE", by="Human",
                                        decisions_path=self.copy, relayed_from=quote)
        self.assertEqual(record["relayed_from"], quote)
        self.assertTrue(any("不是 D0 自主决定" in line for line in record["evidence"]))
        self.assertEqual(record["resolves"], [self.OPEN])

    def test_direct_answer_has_no_relay_mark(self):
        record = human_gate_mod.resolve(self.OPEN, "CANCEL", by="Human",
                                        decisions_path=self.copy)
        self.assertNotIn("relayed_from", record)

    def test_pending_approval_is_not_squeezed_out_by_later_decisions(self):
        # D-086 修的真缺陷：早期待批项被后来**无关**裁决挤掉，等于无人回答却消失。
        early = {"decision_id": "D-20260101-001", "task_id": "M99", "decision": "RULING",
                 "reason_code": "RULING", "human_approval_required": True}
        later = {"decision_id": "D-20260101-002", "task_id": "M99", "decision": "ACCEPT",
                 "reason_code": "EVIDENCE_COMPLETE", "human_approval_required": False}
        pending = status_mod.pending_human([early, later])
        self.assertEqual([row["decision_id"] for row in pending], ["D-20260101-001"])
        closing = {"decision_id": "D-20260101-003", "task_id": "M99", "decision": "BLOCK",
                   "reason_code": "GATE_FAILED", "resolves": ["D-20260101-001"]}
        self.assertEqual(status_mod.pending_human([early, later, closing]), [])


# --------------------------------------------------------------- 阶段 I：真值档
class TruthTierTest(unittest.TestCase):
    def test_all_tiers_accepted(self):
        for tier in evidence_mod.TRUTH_TIERS:
            self.assertEqual(evidence_mod.normalize(ev(truth_tier=tier))["truth_tier"], tier)

    def test_bad_tier_rejected(self):
        for wrong in ("T4", "t3", "delivery", "T3b"):
            with self.assertRaises(evidence_mod.EvidenceError) as ctx:
                evidence_mod.normalize(ev(truth_tier=wrong))
            self.assertEqual(ctx.exception.reason_code, "WRONG_TRUTH_TIER")

    def test_old_records_keep_their_hash(self):
        # 老记录不带 truth_tier：加字段不许改它们的历史哈希。
        self.assertNotIn("truth_tier", evidence_mod.normalize(ev()))
        self.assertEqual(evidence_mod.digest(ev()), evidence_mod.digest(ev()))

    def test_tier_participates_in_hash(self):
        self.assertNotEqual(evidence_mod.digest(ev(truth_tier="T3")),
                            evidence_mod.digest(ev(truth_tier="T2")))

    def test_m08_only_accepts_delivery_tier(self):
        bundle = {"evidence_check_exit": 0, "coverage_check": "PASS", "acceptance_result": "PASS",
                  "truth_tier": "T3", "snapshot_paths": [], "module_provenance": {},
                  "resource_lease_valid": True}
        ok = gates_mod.check_bundle(dict(bundle, task_id="M08"), {"task_id": "M08"}, worktree=ROOT)
        self.assertEqual(ok["reason_code"], "EVIDENCE_COMPLETE")
        for tier in ("T0", "T1", "T2", "T_DESCRIPTIVE"):
            bad = gates_mod.check_bundle(dict(bundle, task_id="M08", truth_tier=tier),
                                         {"task_id": "M08"}, worktree=ROOT)
            self.assertEqual(bad["reason_code"], "EVIDENCE_SCOPE_MISMATCH", tier)

    def test_other_modules_accept_non_delivery_tiers(self):
        bundle = {"evidence_check_exit": 0, "coverage_check": "PASS", "acceptance_result": "PASS",
                  "truth_tier": "T1", "snapshot_paths": [], "module_provenance": {},
                  "resource_lease_valid": True}
        self.assertEqual(gates_mod.check_bundle(dict(bundle, task_id="M02"),
                                                {"task_id": "M02"}, worktree=ROOT)["reason_code"],
                         "EVIDENCE_COMPLETE")

    def test_cache_replay_cannot_report_t2_or_t3(self):
        bundle = {"evidence_check_exit": 0, "coverage_check": "PASS", "acceptance_result": "PASS",
                  "truth_tier": "T3", "snapshot_paths": [], "module_provenance": {},
                  "resource_lease_valid": True, "task_id": "M04", "pose_source": "cache_replay"}
        self.assertEqual(gates_mod.check_bundle(bundle, {"task_id": "M04"},
                                                worktree=ROOT)["reason_code"],
                         "EVIDENCE_SCOPE_MISMATCH")
        bundle["truth_tier"] = "T_DESCRIPTIVE"
        self.assertEqual(gates_mod.check_bundle(bundle, {"task_id": "M04"},
                                                worktree=ROOT)["reason_code"], "EVIDENCE_COMPLETE")


# --------------------------------------------------------------- 证据快照（D-159）
class EvidenceStoreTest(TempDirTest):
    def test_snapshot_path_shape(self):
        digest = "a" * 64
        path = store_mod.snapshot_path(digest, "x.md", root=self.tmp)
        self.assertEqual(os.path.relpath(path, self.tmp).replace("\\", "/"),
                         "a" * store_mod.SHA16 + "/x.md")

    def test_bad_digest_rejected(self):
        with self.assertRaises(store_mod.SnapshotError) as ctx:
            store_mod.snapshot_path("zz" * 4, root=self.tmp)
        self.assertEqual(ctx.exception.reason_code, "HASH_BASIS_INVALID")

    def test_snapshot_keeps_original_bytes(self):
        src = self.path("known_limits.md")
        payload = b"\xe7\xac\xac\xe4\xb8\x80\xe8\xa1\x8c\r\n\xe7\xac\xac\xe4\xba\x8c\xe8\xa1\x8c\r\n"
        with open(src, "wb") as fh:
            fh.write(payload)
        row = store_mod.snapshot_artifact(src, root=self.tmp)
        with open(row["snapshot"], "rb") as fh:
            self.assertEqual(fh.read(), payload)      # 不做 LF 归一：副本要能直接替换原件
        self.assertEqual(row["sha256"], store_mod.file_sha256(src))
        self.assertEqual(row["bytes"], len(payload))

    def test_idempotent_and_never_overwrites(self):
        src = self.path("a.txt")
        with open(src, "wb") as fh:
            fh.write(b"v1\n")
        first = store_mod.snapshot_artifact(src, root=self.tmp)
        self.assertEqual(store_mod.snapshot_artifact(src, root=self.tmp)["snapshot"],
                         first["snapshot"])
        with open(first["snapshot"], "wb") as fh:
            fh.write(b"tampered\n")
        with self.assertRaises(store_mod.SnapshotError) as ctx:
            store_mod.snapshot_artifact(src, root=self.tmp)
        self.assertEqual(ctx.exception.reason_code, "SNAPSHOT_INVALID")

    def test_declared_hash_mismatch_refuses_to_store(self):
        src = self.path("b.txt")
        with open(src, "wb") as fh:
            fh.write(b"v1\n")
        with self.assertRaises(store_mod.SnapshotError) as ctx:
            store_mod.snapshot_artifact(src, sha256="1" * 64, root=self.tmp)
        self.assertEqual(ctx.exception.reason_code, "HASH_BASIS_INVALID")

    def test_verify_reports_each_problem(self):
        src = self.path("c.txt")
        with open(src, "wb") as fh:
            fh.write(b"v1\n")
        row = store_mod.snapshot_artifact(src, root=self.tmp)
        self.assertTrue(store_mod.verify(row)["ok"])
        self.assertFalse(store_mod.verify({"path": row["path"], "sha256": row["sha256"]})["ok"])
        os.remove(row["snapshot"])
        problems = store_mod.verify(row)["problems"]
        self.assertEqual(len(problems), 1)
        self.assertIn("快照不存在", problems[0])


# --------------------------------------------------------------- 阶段 E：词表
class TaxonomyTest(unittest.TestCase):
    def test_history_fully_mapped(self):
        report = taxonomy_mod.check_history()
        self.assertEqual(report["missing_mapping"], [])
        self.assertEqual(report["unknown_decision_kinds"], [])
        self.assertGreaterEqual(report["records"], 162)

    def test_new_vocabulary_record_needs_no_legacy_mapping(self):
        # 修过的判据：词表落地后写的新裁决本来就合规，不该被判"缺 legacy 映射"；
        # 词表外的仍旧要报。
        path = os.path.join(tempfile.mkdtemp(prefix="tax-"), "decisions.jsonl")
        self.addCleanup(shutil.rmtree, os.path.dirname(path), True)
        rows = [
            {"decision_id": "D-20261116-163", "task_id": "SPEC",
             "decision": "ACCEPT_INTERFACE", "reason_code": "SPEC_CHANGE"},
            {"decision_id": "D-20261116-164", "task_id": "SPEC",
             "decision": "INVENTED_ACTION", "reason_code": "MADE_UP"},
        ]
        with io.open(path, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        report = taxonomy_mod.check_history(path)
        self.assertEqual(report["missing_mapping"], ["D-20261116-164"])
        self.assertEqual(report["unknown_decision_kinds"], ["INVENTED_ACTION"])

    def test_unknown_vocabulary_is_turned_into_needs_human(self):
        doc = taxonomy_mod.load()
        row = {"task_id": "M02", "decision": "INVENTED", "reason_code": "MADE_UP"}
        final = taxonomy_mod.normalize_or_needs_human(row, doc)
        self.assertEqual(final["decision"], "NEEDS_HUMAN")
        self.assertEqual(final["reason_code"], "SCOPE_CHANGE")
        self.assertTrue(final["human_approval_required"])

    def test_allowed_sets_are_closed(self):
        decisions, reasons = taxonomy_mod.allowed()
        # 词表里只有 7 个**动作**词。`RULING` / `CORRECTION` 是历史 kind，不在动作集内——
        # 这正是新架构的要求：每枚裁决都必须落成一个能改变状态的动作或 NEEDS_HUMAN。
        self.assertEqual(decisions, {"ACCEPT_MERGE", "ACCEPT_INTERFACE", "RETURN_FIX", "BLOCK",
                                     "REASSIGN", "NEEDS_HUMAN", "CANCEL"})
        for code in ("GATE_FAILED", "PROVENANCE_INVALID", "CAP_UNMET", "LEASE_EXPIRED",
                     "OWNERSHIP_VIOLATION", "EVIDENCE_SCOPE_MISMATCH", "SNAPSHOT_INVALID"):
            self.assertIn(code, reasons)


# --------------------------------------------------------------- 阶段 D：派工
class DispatcherP0Test(TempDirTest):
    def setUp(self):
        super().setUp()
        self.board = board_mod.Board(self.path("board.db"))
        self.board.init()
        self.addCleanup(self.board.close)

    def plan(self, **extra):
        return dispatcher_mod.plan(self.board, repo=ROOT, **extra)

    def lane_row(self, result, lane):
        return next(row for row in result["assignments"] if row["lane"] == lane)

    def approve(self, task_id, by):
        self.board.db.execute(
            "INSERT INTO events (ts, type, task_id, payload_json) VALUES (?,?,?,?)",
            (self.board.now().isoformat(timespec="seconds"),
             dispatcher_mod.P0_APPROVAL_EVENT, task_id, json.dumps({"by": by}, ensure_ascii=False)))
        self.board.db.commit()

    def test_p0_lane_exists_and_owns_m00(self):
        self.assertIn("P0", dispatcher_mod.LANES)
        self.assertIn("M00", dispatcher_mod.LANES["P0"])
        self.assertEqual(dispatcher_mod.LANE_SEAT["P0"], "A4")
        self.assertEqual(dispatcher_mod.lane_of("M00"), "P0")

    def test_empty_board_with_status_tasks_is_misconfigured(self):
        status_path = self.path("task_status.json")
        with io.open(status_path, "w", encoding="utf-8") as fh:
            json.dump({"tasks": {"M00": {"status": "PASS"}}}, fh)
        result = self.plan(status_path=status_path)
        self.assertEqual(result["state"], "MISCONFIGURED_EMPTY_BOARD")
        self.assertEqual(result["fix"], "python -m coordination.sync_board")

    def test_p0_requires_d0_approval(self):
        self.board.add_task("M00", "M00", "P0", status="ready")
        row = self.lane_row(self.plan(), "P0")
        self.assertEqual(row["action"], "needs_approval")
        self.assertEqual(row["reason_code"], "HUMAN_REQUIRED")

    def test_p0_approval_from_board_event(self):
        self.board.add_task("M00", "M00", "P0", status="ready")
        self.approve("M00", "D0")
        row = self.lane_row(self.plan(), "P0")
        self.assertEqual(row["action"], "claim")
        self.assertEqual(row["d0_approval"]["by"], "D0")

    def test_p0_approval_by_cli_flag(self):
        self.board.add_task("M00", "M00", "P0", status="ready")
        self.assertEqual(self.lane_row(self.plan(approve_p0=True), "P0")["action"], "claim")

    def test_approval_by_other_member_does_not_count(self):
        self.board.add_task("M00", "M00", "P0", status="ready")
        self.approve("M00", "模块负责4")
        self.assertEqual(self.lane_row(self.plan(), "P0")["action"], "needs_approval")


if __name__ == "__main__":
    unittest.main()
