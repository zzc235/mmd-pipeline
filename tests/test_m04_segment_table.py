# -*- coding: utf-8 -*-
"""分段读数生成器（`m04_segment_table.py`）的测试 —— 重点在**拒算**那一侧。

触发点：19:30 那版报告里「交接瞬态 302..351」是事后看着极端值切的，`4号` 换了七个切点
验「结论稳、只有 15 这个数不稳」；他 §二 给的替代切分里又把稳态窗口 `355..832` 的最深
写成 `−69.097 @f353` —— 而 f353 不在 `355..832` 里。所以这里把三件事钉死：

1. 窗口边界只由 `hold_from` + 比例导出，重新算一次就是同一条边界；
2. 相邻窗口必须**恰好铺满**，漏一帧、重一帧都拒算（两条负控）；
3. 真读数上算出来的四行必须与报告逐项同值（防手抄漂移）。
"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODULE = os.path.join(ROOT, "reports", "subai", "M04", "scripts", "m04_segment_table.py")
SNAPSHOT = os.path.join(ROOT, "reports", "subai", "M04", "cd_round2", "C_W2.meta.json")


def load_module():
    spec = importlib.util.spec_from_file_location("m04_segment_table_uut", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SEG = load_module()


def synthetic(values, first_frame=1):
    """按给定深度序列造读数（米），帧号从 first_frame 起。"""
    return [{"frame": first_frame + i, "max_depth_m": v} for i, v in enumerate(values)]


class WindowStatsTest(unittest.TestCase):
    def test_counts_only_strictly_over_eps(self):
        # 恰好等于 −ε 不算越界（判据是严格小于 −ε）
        rows = synthetic([0.0, -0.020, -0.0201, -0.05])
        w = SEG.window_stats(rows, 1, 4, eps=0.020)
        self.assertEqual(w["over_eps"], 2)
        self.assertEqual(w["deepest_mm"], -50.0)
        self.assertEqual(w["deepest_frame"], 4)

    def test_window_must_be_covered_by_readings(self):
        rows = synthetic([0.0] * 10)
        with self.assertRaises(ValueError):
            SEG.window_stats(rows, 1, 11, eps=0.020)

    def test_empty_window_refused(self):
        rows = synthetic([0.0] * 10)
        with self.assertRaises(ValueError):
            SEG.window_stats(rows, 20, 30, eps=0.020)


class TransitionLengthTest(unittest.TestCase):
    def test_ratio_rounds_to_frames(self):
        self.assertEqual(SEG.transition_length(531, 0.10), 53)
        self.assertEqual(SEG.transition_length(531, 0.50), 266)

    def test_degenerate_ratios_refused(self):
        for bad in (0.0, -0.1, 1.0, 1.5):
            with self.assertRaises(ValueError):
                SEG.transition_length(531, bad)

    def test_ratio_too_small_for_the_segment_refused(self):
        with self.assertRaises(ValueError):
            SEG.transition_length(5, 0.01)


class PartitionTest(unittest.TestCase):
    def test_partition_must_be_contiguous(self):
        parts = [{"window": [1, 10]}, {"window": [11, 20]}]
        self.assertTrue(SEG.assert_partition(parts, 1, 20))

    def test_gap_is_refused(self):
        """负控：漏掉第 11 帧 —— 正是「稳态窗口从 355 起、最深却在 f353」那种形状。"""
        parts = [{"window": [1, 10]}, {"window": [12, 20]}]
        with self.assertRaises(ValueError):
            SEG.assert_partition(parts, 1, 20)

    def test_overlap_is_refused(self):
        """负控：第 10 帧被两个窗口同时算进去。"""
        parts = [{"window": [1, 10]}, {"window": [10, 20]}]
        with self.assertRaises(ValueError):
            SEG.assert_partition(parts, 1, 20)

    def test_short_partition_is_refused(self):
        parts = [{"window": [1, 10]}]
        with self.assertRaises(ValueError):
            SEG.assert_partition(parts, 1, 20)


class RealSnapshotTest(unittest.TestCase):
    """真读数：四行必须与报告 §六 逐项同值。数据变了这里先红。"""

    @classmethod
    def setUpClass(cls):
        cls.rows = SEG.load_frames(SNAPSHOT)
        cls.block = SEG.build_rows(cls.rows, 302, 0.10, 0.020)

    def test_boundaries_come_from_the_rule(self):
        rule = self.block["rule"]
        # 默认是 post_hoc：危险的默认值往保守那边放（`D-224` 裁定这条窗口只能作解释）
        self.assertEqual(rule["rule_kind"], "post_hoc")
        self.assertEqual(rule["hold_frames"], 531)
        self.assertEqual(rule["transition_frames"], 53)
        self.assertEqual(self.block["transition"]["window"], [302, 354])
        self.assertEqual(self.block["steady"]["window"], [355, 832])

    def test_anim_and_hold_rows(self):
        self.assertEqual(self.block["anim"]["frames"], 301)
        self.assertEqual(self.block["anim"]["over_eps"], 20)
        self.assertEqual((self.block["anim"]["deepest_mm"],
                          self.block["anim"]["deepest_frame"]), (-80.417, 95))
        self.assertEqual(self.block["hold"]["frames"], 531)
        self.assertEqual(self.block["hold"]["over_eps"], 28)
        self.assertEqual((self.block["hold"]["deepest_mm"],
                          self.block["hold"]["deepest_frame"]), (-83.250, 304))

    def test_transition_and_steady_rows(self):
        self.assertEqual(self.block["transition"]["over_eps"], 17)
        self.assertEqual(self.block["transition"]["mean_mm"], -17.316)
        self.assertEqual(self.block["transition"]["sd_mm"], 24.057)
        self.assertEqual((self.block["transition"]["deepest_mm"],
                          self.block["transition"]["deepest_frame"]), (-83.250, 304))
        self.assertEqual(self.block["steady"]["over_eps"], 11)
        self.assertEqual(self.block["steady"]["mean_mm"], -2.701)
        self.assertEqual((self.block["steady"]["deepest_mm"],
                          self.block["steady"]["deepest_frame"]), (-65.647, 646))

    def test_partition_adds_up_to_the_hold(self):
        self.assertEqual(self.block["transition"]["over_eps"]
                         + self.block["steady"]["over_eps"],
                         self.block["hold"]["over_eps"])
        self.assertEqual(self.block["transition"]["frames"]
                         + self.block["steady"]["frames"],
                         self.block["hold"]["frames"])

    def test_deepest_frame_of_steady_is_inside_steady(self):
        """`4号` 那处错就是这一条不成立：f353 不在 355..832 里。"""
        a, b = self.block["steady"]["window"]
        self.assertTrue(a <= self.block["steady"]["deepest_frame"] <= b)

    def test_sensitivity_pins_where_robustness_stops(self):
        """5% 时稳态最深仍是 −81.290 @f347 ⇒「极端值全在交接」要比例 ≥10% 才成立。"""
        sens = {round(s["ratio"], 2): s
                for s in SEG.sensitivity(self.rows, 302, [0.05, 0.10])}
        self.assertEqual(sens[0.05]["transition_window"], [302, 328])
        self.assertEqual(sens[0.05]["transition_over"], 4)
        self.assertEqual((sens[0.05]["steady_deepest_mm"],
                          sens[0.05]["steady_deepest_frame"]), (-81.290, 347))
        self.assertEqual(sens[0.10]["steady_over"], 11)
        self.assertEqual(sens[0.10]["steady_deepest_mm"], -65.647)


class BoundaryFrameTest(unittest.TestCase):
    """边界不是「比例」定的，是**哪几帧进了瞬态窗口**定的（`4号` 19:38 的两级台阶）。"""

    @classmethod
    def setUpClass(cls):
        cls.rows = SEG.load_frames(SNAPSHOT)

    def test_frame_needs_enough_frames_to_be_covered(self):
        b = SEG.boundary_frames(self.rows, 302, [347, 353], 0.020)
        self.assertEqual([x["frames_needed"] for x in b], [46, 52])
        self.assertAlmostEqual(b[0]["hold_fraction"], 46 / 531.0, places=6)
        # round(531*r) >= 46  <=>  r >= 45.5/531
        self.assertAlmostEqual(b[0]["round_threshold"], 45.5 / 531.0, places=6)
        self.assertAlmostEqual(b[1]["round_threshold"], 51.5 / 531.0, places=6)

    def test_coverage_flag_follows_the_window(self):
        b = {x["frame"]: x for x in
             SEG.boundary_frames(self.rows, 302, [347, 353], 0.020, ratio=0.09)}
        self.assertTrue(b[347]["covered_at_ratio"])   # round(531*0.09)=48 >= 46
        self.assertFalse(b[353]["covered_at_ratio"])  # 48 < 52
        b = {x["frame"]: x for x in
             SEG.boundary_frames(self.rows, 302, [347, 353], 0.020, ratio=0.10)}
        self.assertTrue(b[353]["covered_at_ratio"])

    def test_smallest_covering_ratio_is_driven_by_the_farthest_frame(self):
        b = SEG.boundary_frames(self.rows, 302, [347, 353], 0.020)
        need = SEG.smallest_covering_ratio(b, 531)
        self.assertEqual(need["frames_needed"], 52)          # f353 说了算
        self.assertAlmostEqual(need["round_threshold"], 51.5 / 531.0, places=6)
        self.assertLess(need["round_threshold"], 0.10)       # 10% 是安全余量
        self.assertGreater(need["round_threshold"], 0.09)    # 但 9% 不够

    def test_frame_outside_the_hold_is_refused(self):
        """负控：f900 不在保持段内，拒算而不是静默返回。"""
        with self.assertRaises(ValueError):
            SEG.boundary_frames(self.rows, 302, [900], 0.020)

    def test_two_step_shape_is_pinned(self):
        """8% → 稳态 −81.290@f347；9% → −69.097@f353；10% → −65.647@f646。"""
        sens = {round(s["ratio"], 2): s
                for s in SEG.sensitivity(self.rows, 302, [0.08, 0.09, 0.10], 0.020,
                                         boundary=[347, 353])}
        expect = {0.08: (-81.290, 347), 0.09: (-69.097, 353), 0.10: (-65.647, 646)}
        for ratio, (value, frame) in expect.items():
            self.assertEqual((sens[ratio]["steady_deepest_mm"],
                              sens[ratio]["steady_deepest_frame"]), (value, frame))
        self.assertEqual(sens[0.08]["covers"], {"347": False, "353": False})
        self.assertEqual(sens[0.09]["covers"], {"347": True, "353": False})
        self.assertEqual(sens[0.10]["covers"], {"347": True, "353": True})


class RuleKindTest(unittest.TestCase):
    """`D-224`：这条窗口是 `post_hoc` —— 默认值就得是它，还得挡非法值。"""

    @classmethod
    def setUpClass(cls):
        cls.rows = SEG.load_frames(SNAPSHOT)

    def test_rule_kind_must_be_from_the_closed_set(self):
        self.assertEqual(SEG._window_rules(),
                         ("preregistered", "segment_ratio", "post_hoc"))

    def test_explicit_preregistered_is_carried_through(self):
        block = SEG.build_rows(self.rows, 302, 0.10, rule_kind="preregistered")
        self.assertEqual(block["rule"]["rule_kind"], "preregistered")

    def test_cli_refuses_unknown_rule_kind(self):
        code = SEG.main(["--meta", SNAPSHOT, "--hold-from", "302",
                         "--ratio", "0.10", "--rule-kind", "looks_fine"])
        self.assertEqual(code, 2)


class DelegatedStabilityTest(unittest.TestCase):
    """「对切点稳健」这句话由 `coordination.comparability` 算，不由本脚本嘴说。"""

    @classmethod
    def setUpClass(cls):
        cls.rows = SEG.load_frames(SNAPSHOT)
        cls.block = SEG.build_rows(cls.rows, 302, 0.10)
        cls.sens = SEG.sensitivity(cls.rows, 302, [0.08, 0.09, 0.10])

    def test_delegation_works_from_a_script_dir_on_sys_path(self):
        """`python path/to/script.py` 时 `sys.path[0]` 是脚本目录，不能沉默地没接上。"""
        out = SEG._delegated_stability(self.rows, self.block["rule"], self.sens, 0.020)
        self.assertIsNotNone(out)
        self.assertEqual(out["sides"], ["prefix", "rest"])

    def test_verdict_is_unstable_and_says_which_frames_move(self):
        out = SEG._delegated_stability(self.rows, self.block["rule"], self.sens, 0.020)
        self.assertEqual(out["verdict"], "UNSTABLE")
        self.assertEqual(out["worst_frames"], [304, 347, 353, 646])
        self.assertFalse(out["worst_frame_stable"])
        # prefix 恒为 f304、动的是 rest —— 这正是只看 prefix 会漏掉的那种
        self.assertEqual(out["worst_frames_by_side"]["prefix"], [304, 304, 304])
        self.assertEqual(out["worst_frames_by_side"]["rest"], [347, 353, 646])


class RootGuardTest(unittest.TestCase):
    """先验根、再 import（`3号` 的写法）：根算错必须**喊出来并打印它算的根**，不许静默降级。"""

    def test_real_root_passes(self):
        root = SEG._ensure_repo_root_on_path()
        self.assertTrue(os.path.isdir(os.path.join(root, "coordination")))

    def test_bogus_root_exits_and_names_itself(self):
        """负控：把根指到一个没有 coordination/ 的目录 ⇒ SystemExit，消息里带那个根。

        注意消息用 `%r` ⇒ 反斜杠被转义，所以比的是路径的**末段**，不是原串
        （这条是负控自己抓出来的：第一版 `assertIn(bogus, …)` 恒假）。
        """
        bogus = os.path.join(ROOT, "tests")
        with self.assertRaises(SystemExit) as ctx:
            SEG._check_root(bogus)
        self.assertIn("ROOT 算错了", str(ctx.exception))
        self.assertIn("tests", str(ctx.exception))
        self.assertIn("coordination", str(ctx.exception))

    def test_missing_mmdpipe_also_exits(self):
        """负控：只有 coordination/ 没有 mmdpipe/ 也得拒（两个都要验）。"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "coordination"))
            with self.assertRaises(SystemExit):
                SEG._check_root(tmp)

    def test_system_exit_is_not_swallowed_by_delegation_fallback(self):
        """`SystemExit` 不是 `Exception` ⇒ `_delegated_stability` 的兜底兜不住它。"""
        self.assertFalse(issubclass(SystemExit, Exception))


class MainTest(unittest.TestCase):
    def test_cli_prints_rows_and_exits_zero(self):
        code = SEG.main(["--meta", SNAPSHOT, "--hold-from", "302", "--ratio", "0.10"])
        self.assertEqual(code, 0)

    def test_cli_refuses_degenerate_ratio_with_exit_2(self):
        """拒算要**说清是哪一档**：`REFUSED:` 恰好一行，且不是早期崩溃（`3号` 20:29 的判据）。"""
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = SEG.main(["--meta", SNAPSHOT, "--hold-from", "302", "--ratio", "1.0"])
        self.assertEqual(code, 2)
        text = err.getvalue()
        self.assertEqual(text.count("REFUSED:"), 1, text)
        self.assertNotIn("Traceback", text)

    def test_cli_refuses_hold_from_outside_the_readings(self):
        code = SEG.main(["--meta", SNAPSHOT, "--hold-from", "900", "--ratio", "0.10"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
