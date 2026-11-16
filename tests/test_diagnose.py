"""M03 · F1–F6 归因判据的合成 fixture 与边界测试。

设计口径（对应任务书 阶段 D）
---------------------------
* 判据函数吃结构化 evidence，所以这里直接造 evidence，不启动 Blender。
* 「缺一个关键证据时不得 confirmed」逐类各测一条。
* 「静止动作 + 低增量不得误判 F3」单独一条 —— 这是 F3 最容易误报的地方。
* 264 只属于飞霄样本，不能写死在判据里：换一个回填体数量的合成模型再测一次。

真实 PMX 的集成测试用 `E:\\blender模型\\...\\星穹铁道—飞霄（无外套）.pmx`：
路径含中文，输出路径带空格，覆盖「路径含空格和中文」这一条。模型不存在时跳过。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

from mmdpipe import diagnose

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEIXIAO_PMX = r"E:\blender模型\没有外套本家模型\星穹铁道—飞霄（无外套）.pmx"
TAXONOMY = ("F1", "F2", "F3", "F4", "F5", "F6")


# ---------------------------------------------------------------- fixture 构造
def base_evidence() -> dict:
    """一个「什么都正常」的模型：已 build、已烘焙、无冻结、无缺口。"""
    return {
        "model": {"name": "synthetic", "version": 2.0, "encoding": "utf-8",
                  "bones": 60, "rigids": 40, "joints": 40},
        "structure": {
            "rigid_modes": {"2": 30},
            "feedback_rigids": 30,
            "joints_total": 40,
            "welded_joints": 0,
            "frozen_roots": [],
            "frozen_chains": [],
            "wide_limit_units": [],
            "units": [],
            "mass_available": True,
        },
        "coverage": {"bones_total": 60, "bones_with_any_rigid": 60,
                     "families": [], "gaps": [], "whole_missing": [],
                     "sparse_gaps": []},
        "blender": {
            "mmd_root": {"name": "synthetic", "is_built": True},
            "constraints": {"COPY_ROTATION": 30},
            "point_cache": {"is_baked": True, "frame_start": 1, "frame_end": 120},
            "rigid_mass_max_kg": 1.0,
            "frozen_pairs": [],
            "unit_angles": [],
            "penetration": [],
        },
        "cache": {"is_baked": True, "frame_start": 1, "frame_end": 120},
    }


def fixture_f1(feedback: int = 264) -> dict:
    ev = base_evidence()
    ev["blender"]["mmd_root"]["is_built"] = False
    ev["structure"]["feedback_rigids"] = feedback
    ev["blender"]["constraints"] = {}
    return ev


def fixture_f2() -> dict:
    ev = base_evidence()
    ev["blender"]["point_cache"] = {"is_baked": False, "frame_start": 1, "frame_end": 240}
    ev["cache"] = dict(ev["blender"]["point_cache"])
    return ev


def fixture_f3() -> dict:
    ev = base_evidence()
    ev["structure"]["frozen_roots"] = [{
        "joint": 0, "joint_name": "右胸", "target_body": 24, "target_bone": "右胸",
        "anchor_body": 6, "anchor_bone": "上半身2", "target_mode": 2,
        "limit_span_rad": 0.0, "spring_max": 0.0,
    }]
    ev["structure"]["frozen_chains"] = [{
        "anchor_bone": "上半身2", "root_body": 24, "bodies": [24],
        "bones": ["右胸"], "body_count": 1, "expansion": "welded_joints_only",
    }]
    ev["blender"]["frozen_pairs"] = [
        {"bone": "右胸", "parent": "上半身2", "rot_delta_deg": 0.0,
         "parent_rot_delta_deg": 32.0, "max_angle_deg": 32.0, "is_frozen_candidate": True},
        {"bone": "右胸１", "parent": "右胸", "rot_delta_deg": 1.2,
         "parent_rot_delta_deg": 0.0, "max_angle_deg": 32.0, "is_frozen_candidate": False},
    ]
    return ev


def fixture_f4() -> dict:
    ev = base_evidence()
    ev["structure"]["wide_limit_units"] = [{
        "uid": 4, "anchor_bone": "下半身", "bodies": 154, "joints": 277,
        "modes": {"0": 1, "2": 153}, "feedback_bodies": 153, "spring_max": 0.0,
        "limit_span_rad": 1.570796, "welded_joints": 2, "flex_joints": 275,
        "cycle_rank": 124, "zero_spring": True, "wide_limit": True,
    }]
    ev["blender"]["unit_angles"] = [{
        "uid": 4, "anchor_bones": ["下擺_0_0"], "max_angle_deg": 84.5,
        "bones_measured": 153,
    }]
    return ev


def fixture_f5() -> dict:
    ev = base_evidence()
    ev["coverage"]["gaps"] = [{
        "family": "下擺", "row": 11, "bones_total": 11,
        "bones_missing": ["下擺_11_7", "下擺_11_8"],
        "missing_count": 11, "missing_ratio": 1.0,
    }]
    ev["blender"]["penetration"] = [{
        "frame": 150, "families": ["下擺"], "bones": ["下擺_11_7"],
        "max_depth_m": -0.202,
    }]
    return ev


def fixture_f6() -> dict:
    ev = base_evidence()
    ev["ab"] = {
        "variable_changed": "rigid_body.collision_collections[组号]=True",
        "fields_compared": ["frames[0].bones.下擺_11_7.x", "penetration.max_depth_m"],
        "identical_fields": ["frames[0].bones.下擺_11_7.x", "penetration.max_depth_m"],
        "differing_fields": [],
        "result_identical": True,
        "source": "compare_ab",
    }
    return ev


def fixture_r0() -> dict:
    ev = base_evidence()
    ev["blender"]["penetration"] = [{
        "frame": 1, "families": ["髪"], "bones": ["髪穗1"], "max_depth_m": -0.058,
    }]
    return ev


def run(ev: dict, config: dict | None = None) -> dict:
    return diagnose.judge(ev, config or diagnose.default_config())


def diag_of(result: dict, cid: str) -> dict:
    for d in result["diagnostics"]:
        if d["id"] == cid:
            return d
    raise AssertionError("缺少判据 %s" % cid)


# ---------------------------------------------------------------- 正例
class TestPositiveCases(unittest.TestCase):
    def test_f1_not_built_confirmed(self):
        d = diag_of(run(fixture_f1()), "F1")
        self.assertTrue(d["matched"])
        self.assertEqual(d["confidence"], diagnose.CONFIRMED)
        self.assertIn("is_built", d["reason"])

    def test_f2_not_baked_confirmed(self):
        d = diag_of(run(fixture_f2()), "F2")
        self.assertTrue(d["matched"])
        self.assertEqual(d["confidence"], diagnose.CONFIRMED)
        self.assertIn("1", d["reason"])
        self.assertIn("240", d["reason"])

    def test_f3_frozen_confirmed(self):
        d = diag_of(run(fixture_f3()), "F3")
        self.assertTrue(d["matched"])
        self.assertEqual(d["confidence"], diagnose.CONFIRMED)
        self.assertIn("硬约束冻结", d["reason"])

    def test_f4_uncalibrated_is_suspected_only(self):
        d = diag_of(run(fixture_f4()), "F4")
        self.assertTrue(d["matched"])
        self.assertEqual(d["confidence"], diagnose.SUSPECTED)

    def test_f4_calibrated_can_confirm(self):
        cfg = diagnose.default_config()
        cfg["f4_calibrated"] = True
        cfg["thresholds"]["f4_angle_deg"]["calibrated"] = True
        d = diag_of(run(fixture_f4(), cfg), "F4")
        self.assertTrue(d["matched"])
        self.assertEqual(d["confidence"], diagnose.CONFIRMED)

    def test_f5_gap_with_penetration_confirmed(self):
        d = diag_of(run(fixture_f5()), "F5")
        self.assertTrue(d["matched"])
        self.assertEqual(d["confidence"], diagnose.CONFIRMED)
        self.assertIn("-0.202", d["reason"])

    def test_f6_identical_ab_confirmed(self):
        d = diag_of(run(fixture_f6()), "F6")
        self.assertTrue(d["matched"])
        self.assertEqual(d["confidence"], diagnose.CONFIRMED)
        self.assertIn("没有生效", d["reason"])


# ---------------------------------------------------------------- 缺证据不得 confirmed
class TestMissingEvidenceDowngrades(unittest.TestCase):
    def test_f1_without_runtime_evidence(self):
        ev = fixture_f1()
        ev["blender"].pop("mmd_root")
        ev["blender"].pop("constraints")
        d = diag_of(run(ev), "F1")
        self.assertNotEqual(d["confidence"], diagnose.CONFIRMED)
        self.assertIn("blender.mmd_root.is_built", d["missing_evidence"])

    def test_f2_without_cache_range(self):
        ev = fixture_f2()
        ev["blender"]["point_cache"].pop("frame_start")
        ev["blender"]["point_cache"].pop("frame_end")
        d = diag_of(run(ev), "F2")
        self.assertTrue(d["matched"])
        self.assertEqual(d["confidence"], diagnose.SUSPECTED)
        self.assertIn("blender.point_cache.frame_start", d["missing_evidence"])

    def test_f3_without_dynamic(self):
        ev = fixture_f3()
        ev["blender"].pop("frozen_pairs")
        d = diag_of(run(ev), "F3")
        self.assertTrue(d["matched"])
        self.assertEqual(d["confidence"], diagnose.SUSPECTED)

    def test_f4_without_angle(self):
        ev = fixture_f4()
        ev["blender"].pop("unit_angles")
        d = diag_of(run(ev), "F4")
        self.assertEqual(d["confidence"], diagnose.SUSPECTED)

    def test_f5_without_penetration(self):
        ev = fixture_f5()
        ev["blender"].pop("penetration")
        d = diag_of(run(ev), "F5")
        self.assertEqual(d["confidence"], diagnose.SUSPECTED)

    def test_f6_without_ab(self):
        ev = base_evidence()
        d = diag_of(run(ev), "F6")
        self.assertFalse(d["matched"])
        self.assertEqual(d["confidence"], diagnose.INSUFFICIENT)
        self.assertIn("ab.variable_changed", d["missing_evidence"])


# ---------------------------------------------------------------- 误报防护
class TestFalsePositiveGuards(unittest.TestCase):
    def test_static_action_low_delta_is_not_f3(self):
        """静止动作：父链和目标都几乎不动，低增量不能判 F3。"""
        ev = base_evidence()
        ev["blender"]["frozen_pairs"] = [
            {"bone": "下擺_0_0", "parent": "下半身", "rot_delta_deg": 0.0,
             "parent_rot_delta_deg": 0.1, "max_angle_deg": 0.1},
            {"bone": "下擺_0_1", "parent": "下擺_0_0", "rot_delta_deg": 0.02,
             "parent_rot_delta_deg": 0.05, "max_angle_deg": 0.1},
        ]
        d = diag_of(run(ev), "F3")
        self.assertFalse(d["matched"])
        self.assertIn("低增量不构成", d["reason"])

    def test_frozen_structure_in_static_action_stays_suspected(self):
        """有焊接根但采样区间父链没动：只能 suspected，不能 confirmed。"""
        ev = fixture_f3()
        ev["blender"]["frozen_pairs"] = [
            {"bone": "右胸", "parent": "上半身2", "rot_delta_deg": 0.0,
             "parent_rot_delta_deg": 0.2, "max_angle_deg": 0.2},
        ]
        d = diag_of(run(ev), "F3")
        self.assertEqual(d["confidence"], diagnose.SUSPECTED)

    def test_no_gap_no_f5(self):
        d = diag_of(run(base_evidence()), "F5")
        self.assertFalse(d["matched"])

    def test_ab_difference_rules_out_f6(self):
        ev = fixture_f6()
        ev["ab"]["differing_fields"] = ["penetration.max_depth_m"]
        ev["ab"]["result_identical"] = False
        d = diag_of(run(ev), "F6")
        self.assertFalse(d["matched"])

    def test_built_true_rules_out_f1(self):
        d = diag_of(run(base_evidence()), "F1")
        self.assertFalse(d["matched"])


# ---------------------------------------------------------------- 不硬编码 264
class TestNoHardcoded264(unittest.TestCase):
    def test_other_feedback_count(self):
        ev = fixture_f1(feedback=145)
        ev["blender"]["mmd_root"]["is_built"] = None   # 走「约束链缺失」这条路径
        d = diag_of(run(ev), "F1")
        self.assertTrue(d["matched"])
        self.assertEqual(d["confidence"], diagnose.CONFIRMED)
        self.assertIn("145", d["reason"])
        self.assertNotIn("264", d["reason"])

    def test_constraint_chain_missing_with_explicit_expected(self):
        """骨架有骨架、刚体有刚体，但约束数为 0 → F1 命中，不看是不是 264。"""
        ev = base_evidence()
        ev["blender"]["mmd_root"]["is_built"] = None
        ev["blender"]["constraints"] = {"COPY_ROTATION": 0}
        ev["structure"]["feedback_rigids"] = 7
        d = diag_of(run(ev), "F1")
        self.assertTrue(d["matched"])
        self.assertIn("7", d["reason"])


# ---------------------------------------------------------------- 分类学与多故障
class TestTaxonomy(unittest.TestCase):
    def test_r0_is_out_of_taxonomy(self):
        result = run(fixture_r0())
        self.assertEqual(result["primary"], diagnose.OUT_OF_TAXONOMY)
        self.assertNotIn(result["primary"], TAXONOMY)
        d = diag_of(result, diagnose.OUT_OF_TAXONOMY)
        self.assertIn("R0", d["reason"])

    def test_multi_fault_secondary(self):
        ev = fixture_f3()
        ev["structure"]["wide_limit_units"] = fixture_f4()["structure"]["wide_limit_units"]
        ev["blender"]["unit_angles"] = fixture_f4()["blender"]["unit_angles"]
        ev["coverage"]["gaps"] = fixture_f5()["coverage"]["gaps"]
        ev["blender"]["penetration"] = fixture_f5()["blender"]["penetration"]
        result = run(ev)
        self.assertEqual(result["primary"], "F3")          # 3.5 分最高
        self.assertEqual(result["confidence"], diagnose.CONFIRMED)
        ids = [s["id"] for s in result["secondary"]]
        self.assertIn("F5", ids)
        self.assertIn("F4", ids)
        self.assertEqual(len(ids), len(set(ids)))

    def test_unknown_when_everything_tested_and_nothing_matched(self):
        """所有判据都拿到了输入、且都没命中 → UNKNOWN（不是 PASS）。"""
        ev = base_evidence()
        ev["ab"] = {"variable_changed": "x", "fields_compared": ["a"],
                    "identical_fields": [], "differing_fields": ["a"],
                    "result_identical": False, "source": "compare_ab"}
        result = run(ev)
        self.assertEqual(result["primary"], diagnose.UNKNOWN)
        self.assertEqual(result["missing_evidence"], [])

    def test_base_evidence_waits_for_ab(self):
        """没有 A/B 时整体只能 INSUFFICIENT_EVIDENCE，并列出要补的字段。"""
        result = run(base_evidence())
        self.assertEqual(result["primary"], diagnose.INSUFFICIENT_EVIDENCE)
        self.assertIn("ab.variable_changed", result["missing_evidence"])

    def test_insufficient_evidence_when_all_blind(self):
        ev = {"model": {"bones": 10, "rigids": 0, "joints": 0},
              "structure": {"frozen_roots": None, "wide_limit_units": None,
                            "feedback_rigids": 0},
              "coverage": {"gaps": None},
              "blender": {}}
        result = run(ev)
        self.assertEqual(result["primary"], diagnose.INSUFFICIENT_EVIDENCE)
        self.assertTrue(result["missing_evidence"])


# ---------------------------------------------------------------- 报告契约
class TestReportContract(unittest.TestCase):
    def test_serializable_and_versioned(self):
        report = diagnose.build_report(
            fixture_f3(), source_type="pmx",
            input_path=r"C:\tmp\模型 目录\模型（副本）.pmx",
            input_sha256="a" * 64)
        blob = json.dumps(report, ensure_ascii=False)
        again = json.loads(blob)
        self.assertEqual(again["schema_version"], diagnose.SCHEMA_VERSION)
        self.assertEqual(again["taxonomy_version"], diagnose.TAXONOMY_VERSION)
        for key in ("input_path", "input_sha256", "source_type", "model", "frame_range",
                    "cache", "primary", "secondary", "status", "confidence",
                    "evidence", "missing_evidence", "warnings", "experiment_id"):
            self.assertIn(key, again)
        self.assertIn("模型（副本）", again["input_path"])

    def test_every_evidence_item_has_unit_and_frames(self):
        report = diagnose.build_report(fixture_f3(), source_type="pmx",
                                       input_path="x.pmx", input_sha256="b" * 64)
        for d in report["diagnostics"]:
            for item in d["evidence"]:
                self.assertEqual(set(item), {"key", "value", "unit", "compare", "frames", "source"})

    def test_fingerprint_is_deterministic(self):
        a = diagnose.build_report(fixture_f3(), source_type="pmx",
                                  input_path="x.pmx", input_sha256="c" * 64)
        b = diagnose.build_report(fixture_f3(), source_type="pmx",
                                  input_path="x.pmx", input_sha256="c" * 64)
        self.assertEqual(a["judgment_fingerprint"], b["judgment_fingerprint"])

    def test_primary_always_in_allowed_set(self):
        for ev in (base_evidence(), fixture_f1(), fixture_f2(), fixture_f3(),
                   fixture_f4(), fixture_f5(), fixture_f6(), fixture_r0()):
            result = run(ev)
            self.assertIn(result["primary"], diagnose.ALLOWED_PRIMARY)


# ---------------------------------------------------------------- A/B 比较
class TestCompareAB(unittest.TestCase):
    def test_identical_measurements(self):
        cfg = diagnose.default_config()
        ab = diagnose.compare_ab(
            {"frames": [{"f": 1, "depth": -0.2}], "variable_changed": "mask"},
            {"frames": [{"f": 1, "depth": -0.2}], "variable_changed": "mask"}, cfg)
        self.assertTrue(ab["result_identical"])
        self.assertEqual(ab["differing_fields"], [])
        self.assertIn("frames[0].depth", ab["fields_compared"])

    def test_different_measurements(self):
        cfg = diagnose.default_config()
        ab = diagnose.compare_ab(
            {"frames": [{"f": 1, "depth": -0.2}]},
            {"frames": [{"f": 1, "depth": -0.05}]}, cfg)
        self.assertFalse(ab["result_identical"])
        self.assertEqual(ab["differing_fields"], ["frames[0].depth"])

    def test_metadata_is_skipped(self):
        cfg = diagnose.default_config()
        ab = diagnose.compare_ab(
            {"path": "a.blend", "generated_at": "t1", "value": 1.0},
            {"path": "b.blend", "generated_at": "t2", "value": 1.0}, cfg)
        self.assertTrue(ab["result_identical"])


# ---------------------------------------------------------------- CLI
@unittest.skipUnless(os.path.isfile(FEIXIAO_PMX), "缺少飞霄 PMX 样本，跳过集成测试")
class TestCliIntegration(unittest.TestCase):
    def test_cli_on_real_pmx_with_spaces_and_chinese(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = os.path.join(tmp, "诊断 输出")
            out = os.path.join(out_dir, "diagnosis 1.json")
            proc = subprocess.run(
                [sys.executable, "-m", "mmdpipe.diagnose",
                 "--pmx", FEIXIAO_PMX, "--out", out],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(proc.returncode, diagnose.EXIT_OK, proc.stderr)
            self.assertTrue(os.path.isfile(out))
            with open(out, encoding="utf-8") as fh:
                report = json.load(fh)
            self.assertIn(report["primary"], diagnose.ALLOWED_PRIMARY)
            self.assertIn("飞霄", report["evidence"]["source"]["path"])
            self.assertEqual(len(report["evidence"]["source"]["sha256"]), 64)
            # 胸口 24–29 的焊接冻结根必须被静态判据抓到
            roots = report["evidence"]["structure"]["frozen_roots"]
            bodies = {r["target_body"] for r in roots}
            self.assertTrue({24, 27}.issubset(bodies))

    def test_cli_missing_input_exit_code(self):
        proc = subprocess.run(
            [sys.executable, "-m", "mmdpipe.diagnose", "--pmx", "不存在的模型.pmx"],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, diagnose.EXIT_INPUT)

    def test_cli_ab_pair_confirms_f6(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.json")
            b = os.path.join(tmp, "b.json")
            out = os.path.join(tmp, "d.json")
            payload = {"frames": [{"f": 150, "max_depth_m": -0.291}],
                       "variable_changed": "collision_collections"}
            for path in (a, b):
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh)
            proc = subprocess.run(
                [sys.executable, "-m", "mmdpipe.diagnose", "--pmx", FEIXIAO_PMX,
                 "--out", out, "--ab", a, b, "--fail-on-confirmed"],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(proc.returncode, diagnose.EXIT_CONFIRMED, proc.stderr)
            with open(out, encoding="utf-8") as fh:
                report = json.load(fh)
            self.assertEqual(report["primary"], "F6")
            self.assertEqual(report["confidence"], diagnose.CONFIRMED)


# ---------------------------------------------------------------- CLI 用法路径
class TestCliUsage(unittest.TestCase):
    """不带样本也要能跑的 CLI 路径（AGENTS.md 第三条：没参数的路径必须单独测）。

    实测缺陷（修前）：`main()` 里 `except SystemExit: return EXIT_USAGE` 把 argparse
    的 `--help`（SystemExit(0)）也当成用法错误，`--help` 退出码是 **2**。
    当时 37 条测试全绿——因为没有一条测过「只带 --help」这条路。
    """

    def _run(self, *argv):
        return subprocess.run(
            [sys.executable, "-m", "mmdpipe.diagnose", *argv],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8")

    def test_help_exits_zero(self):
        proc = self._run("--help")
        self.assertEqual(proc.returncode, diagnose.EXIT_OK, proc.stderr)
        self.assertIn("F1–F6", proc.stdout)

    def test_no_args_exits_usage(self):
        proc = self._run()
        self.assertEqual(proc.returncode, diagnose.EXIT_USAGE, proc.stderr)

    def test_unknown_flag_exits_usage(self):
        proc = self._run("--pmx", "x.pmx", "--no-such-flag")
        self.assertEqual(proc.returncode, diagnose.EXIT_USAGE, proc.stderr)


# ---------------------------------------------------------------- 真实证据回归
EVIDENCE_DIR = os.path.join(REPO_ROOT, "reports", "subai", "M03", "evidence")

# 录好的真实证据（本轮之前用 Blender / 真 PMX 采出来的 diagnosis JSON）。
# 判据改一次就要重跑这一组：证据不变、判定不许漂。缺文件时跳过——
# reports/ 不进版本控制，干净克隆里没有这些文件是正常的。
REAL_EVIDENCE = (
    ("F1", "blend/probe_v1.json", "F1", "confirmed"),
    ("F2", "blend/probe_combined_v3.json", "F2", "confirmed"),
    ("F2-b", "blend/probe_kafuka_all.json", "F2", "confirmed"),
    ("F3", "blend/S5_sleeve_60f.json", "F3", "confirmed"),
    ("F6", "static/S8_f6.json", "F6", "confirmed"),
    # 正常舞蹈场景：实测摆角 179.231°，阈值 60° 会误报，这里锁死「不得 confirmed」
    ("正常舞蹈不误报", "blend/S3_chest_60f.json", None, "suspected"),
    ("静态胸口", "static/S3.json", "F3", "suspected"),
)


class TestRealEvidenceRegression(unittest.TestCase):
    """证据不变则判定不许漂：judge() 与 judgment_fingerprint() 都要逐位复现。

    这一组补的是「F2 没有独立标签样本」的缺口——F2 的两份证据（合成场景与
    卡芙卡真实场景）现在都成了可重放的回归样本，不再是只存在于报告文字里的数字。
    """

    def _load(self, rel):
        path = os.path.join(EVIDENCE_DIR, *rel.split("/"))
        if not os.path.isfile(path):
            self.skipTest("缺少录好的证据文件：%s" % rel)
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_recorded_evidence_reproduces_primary_and_confidence(self):
        for name, rel, want_primary, want_conf in REAL_EVIDENCE:
            with self.subTest(fixture=name):
                report = self._load(rel)
                got = diagnose.judge(report["evidence"])
                self.assertEqual(got["confidence"], want_conf, report["primary"])
                if want_primary is not None:
                    self.assertEqual(got["primary"], want_primary)

    def test_recorded_evidence_reproduces_fingerprint(self):
        for name, rel, _p, _c in REAL_EVIDENCE:
            with self.subTest(fixture=name):
                report = self._load(rel)
                fresh = diagnose.judge(report["evidence"])
                rebuilt = dict(report)
                rebuilt.update({k: fresh[k] for k in
                                ("primary", "secondary", "confidence", "diagnostics")})
                self.assertEqual(diagnose.judgment_fingerprint(rebuilt),
                                 report["judgment_fingerprint"])


# ---------------------------------------------------------------- 静态采集器
class TestCollector(unittest.TestCase):
    def test_coverage_helper_groups_rows(self):
        config = diagnose.default_config()
        self.assertEqual(diagnose._family_of("下擺_11_7"), ("下擺", [11, 7]))
        self.assertEqual(diagnose._family_of("センター"), (None, []))
        # 阈值来自 config，不是散落在代码里的魔法数
        self.assertAlmostEqual(diagnose._threshold(config, "f5_gap_ratio"), 0.5)

    @unittest.skipUnless(os.path.isfile(FEIXIAO_PMX), "缺少飞霄 PMX 样本")
    def test_static_collect_marks_mass_unavailable(self):
        ev = diagnose.collect_pmx(FEIXIAO_PMX)
        self.assertFalse(ev["structure"]["mass_available"])
        self.assertEqual(ev["source"]["sha256"], diagnose.sha256_file(FEIXIAO_PMX))
        self.assertGreater(ev["structure"]["welded_joints"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
