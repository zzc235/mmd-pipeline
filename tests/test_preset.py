"""`preset.section()` 的行为：缺段/部分段要用默认值补齐，坏输入必须被拒。

背景（2026-11-16，1号 实测）：`presets/*.json` 是**差分文件**，磁盘上根本没有 `import` 段
（`kafuka_hsr_look.json` 只有 `camera` 与 `look`）。走 `preset.load()` 的产线没事，
但直接调 `stage_import(preset_dict)` 的调用者会 `KeyError` —— 而且那一行在 `try` 之外，
表现为导入阶段直接抛栈。这一层就是那个补丁，所以这里同时钉住"磁盘上确实缺这段"。
"""
import json
import os
import unittest

from mmdpipe import preset as P

PRESET_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "presets")


class TestSection(unittest.TestCase):
    def test_missing_section_falls_back_to_defaults(self):
        sec = P.section({}, "import")
        self.assertEqual(sec["scale"], P.DEFAULT_PRESET["import"]["scale"])
        self.assertEqual(set(sec), set(P.DEFAULT_PRESET["import"]))

    def test_partial_section_keeps_other_defaults(self):
        sec = P.section({"import": {"scale": 2.0}}, "import")
        self.assertEqual(sec["scale"], 2.0)
        self.assertEqual(sec["types"], P.DEFAULT_PRESET["import"]["types"])

    def test_explicit_values_win(self):
        sec = P.section({"import": {"types": ["MESH"], "scale": 0.5}}, "import")
        self.assertEqual(sec["types"], ["MESH"])
        self.assertEqual(sec["scale"], 0.5)

    def test_none_preset_gives_defaults(self):
        self.assertEqual(P.section(None, "render")["fps"], P.DEFAULT_PRESET["render"]["fps"])

    def test_unknown_section_is_rejected(self):
        with self.assertRaises(KeyError):
            P.section({}, "no_such_section")

    def test_non_dict_preset_is_rejected(self):
        with self.assertRaises(TypeError):
            P.section(["not", "a", "dict"], "import")

    def test_non_dict_section_is_rejected(self):
        with self.assertRaises(TypeError):
            P.section({"import": 3}, "import")

    def test_section_does_not_mutate_input(self):
        src = {"import": {"scale": 2.0}}
        P.section(src, "import")
        self.assertEqual(src, {"import": {"scale": 2.0}})

    def test_disk_preset_really_has_no_import_section(self):
        """钉住前提：预设文件缺 `import` 段，不是我以为它会缺。"""
        with open(os.path.join(PRESET_DIR, "kafuka_hsr_look.json"), "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        self.assertNotIn("import", raw)
        self.assertIn("scale", P.section(raw, "import"))


if __name__ == "__main__":
    unittest.main()
