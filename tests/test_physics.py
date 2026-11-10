"""物理单元识别测试：过约束桁架必须被认出来。

这条是"袖子翻折"的病灶识别——判定器认不出，后面的修复器就无从下手。
"""
import os
import unittest

from mmdpipe import physics, pmx

KAF = (r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_"
       r"31cc0fe7cc29460474ff5e5cd7188309/星穹铁道—卡芙卡无外套/卡芙卡3.0.pmx")
XIAO = r"C:/Users/zzc/Desktop/xiaogong/宵宫.pmx"


def _has(p):
    return os.path.exists(p)


class TestUnits(unittest.TestCase):
    @unittest.skipUnless(_has(KAF), "缺少卡芙卡模型")
    def test_kafuka_sleeve_units(self):
        rep = physics.classify(pmx.load(KAF))
        sleeve = [u for u in rep.units
                  if len(u.bodies) >= 20 and u.cycle_rank >= 20 and 2 not in (u.modes or set())]
        self.assertEqual(len(sleeve), 2, "两只袖筒都应该被认成过约束单元")
        for u in sleeve:
            self.assertGreaterEqual(u.welded_ratio, 0.35)

    @unittest.skipUnless(_has(XIAO), "缺少宵宫模型")
    def test_xiaogong_parses(self):
        m = pmx.load(XIAO)
        self.assertGreater(len(m.bones), 300)
        self.assertGreater(len(m.rigids), 100)
        self.assertIsNone(m.tail_error, "PMX 尾部没对齐，解析可能错位")
        rep = physics.classify(m)
        self.assertGreater(len(rep.units), 5)

    @unittest.skipUnless(_has(KAF), "缺少卡芙卡模型")
    def test_pattern_matching(self):
        m = pmx.load(KAF)
        bones = physics.bones_by_pattern(m, ["xk_"])
        self.assertTrue(bones, "force_static 的模式匹配应该命中午子骨")
        self.assertTrue(all("xk_" in b for b in bones))

    @unittest.skipUnless(_has(KAF), "缺少卡芙卡模型")
    def test_policy_off_mutes_nothing(self):
        rep = physics.classify(pmx.load(KAF))
        self.assertEqual(physics.bones_for_policy(rep, "off"), [])


if __name__ == "__main__":
    unittest.main()
