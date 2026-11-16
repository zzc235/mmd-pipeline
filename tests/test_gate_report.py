"""M04 批量报告：混淆矩阵的统计口径测试。

两条最容易出假结论的地方，这里都钉死：
1. 没有 holdout 就**不许**出报告（同一批既标定又验证 = 虚假 100%）；
2. UNKNOWN **不进** TP/FP/TN/FN，也不进分母——缺数据不是结论。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

from mmdpipe import gate_report as gr
from mmdpipe import physics_gate as pg

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_PATH = os.path.join(REPO_ROOT, "presets", "physics_gate", "exploratory_v0.json")


def profile():
    return pg.load_profile(PROFILE_PATH)


def good():
    """一条三类门禁全 PASS 的测量。

    注意 penetration 也必须给足帧数与骨次：门禁对「0 帧 / 0 骨」返回 UNKNOWN，
    这是故意的（没测过不等于没穿），所以「好样本」要写成「测过、没超过 epsilon」。
    """
    return {
        "sample_id": "good", "evidence_mode": "baked",
        "frames": {"start": 1, "end": 60},
        "dynamics": {"median": 10.0, "p95": 20.0, "max": 30.0, "spike_count": 0, "bones": 100},
        "frozen": {"parent_delta_deg": 2.0, "target_delta_deg": 20.0, "consecutive_frames": 0},
        "penetration": {"roi": "r", "max_depth_m": 0.0, "frames": 3, "bones": 5},
    }


def bad():
    m = good()
    m["sample_id"] = "bad"
    m["penetration"] = {"roi": "r", "max_depth_m": -0.3, "frames": 9, "bones": 3}
    return m


def unknown():
    m = good()
    m["sample_id"] = "unknown"
    del m["dynamics"]
    return m


def rec(sample_id, expected, split, measurement):
    return {"sample_id": sample_id, "expected": expected,
            "split": split, "measurement": measurement}


class TestMatrix(unittest.TestCase):
    def test_counts_and_rates(self):
        records = [
            rec("g1", "PASS", "calibration", good()),
            rec("b1", "FAIL", "calibration", bad()),
            rec("g2", "PASS", "holdout", good()),
            rec("g3", "PASS", "holdout", good()),
            rec("b2", "FAIL", "holdout", bad()),
        ]
        report = gr.build_report(records, profile())
        cal, hold = report["calibration"], report["holdout"]
        self.assertEqual((cal["tp"], cal["fp"], cal["tn"], cal["fn"]), (1, 0, 1, 0))
        self.assertEqual((hold["tp"], hold["fp"], hold["tn"], hold["fn"]), (1, 0, 2, 0))
        self.assertEqual(hold["false_positive_rate"], 0.0)
        self.assertEqual(hold["false_negative_rate"], 0.0)

    def test_unknown_is_counted_separately(self):
        records = [
            rec("g1", "PASS", "calibration", good()),
            rec("u1", "FAIL", "calibration", unknown()),
            rec("g2", "PASS", "holdout", good()),
            rec("u2", "PASS", "holdout", unknown()),
        ]
        report = gr.build_report(records, profile())
        cal = report["calibration"]
        self.assertEqual(cal["unknown"], 1)
        self.assertEqual((cal["tp"], cal["fp"], cal["tn"], cal["fn"]), (0, 0, 1, 0),
                         "UNKNOWN 不能被当成 FN 或 TN")
        self.assertIsNone(cal["false_negative_rate"],
                          "该划分里没有一条有结论的坏样本时，漏报率必须是 None 而不是 0.0——"
                          "0.0 会被读成「一条都没漏」，而实际是一条都没测出来")
        self.assertEqual(cal["conclusive"], 1)

    def test_missing_holdout_refused(self):
        records = [rec("g1", "PASS", "calibration", good()),
                   rec("b1", "FAIL", "calibration", bad())]
        with self.assertRaises(gr.ReportError) as ctx:
            gr.build_report(records, profile())
        self.assertIn("holdout", str(ctx.exception))

    def test_empty_records_refused(self):
        with self.assertRaises(gr.ReportError):
            gr.build_report([], profile())

    def test_exploratory_profile_is_marked(self):
        records = [rec("g1", "PASS", "calibration", good()),
                   rec("g2", "PASS", "holdout", good())]
        report = gr.build_report(records, profile())
        self.assertTrue(report["exploratory"])
        self.assertIn("探索性", report["conclusion"])

    def test_repeatable(self):
        records = [rec("g1", "PASS", "calibration", good()),
                   rec("b1", "FAIL", "holdout", bad())]
        a = json.dumps(gr.build_report(records, profile()), sort_keys=True, ensure_ascii=False)
        b = json.dumps(gr.build_report(records, profile()), sort_keys=True, ensure_ascii=False)
        self.assertEqual(a, b)


class TestSpecLoading(unittest.TestCase):
    def test_bad_expected_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "spec.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"records": [{"sample_id": "a", "expected": "MAYBE",
                                        "split": "holdout", "measurement": "m.json"}]}, fh)
            with self.assertRaises(gr.ReportError):
                gr._load_records(path)

    def test_missing_measurement_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "spec.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"records": [{"sample_id": "a", "expected": "PASS",
                                        "split": "holdout",
                                        "measurement": "nope.json"}]}, fh)
            with self.assertRaises(gr.ReportError):
                gr._load_records(path)


class TestScope(unittest.TestCase):
    def test_out_of_scope_is_excluded_not_unknown(self):
        m = good()
        del m["penetration"]
        m["out_of_scope"] = ["penetration"]
        report = pg.evaluate(m, profile())
        self.assertEqual(report["status"], pg.PASS,
                         "声明范围外的门禁不该把整条样本拖成 UNKNOWN")
        self.assertEqual(report["out_of_scope_gates"], ["penetration"])

    def test_all_out_of_scope_is_unknown(self):
        m = good()
        m["out_of_scope"] = ["overshoot", "frozen", "penetration"]
        self.assertEqual(pg.evaluate(m, profile())["status"], pg.UNKNOWN,
                         "三类都范围外时没有任何证据支持 PASS")

    def test_unknown_gate_name_rejected(self):
        m = good()
        m["out_of_scope"] = ["不存在的门禁"]
        with self.assertRaises(pg.GateInputError):
            pg.evaluate(m, profile())


class TestCli(unittest.TestCase):
    def test_report_cli_chinese_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "报告 输出")
            os.makedirs(folder)
            g = os.path.join(folder, "好样本 1.json")
            b = os.path.join(folder, "坏样本 1.json")
            for path, data in ((g, good()), (b, bad())):
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, ensure_ascii=False)
            spec = os.path.join(folder, "清单.json")
            with open(spec, "w", encoding="utf-8") as fh:
                json.dump({"records": [
                    {"sample_id": "g1", "expected": "PASS", "split": "calibration",
                     "measurement": os.path.basename(g)},
                    {"sample_id": "b1", "expected": "FAIL", "split": "calibration",
                     "measurement": os.path.basename(b)},
                    {"sample_id": "g2", "expected": "PASS", "split": "holdout",
                     "measurement": os.path.basename(g)},
                ]}, fh, ensure_ascii=False)
            out = os.path.join(folder, "混淆 矩阵.json")
            proc = subprocess.run(
                [sys.executable, "-m", "mmdpipe.gate_report", "--spec", spec,
                 "--profile", PROFILE_PATH, "--out", out],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with open(out, encoding="utf-8") as fh:
                report = json.load(fh)
            self.assertEqual(report["holdout"]["tn"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
