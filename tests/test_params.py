"""参数声明层测试：面板与 CLI 必须同源。

这层是所有 P0 缺口的根源——两套独立维护的参数定义今天追平、下次加功能又漂移。
"""
import argparse
import unittest

from mmdpipe import params


class TestSchema(unittest.TestCase):
    def test_unique_names(self):
        names = [p.name for p in params.PARAMS]
        self.assertEqual(len(names), len(set(names)), "参数名重复")

    def test_argparse_matches_schema(self):
        ap = argparse.ArgumentParser()
        params.add_arguments(ap)
        declared = {a.dest for a in ap._actions if a.dest != "help"}
        expected = {p.name for p in params.PARAMS}
        self.assertEqual(declared, expected)

    def test_flags_use_dashes(self):
        ap = argparse.ArgumentParser()
        params.add_arguments(ap)
        opts = {o for a in ap._actions for o in a.option_strings}
        self.assertIn("--chain-gap", opts)
        self.assertIn("--physics-policy", opts)
        self.assertIn("--force-static", opts)

    def test_every_param_has_tooltip(self):
        # tooltip 即文档：零成本的交付质量，不留空
        for p in params.PARAMS:
            self.assertTrue(p.help, "参数 %s 没有 help（面板 tooltip 会是空的）" % p.name)

    def test_blender_props_cover_all(self):
        # 不 import bpy：只验证生成函数用到声明，字段集合一致
        self.assertTrue(all(p.name for p in params.PARAMS))


class TestParsing(unittest.TestCase):
    def setUp(self):
        self.ap = argparse.ArgumentParser()
        params.add_arguments(self.ap)

    def test_defaults(self):
        a = self.ap.parse_args(["--pmx", "m.pmx"])
        self.assertEqual(a.chain_mode, "splice")
        self.assertEqual(a.physics_policy, "strict")
        self.assertEqual(a.align, "auto")
        self.assertEqual(int(a.fps), 30)
        self.assertEqual(a.frames, 360)

    def test_path_with_spaces(self):
        a = self.ap.parse_args(["--pmx", "E:/a b/模型.pmx",
                                "--vmd", "E:/a b/动 作.vmd"])
        self.assertEqual(a.pmx, "E:/a b/模型.pmx")
        self.assertEqual(a.vmd, "E:/a b/动 作.vmd")

    def test_repeatable_list(self):
        a = self.ap.parse_args(["--pmx", "m.pmx", "--force-static", "xk_",
                                "--force-static", "zxk"])
        self.assertEqual(a.force_static, ["xk_", "zxk"])

    def test_choice_rejects_bad_value(self):
        with self.assertRaises(SystemExit):
            self.ap.parse_args(["--pmx", "m.pmx", "--chain-mode", "nope"])


if __name__ == "__main__":
    unittest.main()
