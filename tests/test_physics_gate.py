"""M04 门禁：边界、缺数据、好/坏样本的合成测试。

设计口径
--------
* 全部用合成 measurement，不依赖 Blender、不依赖 `reports/`。
* 每个门禁正例/反例各一条，**缺数据必须 UNKNOWN、不能被别的 PASS 淹没**。
* 阈值一律从 `presets/physics_gate/exploratory_v0.json` 读，测试里不另写一套数字
  （写死两套数字，改配置时测试就会假装通过）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

from mmdpipe import physics_gate as pg

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_PATH = os.path.join(REPO_ROOT, "presets", "physics_gate", "exploratory_v0.json")


def profile():
    return pg.load_profile(PROFILE_PATH)


def measurement(**over):
    """一条三类门禁全 PASS 的基线测量；over 里给哪段就整段替换。"""
    base = {
        "sample_id": "synthetic",
        "evidence_mode": "stepped",
        "frames": {"start": 1, "end": 60},
        "dynamics": {"median": 37.2, "p95": 72.8, "max": 93.3,
                     "spike_count": 0, "bones": 420},
        "frozen": {"parent_delta_deg": 2.0, "target_delta_deg": 20.0,
                   "consecutive_frames": 0},
        "penetration": {"roi": "row11", "max_depth_m": 0.01, "frames": 5, "bones": 11,
                    "frames_measured": 240, "basis": "mesh"},
    }
    base.update(over)
    return base


class TestAggregation(unittest.TestCase):
    def test_all_pass(self):
        report = pg.evaluate(measurement(), profile())
        self.assertEqual(report["status"], pg.PASS)
        self.assertEqual(report["failed_gates"], [])
        self.assertEqual(report["unknown_gates"], [])

    def test_unknown_is_not_masked_by_pass(self):
        m = measurement()
        del m["dynamics"]
        report = pg.evaluate(m, profile())
        self.assertEqual(report["status"], pg.UNKNOWN,
                         "一个门禁缺数据不能因为别的门禁 PASS 就算合格")
        self.assertEqual(report["unknown_gates"], ["overshoot"])

    def test_fail_beats_unknown(self):
        m = measurement(frozen={"parent_delta_deg": 66.41, "target_delta_deg": 0.0,
                                "consecutive_frames": 60})
        del m["penetration"]
        report = pg.evaluate(m, profile())
        self.assertEqual(report["status"], pg.FAIL)
        self.assertEqual(report["failed_gates"], ["frozen"])

    def test_exit_codes(self):
        self.assertEqual(pg.exit_code_for(pg.PASS), 0)
        self.assertEqual(pg.exit_code_for(pg.FAIL), 1)
        self.assertEqual(pg.exit_code_for(pg.ERROR), 2)
        self.assertEqual(pg.exit_code_for(pg.UNKNOWN), 3)

    def test_deterministic(self):
        m = measurement()
        a = json.dumps(pg.evaluate(m, profile()), sort_keys=True, ensure_ascii=False)
        b = json.dumps(pg.evaluate(m, profile()), sort_keys=True, ensure_ascii=False)
        self.assertEqual(a, b)

    def test_exploratory_profile_is_flagged(self):
        report = pg.evaluate(measurement(), profile())
        self.assertEqual(report["profile_status"], "exploratory")
        self.assertTrue(any("探索性" in w for w in report["warnings"]),
                        "探索性阈值必须在结果里明说，不能混成生产结论")


class TestOvershoot(unittest.TestCase):
    def test_fail_on_p95_and_peak(self):
        m = measurement(dynamics={"median": 46.3, "p95": 242.0, "max": 638.0,
                                  "spike_count": 0, "bones": 420})
        report = pg.evaluate(m, profile())
        self.assertEqual(report["gate_results"]["overshoot"]["status"], pg.FAIL)

    def test_p95_boundary_equals_passes(self):
        p95_max = profile()["gates"]["overshoot"]["p95_max_deg"]
        m = measurement(dynamics={"median": 10.0, "p95": p95_max, "max": 260.0,
                                  "spike_count": 0, "bones": 420})
        self.assertEqual(pg.evaluate(m, profile())["gate_results"]["overshoot"]["status"],
                         pg.PASS, "等于阈值不算超过")

    def test_fail_on_spike_count(self):
        m = measurement(dynamics={"median": 46.3, "p95": 72.8, "max": 150.0,
                                  "spike_count": 17, "bones": 420})
        self.assertEqual(pg.evaluate(m, profile())["gate_results"]["overshoot"]["status"],
                         pg.FAIL)

    def test_quiet_action_with_zero_median(self):
        # median=0 时不能用「相对基线」放大倍数，否则安静动作会被判成过冲
        m = measurement(dynamics={"median": 0.0, "p95": 5.0, "max": 8.0,
                                  "spike_count": 0, "bones": 300})
        self.assertEqual(pg.evaluate(m, profile())["gate_results"]["overshoot"]["status"],
                         pg.PASS)

    def test_insufficient_frames(self):
        m = measurement(frames={"start": 1, "end": 5})
        self.assertEqual(pg.evaluate(m, profile())["gate_results"]["overshoot"]["status"],
                         pg.UNKNOWN)

    def test_missing_field_unknown(self):
        m = measurement(dynamics={"median": 10.0, "p95": 20.0, "max": 30.0,
                                  "bones": 400})
        out = pg.evaluate(m, profile())["gate_results"]["overshoot"]
        self.assertEqual(out["status"], pg.UNKNOWN)
        self.assertIn("dynamics.spike_count", out["missing"])


class TestFrozen(unittest.TestCase):
    def test_fail_when_parent_moves_and_target_is_frozen(self):
        m = measurement(frozen={"parent_delta_deg": 66.41, "target_delta_deg": 0.0,
                                "consecutive_frames": 60})
        self.assertEqual(pg.evaluate(m, profile())["gate_results"]["frozen"]["status"],
                         pg.FAIL)

    def test_static_action_is_not_frozen(self):
        m = measurement(frozen={"parent_delta_deg": 2.0, "target_delta_deg": 0.0,
                                "consecutive_frames": 60})
        self.assertEqual(pg.evaluate(m, profile())["gate_results"]["frozen"]["status"],
                         pg.PASS, "父链本来就没动，不能算冻结")

    def test_single_frame_zero_is_not_frozen(self):
        m = measurement(frozen={"parent_delta_deg": 60.0, "target_delta_deg": 0.0,
                                "consecutive_frames": 1})
        self.assertEqual(pg.evaluate(m, profile())["gate_results"]["frozen"]["status"],
                         pg.PASS)

    def test_target_moved_is_not_frozen(self):
        m = measurement(frozen={"parent_delta_deg": 60.0, "target_delta_deg": 30.0,
                                "consecutive_frames": 60})
        self.assertEqual(pg.evaluate(m, profile())["gate_results"]["frozen"]["status"],
                         pg.PASS)

    def test_static_parent_pass_reason_is_target_span_not_parent(self):
        """父链不动时，PASS 的理由必须落在目标自身跨度上（结论对、理由错也是错）。"""
        m = measurement(frozen={"parent_delta_deg": 0.0, "target_delta_deg": 0.0,
                                "consecutive_frames": 0, "parent_all_zero": True,
                                "target_span_deg": 66.297, "suspicious_zero_parent": False})
        out = pg.evaluate(m, profile())["gate_results"]["frozen"]
        self.assertEqual(out["status"], pg.PASS)
        self.assertIn("target_span_deg", out["reason"].replace("目标自身跨度", "target_span_deg"))
        self.assertIn("66.297", out["reason"])
        self.assertNotIn("本来就不该动", out["reason"],
                         "旧口径的文字不能再出现在 PASS 理由里")

    def test_reason_falls_back_when_span_missing(self):
        m = measurement(frozen={"parent_delta_deg": 2.0, "target_delta_deg": 0.0,
                                "consecutive_frames": 60})
        out = pg.evaluate(m, profile())["gate_results"]["frozen"]
        self.assertEqual(out["status"], pg.PASS)
        self.assertIn("本来就不该动", out["reason"], "旧生产者没给跨度，仍走旧文字")

    def test_suspicious_zero_parent_is_unknown_not_pass(self):
        """父链恒 0 + 目标角不小 → UNKNOWN。判 PASS 等于把没测过的量当合格。"""
        m = measurement(frozen={"parent_delta_deg": 0.0, "target_delta_deg": 40.0,
                                "consecutive_frames": 0,
                                "parent_all_zero": True,
                                "suspicious_zero_parent": True})
        out = pg.evaluate(m, profile())
        self.assertEqual(out["gate_results"]["frozen"]["status"], pg.UNKNOWN)
        self.assertIn("无法区分", out["gate_results"]["frozen"]["reason"])
        self.assertIn("frozen", out["unknown_gates"])


class TestPenetration(unittest.TestCase):
    def test_fail_on_history_depth(self):
        m = measurement(penetration={"roi": "row11", "max_depth_m": -0.202,
                                     "frames": 31, "bones": 11,
                                     "frames_measured": 240, "basis": "mesh"})
        self.assertEqual(pg.evaluate(m, profile())["gate_results"]["penetration"]["status"],
                         pg.FAIL)

    def test_epsilon_boundary(self):
        eps = profile()["gates"]["penetration"]["depth_epsilon_m"]
        at = measurement(penetration={"roi": "r", "max_depth_m": -eps,
                                      "frames": 3, "bones": 5,
                                      "frames_measured": 240, "basis": "mesh"})
        inside = measurement(penetration={"roi": "r", "max_depth_m": -eps + 0.001,
                                          "frames": 3, "bones": 5,
                                          "frames_measured": 240, "basis": "mesh"})
        self.assertEqual(pg.evaluate(at, profile())["gate_results"]["penetration"]["status"],
                         pg.FAIL)
        self.assertEqual(pg.evaluate(inside, profile())["gate_results"]["penetration"]["status"],
                         pg.PASS)

    def test_missing_roi_is_unknown(self):
        m = measurement(penetration={"max_depth_m": -0.3, "frames": 9, "bones": 4,
                                     "frames_measured": 240, "basis": "mesh"})
        out = pg.evaluate(m, profile())["gate_results"]["penetration"]
        self.assertEqual(out["status"], pg.UNKNOWN)
        self.assertIn("penetration.roi", out["missing"])

    def test_measured_without_penetration_is_pass(self):
        """第一份真实数据：240 帧全测、0 帧穿入（最深 -0.0171 < 0.02），必须 PASS。

        改前这里返回 UNKNOWN（判据错用 frames，把「测了没穿入」当成「没测」），
        等于这份门禁在干净样本上永远给不出 PASS。
        """
        m = measurement(penetration={"roi": "18_skirt_rigid", "max_depth_m": -0.017064,
                                     "frames": 0, "bones": 0,
                                     "frames_measured": 240, "basis": "mesh"})
        out = pg.evaluate(m, profile())["gate_results"]["penetration"]
        self.assertEqual(out["status"], pg.PASS)
        self.assertIn("240", out["reason"])

    def test_missing_basis_is_unknown(self):
        """口径缺失不许默认成 mesh：胶囊的数字贴不上网格 epsilon。"""
        m = measurement(penetration={"roi": "r", "max_depth_m": 0.0,
                                     "frames": 3, "bones": 5, "frames_measured": 240})
        out = pg.evaluate(m, profile())["gate_results"]["penetration"]
        self.assertEqual(out["status"], pg.UNKNOWN)
        self.assertIn("penetration.basis", out["missing"])

    def test_unknown_basis_is_unknown(self):
        m = measurement(penetration={"roi": "r", "basis": "gauss", "max_depth_m": 0.0,
                                     "frames": 3, "bones": 5, "frames_measured": 240})
        out = pg.evaluate(m, profile())["gate_results"]["penetration"]
        self.assertEqual(out["status"], pg.UNKNOWN)
        self.assertIn("basis", out["reason"])

    def test_capsule_pass_never_claims_model_clean(self):
        """胶囊干净只能说「刚体胶囊无重叠」，不许写成「无穿入」。"""
        m = measurement(penetration={"roi": "r", "basis": "capsule", "max_depth_m": -0.001,
                                     "frames": 2, "bones": 3, "frames_measured": 240})
        out = pg.evaluate(m, profile())["gate_results"]["penetration"]
        self.assertEqual(out["status"], pg.PASS)
        self.assertIn("刚体胶囊口径", out["reason"])
        self.assertIn("不代表模型无穿入", out["reason"])

    def test_mesh_reason_names_basis(self):
        m = measurement(penetration={"roi": "r", "basis": "mesh", "max_depth_m": -0.001,
                                     "frames": 2, "bones": 3, "frames_measured": 240})
        out = pg.evaluate(m, profile())["gate_results"]["penetration"]
        self.assertIn("网格口径", out["reason"])

    def test_basis_specific_epsilon_is_used(self):
        prof = json.loads(json.dumps(profile()))
        prof["gates"]["penetration"]["depth_epsilon_capsule_m"] = 0.005
        m = measurement(penetration={"roi": "r", "basis": "capsule", "max_depth_m": -0.008,
                                     "frames": 2, "bones": 3, "frames_measured": 240})
        out = pg.evaluate(m, prof)["gate_results"]["penetration"]
        self.assertEqual(out["status"], pg.FAIL)
        self.assertIn("0.0050", out["reason"])

    def test_missing_frames_measured_is_unknown(self):
        m = measurement(penetration={"roi": "r", "max_depth_m": 0.0,
                                     "frames": 3, "bones": 5})
        out = pg.evaluate(m, profile())["gate_results"]["penetration"]
        self.assertEqual(out["status"], pg.UNKNOWN)
        self.assertIn("penetration.frames_measured", out["missing"])

    def test_absent_section_is_unknown(self):
        m = measurement()
        del m["penetration"]
        self.assertEqual(pg.evaluate(m, profile())["status"], pg.UNKNOWN)


class TestErrors(unittest.TestCase):
    def test_bad_type_raises(self):
        m = measurement(dynamics={"median": 1.0, "p95": 2.0, "max": "很大",
                                  "spike_count": 0, "bones": 10})
        with self.assertRaises(pg.GateInputError):
            pg.evaluate(m, profile())

    def test_bool_is_rejected(self):
        m = measurement(dynamics={"median": 1.0, "p95": 2.0, "max": True,
                                  "spike_count": 0, "bones": 10})
        with self.assertRaises(pg.GateInputError):
            pg.evaluate(m, profile())

    def test_nan_is_rejected(self):
        m = measurement(penetration={"roi": "r", "max_depth_m": float("nan"),
                                     "frames": 1, "bones": 1,
                                     "frames_measured": 1, "basis": "mesh"})
        with self.assertRaises(pg.GateInputError):
            pg.evaluate(m, profile())

    def test_profile_without_version(self):
        bad = json.loads(json.dumps(profile()))
        del bad["threshold_version"]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(bad, fh)
            with self.assertRaises(pg.GateInputError):
                pg.load_profile(path)


class TestCli(unittest.TestCase):
    def test_chinese_and_space_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "门禁 输出")
            os.makedirs(folder)
            meas = os.path.join(folder, "测量 1.json")
            out = os.path.join(folder, "门禁 结果.json")
            with open(meas, "w", encoding="utf-8") as fh:
                json.dump(measurement(), fh, ensure_ascii=False)
            proc = subprocess.run(
                [sys.executable, "-m", "mmdpipe.physics_gate",
                 "--measurement", meas, "--profile", PROFILE_PATH, "--out", out],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(proc.returncode, pg.EXIT_PASS, proc.stderr)
            with open(out, encoding="utf-8") as fh:
                report = json.load(fh)
            self.assertEqual(report["status"], pg.PASS)
            self.assertEqual(report["threshold_version"],
                             profile()["threshold_version"])

    def test_exit_code_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            meas = os.path.join(tmp, "m.json")
            with open(meas, "w", encoding="utf-8") as fh:
                json.dump(measurement(penetration={"roi": "r", "max_depth_m": -0.5,
                                                   "frames": 3, "bones": 9,
                                                   "frames_measured": 240,
                                                   "basis": "mesh"}), fh)
            proc = subprocess.run(
                [sys.executable, "-m", "mmdpipe.physics_gate",
                 "--measurement", meas, "--profile", PROFILE_PATH],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(proc.returncode, pg.EXIT_FAIL, proc.stderr)

    def test_config_error_exits_2_and_writes_no_json(self):
        """ERROR 不是聚合结果：退出码 2 且不产出 gate JSON。

        这条钉住的是「消费方别写 ERROR 状态的解析分支」——
        D-024 指出的那句错注释就错在这里：把 ERROR 当成第三级聚合，
        会让人写出一个永不可达的分支，然后以为自己处理了错误路径。
        """
        with tempfile.TemporaryDirectory() as tmp:
            meas = os.path.join(tmp, "m.json")
            with open(meas, "w", encoding="utf-8") as fh:
                json.dump(measurement(), fh)
            bad = os.path.join(tmp, "bad_profile.json")
            with open(bad, "w", encoding="utf-8") as fh:
                json.dump({"profile_id": "x"}, fh)  # 缺 threshold_version / gates
            out = os.path.join(tmp, "gate.json")
            proc = subprocess.run(
                [sys.executable, "-m", "mmdpipe.physics_gate",
                 "--measurement", meas, "--profile", bad, "--out", out],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(proc.returncode, pg.EXIT_ERROR, proc.stderr)
            self.assertFalse(os.path.exists(out),
                             "配置错误时不许留下半成品 JSON，否则消费方会读到不完整结果")


if __name__ == "__main__":
    unittest.main(verbosity=2)
