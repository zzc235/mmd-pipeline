# -*- coding: utf-8 -*-
"""`m04_preflight_spec.py` 的取数纪律（离屏，不开 Blender、不占锁）。

这组回归守的是「两个数不许凭记忆取」这条（`4号` 18:02 抓到的两棵树拼数）：

* 从场景记录取数时，**两种形状都要认**：顶层（`stage_mask()` 落盘）与
  `mask_wired_record`（回读件）；但形状要记进 `_derivation.numbers_source.shape`，
  否则下一个人分不清这数是从哪一层读出来的；
* 找不到数就**停**（退出 4），不许用 `mask_triple` 的 `null` 凑；
* 手给数必须带出处，缺出处同样停。
"""
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "reports", "subai", "M04", "scripts",
                      "m04_preflight_spec.py")


def load_script():
    spec = importlib.util.spec_from_file_location("m04_preflight_spec", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SPEC = load_script()


class TempCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="m04spec-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def write(self, name, payload):
        p = os.path.join(self.root, name)
        with io.open(p, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        return p


class SceneRecordTest(TempCase):
    def test_top_level_shape(self):
        p = self.write("rec.json", {"constraints_needed": 10111,
                                    "constraints_already_blocked": 1813,
                                    "constraints_to_add": 8298,
                                    "skipped_count": 0,
                                    "verdict": "WIRED",
                                    "constraints_capped": False})
        got = SPEC.numbers_from_scene_record(p)
        self.assertEqual((got["needed"], got["already"], got["to_add"]),
                         (10111, 1813, 8298))
        self.assertEqual(got["source"]["shape"], "top_level")

    def test_nested_mask_wired_record_shape(self):
        # 1号 的回读件形状：数在 mask_wired_record 里
        p = self.write("readback.json", {
            "mask_triple": {"verdict": "WIRED", "constraints_needed": None},
            "mask_wired_record": {"verdict": "WIRED", "constraints_needed": 10111,
                                  "constraints_already_blocked": 1813,
                                  "constraints_to_add": 8298, "skipped_count": 0,
                                  "constraints_capped": False}})
        got = SPEC.numbers_from_scene_record(p)
        self.assertEqual((got["needed"], got["already"], got["to_add"]),
                         (10111, 1813, 8298))
        self.assertEqual(got["source"]["shape"], "mask_wired_record")
        self.assertEqual(got["verdict"], "WIRED")

    def test_to_add_derived_when_absent(self):
        p = self.write("rec.json", {"constraints_needed": 10111,
                                   "constraints_already_blocked": 1813})
        self.assertEqual(SPEC.numbers_from_scene_record(p)["to_add"], 8298)

    def test_nulls_only_stops(self):
        # 反控：只有 mask_triple 的 null（没有 mask_wired_record）⇒ 停，不许当数
        p = self.write("bad.json", {"mask_triple": {"verdict": "WIRED",
                                                    "constraints_needed": None,
                                                    "constraints_added": None,
                                                    "constraints_already_blocked": None}})
        with self.assertRaises(SPEC.Stop) as ctx:
            SPEC.numbers_from_scene_record(p)
        self.assertIn("找不到 constraints_needed", str(ctx.exception))

    def test_missing_file_stops(self):
        with self.assertRaises(SPEC.Stop):
            SPEC.numbers_from_scene_record(os.path.join(self.root, "nope.json"))

    def test_partial_record_stops(self):
        p = self.write("half.json", {"constraints_needed": 10111})
        with self.assertRaises(SPEC.Stop) as ctx:
            SPEC.numbers_from_scene_record(p)
        self.assertIn("constraints_already_blocked", str(ctx.exception))


class SourceDisciplineTest(TempCase):
    def test_hand_given_without_note_stops(self):
        class Args:
            spec_source = ""
            needed = 8298
            already = 1813
            note_source = "  "
        with self.assertRaises(SPEC.Stop) as ctx:
            SPEC._pick_numbers(Args)
        self.assertIn("note-source", str(ctx.exception))

    def test_hand_given_with_note_ok(self):
        class Args:
            spec_source = ""
            needed = 8298
            already = 1813
            note_source = "1号 回读件的 mask_wired_record"
        got = SPEC._pick_numbers(Args)
        self.assertEqual((got["needed"], got["already"], got["to_add"]),
                         (8298, 1813, 6485))
        self.assertEqual(got["source"]["note"], "1号 回读件的 mask_wired_record")

    def test_nothing_given_stops(self):
        class Args:
            spec_source = ""
            needed = None
            already = None
            note_source = ""
        with self.assertRaises(SPEC.Stop):
            SPEC._pick_numbers(Args)


if __name__ == "__main__":
    unittest.main()
