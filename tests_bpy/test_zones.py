"""四区面板的参数分区测试（纯 Python，不需要 Blender）。

为什么单测这个：面板唯一的职责就是"把每个旋钮放对区"。分区元数据一旦漏项，
`params.py` 在 import 阶段就会 raise（插件装不上，而不是某个旋钮静默消失）；
这里再把"每区非空、顺序稳定、高级项不丢"钉住，免得将来改分区把字段挪丢。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mmdpipe import params  # noqa: E402


class TestZones(unittest.TestCase):
    def test_every_param_has_zone(self):
        self.assertEqual(set(params.ZONE_OF), {p.name for p in params.PARAMS})
        for zone in params.ZONES:
            self.assertTrue(params.by_zone(zone), "区 %s 是空的" % zone)

    def test_zones_cover_all_params_exactly_once(self):
        collected = [p.name for zone in params.ZONES for p in params.by_zone(zone)]
        self.assertEqual(sorted(collected), sorted(p.name for p in params.PARAMS))
        self.assertEqual(len(collected), len(set(collected)), "有参数被放进两个区")

    def test_order_follows_declaration(self):
        """同一区内按 PARAMS 声明顺序 —— 面板显示顺序 = CLI 帮助顺序，好对照。"""
        declared = [p.name for p in params.PARAMS]
        for zone in params.ZONES:
            names = [p.name for p in params.by_zone(zone)]
            self.assertEqual(names, [n for n in declared if n in set(names)])

    def test_advanced_items_stay_in_their_zone(self):
        """高级项归它自己的区，不因为"高级"被挪到别的区或丢掉。"""
        advanced = [p.name for p in params.PARAMS if p.advanced]
        placed = [p.name for zone in params.ZONES for p in params.by_zone(zone) if p.advanced]
        self.assertEqual(sorted(advanced), sorted(placed))

    def test_unknown_zone_rejected(self):
        with self.assertRaises(KeyError):
            params.by_zone("nope")

    def test_key_inputs_are_where_users_look(self):
        """三个最常用的旋钮必须在资产区第一屏：模型、输出、帧数。"""
        asset = [p.name for p in params.by_zone("asset")]
        for name in ("pmx", "out", "frames"):
            self.assertIn(name, asset)
        physics = [p.name for p in params.by_zone("physics")]
        self.assertIn("physics_policy", physics)
        render = [p.name for p in params.by_zone("render")]
        self.assertIn("chain_mode", render)


if __name__ == "__main__":
    unittest.main(verbosity=2)
