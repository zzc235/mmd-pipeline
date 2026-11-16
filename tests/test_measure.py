"""M04 装配器：逐帧 → measurement 的聚合口径测试。

口径一旦被改，门禁的输入就变了，所以这里把每个聚合规则都钉死：
分位数插值、每帧取最大而不是全骨平均、尖峰的相对+绝对双条件、
冻结候选的挑选规则、穿透负值约定、缺穿透段不伪造。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

from mmdpipe import measure

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSEMBLY_PATH = os.path.join(REPO_ROOT, "presets", "physics_gate", "assembly_v1.json")
FRAMES = {"start": 1, "end": 10}


def assembly():
    with open(ASSEMBLY_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def rows(pairs, parent=0.0):
    """pairs: [(frame, bone, angle)] → dynamics 行。"""
    return [{"frame": f, "bone": b, "angle_deg": a, "parent_delta_deg": parent}
            for f, b, a in pairs]


class TestPercentile(unittest.TestCase):
    def test_linear_interpolation(self):
        self.assertAlmostEqual(measure._percentile([0, 10], 0.5), 5.0)
        self.assertAlmostEqual(measure._percentile([0, 10, 20], 0.95), 19.0)
        self.assertAlmostEqual(measure._percentile([7], 0.95), 7.0)

    def test_empty_sequence_raises(self):
        with self.assertRaises(measure.AssemblyError):
            measure._percentile([], 0.5)

    def test_median_and_mad(self):
        self.assertAlmostEqual(measure._median([1, 2, 3]), 2.0)
        self.assertAlmostEqual(measure._mad([1, 2, 3]), 1.0)


class TestDynamics(unittest.TestCase):
    def test_per_frame_max_not_bone_average(self):
        # 一根骨甩到 60°，另一根贴着 0°：平均会稀释成 30°，取每帧最大才是 60°。
        data = rows([(1, "sleeve_a", 60.0), (1, "sleeve_b", 0.0),
                     (2, "sleeve_a", 40.0), (2, "sleeve_b", 0.0)])
        m = measure.assemble(data, None, sample_id="t", evidence_mode="stepped",
                             frames=FRAMES, assembly=assembly())
        self.assertAlmostEqual(m["dynamics"]["max"], 60.0)
        self.assertEqual(m["dynamics"]["bones"], 2)

    def test_quiet_action_has_no_spikes(self):
        data = rows([(f, "b", 2.0) for f in range(1, 11)])
        m = measure.assemble(data, None, sample_id="t", evidence_mode="stepped",
                             frames=FRAMES, assembly=assembly())
        self.assertEqual(m["dynamics"]["spike_count"], 0)

    def test_spike_needs_relative_and_absolute(self):
        # 一帧暴涨到 200°，其余 2°：相对与绝对都满足 → 记 1 个尖峰
        data = rows([(f, "b", 2.0) for f in range(1, 10)] + [(10, "b", 200.0)])
        m = measure.assemble(data, None, sample_id="t", evidence_mode="stepped",
                             frames=FRAMES, assembly=assembly())
        self.assertEqual(m["dynamics"]["spike_count"], 1)

    def test_small_outlier_below_abs_floor_is_not_spike(self):
        # 相对暴涨但绝对值只有 25°（< 30° 绝对下限）：不算尖峰
        data = rows([(f, "b", 0.5) for f in range(1, 10)] + [(10, "b", 25.0)])
        m = measure.assemble(data, None, sample_id="t", evidence_mode="stepped",
                             frames=FRAMES, assembly=assembly())
        self.assertEqual(m["dynamics"]["spike_count"], 0)

    def test_empty_dynamics_raises(self):
        with self.assertRaises(measure.AssemblyError):
            measure.assemble([], None, sample_id="t", evidence_mode="stepped",
                             frames=FRAMES, assembly=assembly())


class TestFrozen(unittest.TestCase):
    def test_picks_most_frozen_candidate(self):
        data = rows([(f, "moving", 40.0, ) for f in range(1, 11)], parent=60.0) + \
               rows([(f, "stuck", 0.0) for f in range(1, 11)], parent=60.0)
        m = measure.assemble(data, None, sample_id="t", evidence_mode="stepped",
                             frames=FRAMES, assembly=assembly())
        self.assertEqual(m["frozen"]["bone"], "stuck")
        self.assertAlmostEqual(m["frozen"]["target_delta_deg"], 0.0)
        self.assertEqual(m["frozen"]["consecutive_frames"], 10)
        self.assertEqual(m["frozen"]["candidates"], 2)

    def test_static_action_reports_zero_parent(self):
        data = rows([(f, "b", 0.0) for f in range(1, 11)], parent=1.0)
        m = measure.assemble(data, None, sample_id="t", evidence_mode="stepped",
                             frames=FRAMES, assembly=assembly())
        self.assertEqual(m["frozen"]["parent_delta_deg"], 0.0)
        self.assertEqual(m["frozen"]["candidates"], 0)

    def test_streak_counts_longest_run(self):
        pairs = [(f, "b", 0.0) for f in (1, 2, 3)]
        pairs += [(4, "b", 5.0)]
        pairs += [(f, "b", 0.0) for f in (5, 6, 7, 8, 9, 10)]
        m = measure.assemble(rows(pairs, parent=60.0), None, sample_id="t",
                             evidence_mode="stepped", frames=FRAMES, assembly=assembly())
        self.assertEqual(m["frozen"]["consecutive_frames"], 6)


class TestPenetration(unittest.TestCase):
    def test_negative_depth_is_penetration(self):
        pen = [{"frame": 5, "roi": "row11", "max_depth_m": -0.2, "bone": "b1"},
               {"frame": 6, "roi": "row11", "max_depth_m": -0.15, "bone": "b2"},
               {"frame": 7, "roi": "row11", "max_depth_m": 0.01, "bone": "b3"}]
        m = measure.assemble(rows([(f, "b", 1.0) for f in range(1, 11)]), pen,
                             sample_id="t", evidence_mode="baked",
                             frames=FRAMES, assembly=assembly())
        self.assertAlmostEqual(m["penetration"]["max_depth_m"], -0.2)
        self.assertEqual(m["penetration"]["frames"], 2)
        self.assertEqual(m["penetration"]["bones"], 2)

    def test_absent_section_when_no_rows(self):
        m = measure.assemble(rows([(f, "b", 1.0) for f in range(1, 11)]), [],
                             sample_id="t", evidence_mode="baked",
                             frames=FRAMES, assembly=assembly())
        self.assertNotIn("penetration", m,
                         "没有穿透数据就不要伪造一段，门禁会返回 UNKNOWN")

    def test_unknown_roi_raises(self):
        pen = [{"frame": 1, "roi": "row11", "max_depth_m": -0.1}]
        with self.assertRaises(measure.AssemblyError):
            measure.assemble(rows([(f, "b", 1.0) for f in range(1, 11)]), pen,
                             sample_id="t", evidence_mode="baked", frames=FRAMES,
                             assembly=assembly(), penetrations_roi="row99")


class TestNullTolerance(unittest.TestCase):
    """真实采样的首帧 parent_delta_deg 是 null（没有上一帧可比较）。

    这条不是理论：M02 交付的 10 套 dyn，每套 4320 行里恰好 18 个 null（18 根骨各一条，都在首帧）。
    早先的装配器直接 float(None) 抛 TypeError，等于把每份真实采样都判死。
    """

    def test_null_parent_delta_on_first_frame_is_skipped(self):
        data = [{"frame": 1, "bone": "b", "angle_deg": 0.0, "parent_delta_deg": None}]
        data += [{"frame": f, "bone": "b", "angle_deg": 0.0, "parent_delta_deg": 60.0}
                 for f in range(2, 11)]
        m = measure.assemble(data, None, sample_id="t", evidence_mode="stepped",
                             frames=FRAMES, assembly=assembly())
        self.assertEqual(m["frozen"]["parent_delta_deg"], 60.0)
        self.assertEqual(m["frozen"]["candidates"], 1)

    def test_all_null_parent_gives_zero_candidates(self):
        data = [{"frame": f, "bone": "b", "angle_deg": 1.0, "parent_delta_deg": None}
                for f in range(1, 11)]
        m = measure.assemble(data, None, sample_id="t", evidence_mode="stepped",
                             frames=FRAMES, assembly=assembly())
        self.assertEqual(m["frozen"]["candidates"], 0,
                         "父链全部不可比时不能编造冻结候选")
        self.assertEqual(m["frozen"]["parent_delta_deg"], 0.0)

    def test_zero_parent_with_large_angle_is_flagged(self):
        """父链增量恒 0 但目标角 40°：分不清「静止」和「没测」，必须打标记。

        来源是真实数据：M02 首采 240 帧 × 18 骨，parent_delta_deg 全 0.0，
        而 angle 从 1.74° 变到 67.2°。不打标记，冻结门禁会凭一个 0 就判 PASS。
        """
        data = [{"frame": f, "bone": "b", "angle_deg": 40.0, "parent_delta_deg": 0.0}
                for f in range(1, 11)]
        m = measure.assemble(data, None, sample_id="t", evidence_mode="stepped",
                             frames=FRAMES, assembly=assembly())
        self.assertTrue(m["frozen"]["parent_all_zero"])
        self.assertTrue(m["frozen"]["suspicious_zero_parent"])
        self.assertAlmostEqual(m["frozen"]["target_delta_deg"], 40.0)

    def test_zero_parent_with_small_angle_is_not_flagged(self):
        data = [{"frame": f, "bone": "b", "angle_deg": 1.0, "parent_delta_deg": 0.0}
                for f in range(1, 11)]
        m = measure.assemble(data, None, sample_id="t", evidence_mode="stepped",
                             frames=FRAMES, assembly=assembly())
        self.assertFalse(m["frozen"]["suspicious_zero_parent"],
                         "目标本来就不动时，恒 0 的父链不值得告警")

    def test_null_angle_is_an_error_not_zero(self):
        data = [{"frame": f, "bone": "b", "angle_deg": 1.0, "parent_delta_deg": 1.0}
                for f in range(1, 10)]
        data.append({"frame": 10, "bone": "b", "angle_deg": None, "parent_delta_deg": 1.0})
        with self.assertRaises(measure.AssemblyError) as ctx:
            measure.assemble(data, None, sample_id="t", evidence_mode="stepped",
                             frames=FRAMES, assembly=assembly())
        self.assertIn("angle_deg", str(ctx.exception))

    def test_non_numeric_angle_raises_assembly_error(self):
        data = [{"frame": 1, "bone": "b", "angle_deg": "很直", "parent_delta_deg": 1.0}]
        with self.assertRaises(measure.AssemblyError):
            measure.assemble(data, None, sample_id="t", evidence_mode="stepped",
                             frames=FRAMES, assembly=assembly())


class TestInputErrors(unittest.TestCase):
    def test_duplicate_frame_bone_rejected(self):
        dup = rows([(1, "b", 1.0), (1, "b", 2.0)])
        with self.assertRaises(measure.AssemblyError):
            measure.assemble(dup, None, sample_id="t", evidence_mode="stepped",
                             frames=FRAMES, assembly=assembly())

    def test_missing_frames_raises(self):
        with self.assertRaises(measure.AssemblyError):
            measure.assemble(rows([(1, "b", 1.0)]), None, sample_id="t",
                             evidence_mode="stepped", frames={}, assembly=assembly())

    def test_bad_jsonl_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.jsonl")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('{"frame":1,"bone":"b","angle_deg":1.0,"parent_delta_deg":0.0}\n')
                fh.write("不是 JSON\n")
            with self.assertRaises(measure.AssemblyError):
                measure.load_jsonl(path)


class TestCli(unittest.TestCase):
    def test_roundtrip_through_gate(self):
        from mmdpipe import physics_gate as pg
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "装配 输出")
            os.makedirs(folder)
            dyn = os.path.join(folder, "dynamics 1.jsonl")
            with open(dyn, "w", encoding="utf-8", newline="\n") as fh:
                for f in range(1, 11):
                    fh.write(json.dumps({"frame": f, "bone": "b",
                                         "angle_deg": 3.0,
                                         "parent_delta_deg": 1.0}) + "\n")
            out = os.path.join(folder, "measurement 1.json")
            proc = subprocess.run(
                [sys.executable, "-m", "mmdpipe.measure", "--dynamics", dyn,
                 "--assembly", ASSEMBLY_PATH, "--sample-id", "cli",
                 "--frame-start", "1", "--frame-end", "10", "--out", out],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with open(out, encoding="utf-8") as fh:
                m = json.load(fh)
            report = pg.evaluate(m, pg.load_profile(os.path.join(
                REPO_ROOT, "presets", "physics_gate", "exploratory_v0.json")))
            # 没有穿透数据 → 该门禁 UNKNOWN，整体不可能是 PASS
            self.assertEqual(report["status"], pg.UNKNOWN)
            self.assertIn("penetration", report["unknown_gates"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
