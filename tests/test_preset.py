"""`preset.section()` 的行为：缺段/部分段要用默认值补齐，坏输入必须被拒。

背景（2026-11-16，1号 实测）：`presets/*.json` 是**差分文件**，磁盘上根本没有 `import` 段
（`kafuka_hsr_look.json` 只有 `camera` 与 `look`）。走 `preset.load()` 的产线没事，
但直接调 `stage_import(preset_dict)` 的调用者会 `KeyError` —— 而且那一行在 `try` 之外，
表现为导入阶段直接抛栈。这一层就是那个补丁，所以这里同时钉住"磁盘上确实缺这段"。

**差分必须走 `load()`**（`D-082` 同族「看起来通过」）：`TestEffectiveDiff` 用 `load()` 之后的
**生效配置**做比对，并且带三条反控——
① 文件里明写了默认值不算差异（裸比对会给出假差异）；
② 把 `section()` 退化成"直返原始 dict"（修好之前的行为）时，这套比对必须**判红**，
   否则「不走 load() 就测不到」只是叙述、不是判据；
③ 同一份文件 `load()` 两次差分为空（比对不会自己造出差异）。
"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from mmdpipe import preset as P

PRESET_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "presets")


def effective_diff(a, b, sections):
    """两份**磁盘上的差分段**在指定段上的差分：`键 -> (a 的生效值, b 的生效值)`。

    差分段里没写的键不是「没有这个键」，而是「用 `DEFAULT_PRESET` 的值」——补这一步
    只有 `preset.section()`（`preset.load()` 内用它）能做。所以差分报的是生效值：
    "a 写了 85、b 没写" 会写成 `camera.lens: (85.0, 50.0)`，读数的人一眼看到 b 实际用什么。
    """
    rows = {}
    for name in sections:
        sa, sb = P.section(a, name), P.section(b, name)
        for key in sorted(set(sa) | set(sb)):
            if sa.get(key) != sb.get(key):
                rows["%s.%s" % (name, key)] = (sa.get(key), sb.get(key))
    return rows


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


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


class TestEffectiveDiff(unittest.TestCase):
    """差分必须走 `preset.load()`：比对的是生效配置，而不是磁盘上的差分段。"""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="preset_diff_")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def _write(self, name, obj):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False)
        return path

    # ------------------------------------------------------------ 正控

    def test_positive_control_real_difference_is_visible(self):
        """正控：改了一处 → 差异可见，且**没改的那一侧给出生效值**（而不是「缺键」）。"""
        raw_a = {"camera": {"lens": 85.0}}
        raw_b = {"camera": {"loc": [0, 0, 0]}}
        path_a = self._write("a.json", raw_a)
        self._write("b.json", raw_b)
        self.assertEqual(
            effective_diff(raw_a, raw_b, ("camera",)),
            {"camera.lens": (85.0, P.DEFAULT_PRESET["camera"]["lens"]),
             "camera.loc": (None, [0, 0, 0])},
            "差分没看见真实差异（或没给出 b 的生效值）")
        # 同一个结论也要能从 `preset.load()` 拿到——生产路径走的就是它
        loaded = P.load(path_a)
        self.assertEqual(loaded["camera"]["lens"], 85.0)
        self.assertEqual(loaded["camera"]["loc"], P.DEFAULT_PRESET["camera"]["loc"])

    def test_negative_control_same_file_twice_has_no_diff(self):
        """反控③：同一份内容比两次，差分必须为空（比对不自己造差异）。"""
        raw = {"camera": {"lens": 85.0}}
        self.assertEqual(
            effective_diff(raw, json.loads(json.dumps(raw)), ("camera", "look", "render")),
            {})

    # ------------------------------------------------------------ 反控①：裸比对给假差异

    def test_negative_control_writing_a_default_is_not_a_difference(self):
        """反控①：文件里明写了默认值 ≠ 真差异；裸 JSON 比对会给出一个假差异。"""
        bare = self._write("bare.json", {})
        explicit = self._write("explicit.json", {"look": {"route": "auto"}})
        self.assertNotEqual(_read(explicit), _read(bare),
                            "前提不成立：两份文件裸比对竟然一样")
        self.assertEqual(
            effective_diff(_read(bare), _read(explicit), ("look",)), {},
            "写法差异被当成了真实差异（裸比对那一路的假阳性）")

    # ------------------------------------------------------------ 反控②：退化实现必须判红

    def test_reverse_control_degraded_section_is_judged_red(self):
        """反控②：把 `section()` 退化成「直返原始 dict」（修好之前的实现）⇒ 这套比对必须判红。

        **这是给假绿留的反控**：如果退化实现也能得出同一个结论，那「必须走 load()」
        就只是叙述，判据根本没测到任何东西。
        """
        raw_a = {"camera": {"lens": 85.0}}
        raw_b = {"camera": {}}
        reference = effective_diff(raw_a, raw_b, ("camera",))
        self.assertEqual(reference,
                         {"camera.lens": (85.0, P.DEFAULT_PRESET["camera"]["lens"])})

        with mock.patch.object(P, "section",
                               lambda preset, name: dict(preset.get(name) or {})):
            degraded = effective_diff(raw_a, raw_b, ("camera",))
        self.assertNotEqual(
            degraded, reference,
            "退化实现给出了同一个结论 ⇒ 这套比对恒真，测不到「没走 load()」")
        self.assertIsNone(
            degraded["camera.lens"][1],
            "退化实现下 b 的生效值取不到（None）就是判红的那个红：%r" % (degraded,))

    # ------------------------------------------------------------ 磁盘上的真预设

    def test_real_presets_differ_only_where_they_really_do(self):
        """两份真预设：差异只落在它们真正改过的键上。"""
        hsr = _read(os.path.join(PRESET_DIR, "kafuka_hsr_look.json"))
        auto = _read(os.path.join(PRESET_DIR, "xiaogong_hsr.json"))
        diff = effective_diff(hsr, auto, ("look",))
        self.assertEqual(
            sorted(diff), ["look.hsr", "look.route"],
            "diff 里多了/少了键：%r" % (diff,))
        self.assertEqual(diff["look.route"], ("hsr", "auto"))
        # 两边都写了 post_processing=True ⇒ 不构成差异（写法不同、值一样）
        self.assertNotIn("look.post_processing", diff)
        # xiaogong 没写 sdf_body_type，生效值来自 DEFAULT ⇒ 与 kafuka 显式写的那个相同
        self.assertNotIn("look.sdf_body_type", diff)


if __name__ == "__main__":
    unittest.main()
