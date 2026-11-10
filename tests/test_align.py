"""对齐判定测试：拦住"用绝对阈值判相对关系"这类错。

这里只测纯算术与规则，世界位移的测量在 Blender 侧（见 tests_bpy/）。
"""
import unittest

from mmdpipe import align


def plan(**kw):
    p = align.AlignmentPlan(**kw)
    return align.decide(p)


class TestDecide(unittest.TestCase):
    def test_noise_is_noop(self):
        p = plan(world_delta_mm=3.0, feet_delta_mm=200.0, heading_deg=0.2)
        self.assertEqual(p.mode, align.NONE)

    def test_pose_difference_is_noop(self):
        """原神摇+活着dj：根 30.5mm 只占脚 351.5mm 的 9%，是体态不是站位。"""
        p = plan(world_delta_mm=30.5, feet_delta_mm=351.5, heading_deg=0.0)
        self.assertEqual(p.mode, align.NONE)
        self.assertIn("9%", p.reason)

    def test_real_displacement_is_match(self):
        p = plan(world_delta_mm=275.0, feet_delta_mm=469.0, heading_deg=-0.4)
        self.assertEqual(p.mode, align.MATCH)

    def test_ratio_boundary(self):
        # 比值 0.30 是分界：刚好过线判 match，线内判 none
        self.assertEqual(plan(world_delta_mm=31.0, feet_delta_mm=100.0).mode, align.MATCH)
        self.assertEqual(plan(world_delta_mm=29.0, feet_delta_mm=100.0).mode, align.NONE)

    def test_heading_alone_triggers(self):
        """朝向差本身就能构成需要对齐（哪怕位移在噪声级）。"""
        p = plan(world_delta_mm=1.0, feet_delta_mm=200.0, heading_deg=8.0)
        self.assertNotEqual(p.mode, align.NONE)

    def test_large_delta_warns_about_keep(self):
        p = plan(world_delta_mm=1202.0, feet_delta_mm=276.8, heading_deg=0.0)
        self.assertEqual(p.mode, align.MATCH)
        self.assertIn("keep", p.reason)

    def test_plan_roundtrip(self):
        p = align.AlignmentPlan(a_path="a", b_path="b", t=[1, 2, 3], mode="match")
        q = align.AlignmentPlan.from_dict(p.as_dict())
        self.assertEqual(q.t, [1, 2, 3])
        self.assertEqual(q.mode, "match")


if __name__ == "__main__":
    unittest.main()
