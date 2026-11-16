# -*- coding: utf-8 -*-
"""`tests_bpy/m08_accept_probe.py` 的落盘序列化回归（离屏跑，不需要 Blender）。

钉住的缺陷（2026-11-16，1号 在真场景上报）：`stage.stage_mask()` 的 `wired_record` 是
**IDProperty 容器**，直接 `json.dumps` 会 `TypeError: Object of type IDPropertyArray is not
JSON serializable` —— 采集器整支退 3，一个读数都留不下来。

三条，缺一条这组测试就没意义：

* **正控**：假 IDProperty 数组/组确实能毒到 `json.dumps`（假件不忠，下面的用例就是空转）；
* **转换**：`to_plain()` 把容器压成 list/dict，嵌套与类型都对；
* **反控**：压不动的对象**不许静默过** —— `dumpable()` 必须把它记进 `errors`（判据那边因此判红）。
"""
import importlib.util
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_stage_wiring import load_stage  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE_PATH = os.path.join(ROOT, "tests_bpy", "m08_accept_probe.py")


class FakeIDPropertyArray:
    """`IDPropertyArray` 替身：**不可 JSON 序列化**，只暴露 `to_list()`。"""

    def __init__(self, values):
        self.values = list(values)

    def to_list(self):
        return list(self.values)


class FakeIDPropertyGroup:
    """`IDPropertyGroup` 替身：只暴露 `to_dict()`。"""

    def __init__(self, mapping):
        self.mapping = dict(mapping)

    def to_dict(self):
        return dict(self.mapping)


class FakeVector:
    def __init__(self, values):
        self.values = tuple(values)

    def to_tuple(self):
        return tuple(self.values)


def load_probe():
    stage, _bpy = load_stage()
    spec = importlib.util.spec_from_file_location("m08_accept_probe_offline", PROBE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, stage


def mask_report():
    """形如 `stage.stage_mask()` 的返回：值是 Blender 的 IDProperty 容器，不是普通 list/dict。"""
    return {
        "rigids": 312,
        "verdict": "WIRED",
        "verdict_reasons": [],
        "constraints_capped": False,
        "skipped_count": 0,
        "wired_record": FakeIDPropertyGroup({
            "verdict": "WIRED",
            "criteria": FakeIDPropertyArray([1, 1, 1, 1]),
            "readback_mismatch": FakeIDPropertyArray([]),
        }),
        "declared_pairs": FakeIDPropertyArray([3, 4, 5]),
        "scope_bodies": FakeIDPropertyArray([0, 1]),
    }


class TestFakesAreFaithful(unittest.TestCase):
    """正控：假件必须真的毒到 `json.dumps`，否则下面那些断言测不到缺陷。"""

    def test_array_is_not_json_serializable(self):
        with self.assertRaises(TypeError):
            json.dumps({"x": FakeIDPropertyArray([1, 2])})

    def test_group_is_not_json_serializable(self):
        with self.assertRaises(TypeError):
            json.dumps({"x": FakeIDPropertyGroup({"a": 1})})


class TestToPlain(unittest.TestCase):
    def setUp(self):
        self.probe, _stage = load_probe()

    def test_primitives_pass_through(self):
        for value in (None, True, False, 0, 312, 0.5, "WIRED", ""):
            plain, holes = self.probe.to_plain(value)
            self.assertEqual(plain, value)
            self.assertEqual(holes, [])

    def test_idproperty_array_becomes_list(self):
        plain, holes = self.probe.to_plain(FakeIDPropertyArray([1, 2, 3]))
        self.assertEqual(plain, [1, 2, 3])
        self.assertEqual(holes, [])
        self.assertIsInstance(plain, list)

    def test_idproperty_group_becomes_dict_recursively(self):
        plain, holes = self.probe.to_plain({"mask": mask_report()})
        self.assertEqual(holes, [])
        self.assertEqual(plain["mask"]["wired_record"]["verdict"], "WIRED")
        self.assertEqual(plain["mask"]["wired_record"]["criteria"], [1, 1, 1, 1])
        self.assertEqual(plain["mask"]["declared_pairs"], [3, 4, 5])
        json.dumps(plain)                       # 能序列化才算压成功

    def test_vector_becomes_list(self):
        plain, holes = self.probe.to_plain(FakeVector((0.0, 1.0, 2.0)))
        self.assertEqual(plain, [0.0, 1.0, 2.0])
        self.assertEqual(holes, [])

    def test_unknown_object_is_a_hole_not_silence(self):
        plain, holes = self.probe.to_plain({"weird": object()})
        self.assertEqual(list(plain), ["weird"])
        self.assertIn("unserializable", plain["weird"])
        self.assertEqual(len(holes), 1)
        self.assertIn("$.weird", holes[0])

    def test_dict_keys_are_stringified(self):
        plain, holes = self.probe.to_plain({1: "a", ("t",): "b"})
        self.assertEqual(holes, [])
        self.assertEqual(sorted(plain), ["('t',)", "1"])


class TestMaskFacts(unittest.TestCase):
    """`mask_facts()` 的输出必须能进 `json.dumps` —— 这是缺陷现场。"""

    def test_mask_facts_is_dumpable(self):
        probe, stage = load_probe()
        with mock.patch.object(stage, "stage_mask", lambda root=None: mask_report()):
            facts = probe.mask_facts()
        plain, holes = probe.to_plain(facts)
        self.assertEqual(holes, [])
        self.assertEqual(plain["wired_record"]["criteria"], [1, 1, 1, 1])
        self.assertEqual(json.loads(json.dumps(plain))["declared_pairs"], [3, 4, 5])

    def test_old_way_would_have_crashed(self):
        """现场取证：不对 mask_facts 做转换，`json.dumps` 就是当初那个 TypeError。"""
        probe, stage = load_probe()
        with mock.patch.object(stage, "stage_mask", lambda root=None: mask_report()):
            facts = probe.mask_facts()
        with self.assertRaises(TypeError):
            json.dumps(facts)


class TestDumpable(unittest.TestCase):
    def setUp(self):
        self.probe, _stage = load_probe()

    def test_clean_facts_stay_clean(self):
        facts = {"errors": [], "mask": {"wired_record": FakeIDPropertyGroup({"verdict": "WIRED"})}}
        out = self.probe.dumpable(facts)
        self.assertEqual(out["errors"], [])
        self.assertEqual(out["unplain"], [])
        self.assertEqual(out["mask"]["wired_record"], {"verdict": "WIRED"})
        json.dumps(out, ensure_ascii=False)

    def test_hole_becomes_an_error(self):
        facts = {"errors": [], "weird": object()}
        out = self.probe.dumpable(facts)
        self.assertTrue(out["unplain"])
        self.assertTrue(any("压不成 JSON" in line for line in out["errors"]))
        json.dumps(out, ensure_ascii=False)

    def test_hole_does_not_erase_existing_errors(self):
        facts = {"errors": ["sha 读不到：x"], "weird": object()}
        out = self.probe.dumpable(facts)
        self.assertEqual(out["errors"][0], "sha 读不到：x")
        self.assertEqual(len(out["errors"]), 2)


if __name__ == "__main__":
    unittest.main()
