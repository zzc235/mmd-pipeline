# -*- coding: utf-8 -*-
"""探针基线文件的口径（离屏，不开 Blender）。

守的是一个真缺陷：老写法只把 `v > 0` 的刚体对写进 `baseline_m`，于是「这一帧这个对
有没有基线」只能靠「key 在不在表里」，而**在基线帧本来没重叠的对**会被记成
`pairs_without_baseline`——它们的真值是 0。预注册的门要求 `pairs_without_baseline == 0`，
所以基线表必须覆盖整个候选对宇宙（含 0），并把「0 是量出来的」显式记下来。

（这不是纸上推的：2026-11-16 19:0x 第一轮实测 `C@W2` 39、`D` 6789，冻结比对器据此判 UNKNOWN。
口径实现在 `m04_baseline.py` 里，探针 import 它、本测试也 import 它 —— 同一份实现。）
"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = os.path.join(os.path.dirname(HERE), "reports", "subai", "M04", "scripts",
                      "m04_baseline.py")


def load_module():
    spec = importlib.util.spec_from_file_location("m04_baseline_uut", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PROBE_MOD = load_module()


class BaselinePayloadTest(unittest.TestCase):
    def test_zero_overlap_pairs_are_kept(self):
        base = {"下擺_0_10|上半身": 0.0, "下擺_0_11|上半身": 0.004321}
        doc = PROBE_MOD.baseline_payload(r"C:\x\arm.blend", "18_skirt_rigid", 1, base)
        self.assertEqual(doc["pairs"], 2)
        self.assertEqual(doc["pairs_with_zero_overlap"], 1)
        self.assertIn("下擺_0_10|上半身", doc["baseline_m"])       # 0 值必须留在表里
        self.assertEqual(doc["baseline_m"]["下擺_0_10|上半身"], 0.0)
        self.assertEqual(doc["baseline_m"]["下擺_0_11|上半身"], 0.004321)

    def test_spec_bumped_and_note_says_zero_is_measured(self):
        doc = PROBE_MOD.baseline_payload("arm.blend", "18", 1, {})
        self.assertEqual(doc["spec"], "penetration_baseline/2")
        self.assertIn("含 0", doc["note"])

    def test_all_zero_baseline(self):
        doc = PROBE_MOD.baseline_payload("arm.blend", "18", 1, {"a|b": 0.0, "c|d": 0.0})
        self.assertEqual(doc["pairs"], 2)
        self.assertEqual(doc["pairs_with_zero_overlap"], 2)

    def test_values_rounded_to_microns(self):
        doc = PROBE_MOD.baseline_payload("arm.blend", "18", 1, {"a|b": 0.0043210987})
        self.assertEqual(doc["baseline_m"]["a|b"], 0.004321)

    def test_scene_name_only_no_directory(self):
        doc = PROBE_MOD.baseline_payload(r"E:\very\long\path\C@W1.blend", "18", 1, {})
        self.assertEqual(doc["scene"], "C@W1.blend")


if __name__ == "__main__":
    unittest.main()
