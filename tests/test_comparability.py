# -*- coding: utf-8 -*-
"""可比性闸门（`coordination/comparability.py`）的回归。

2026-11-16 一晚同一形状错四次，每次都由**人**抓到、没有一次自查出来。这组测试就是
把那几次错各做成一条**必红**的负控，外加「拿它当靶子」的对抗清单：

| 出处 | 错的形状 | 对齐的负控 |
|---|---|---|
| `2号` `0.049031` | 两个不同帧域的 max 相减 | `DomainExtremaTest.test_two_scalars_rejected` + 签名只收一份帧域 |
| `2号` 方向 | 「更负」当「更浅」 | `DomainExtremaTest.test_deeper_is_lower_flag` |
| `2号` 瞬态当整段 | 50 帧极值冒充 531 帧属性 | `ExtremumReportTest.test_spike_is_transient` |
| `4号` 窗外帧号 | `355..832` 引用 `f353` | `ExtremumReportTest.test_frame_outside_domain_rejected` |
| `4号` 切点敏感度 | 「稳健」由作者嘴说 | `CutSensitivityTest` |
| `2号` 比例下限 | 比例把结论切翻（5%） | `WindowCutTest.test_segment_ratio_with_unstable_stability_refused` |

运行：`python -m unittest discover -s tests -t tests -p 'test_*.py'`
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from coordination import comparability as C  # noqa: E402


def series(lo, hi, value=-0.0015, overrides=None):
    """造一份逐帧数组；`overrides` 是 `{帧号: 值}`。"""
    overrides = overrides or {}
    return [{"frame": f, "max_depth_m": overrides.get(f, value)} for f in range(lo, hi + 1)]


def side(**kw):
    """一份满六条的可比性声明；`kw` 覆盖个别字段。"""
    base = {
        "frame_domain": [1, 240],
        "baseline": "per_arm_first_frame:79862401ed1f",
        "pair_universe": "roi_candidate_5076",
        "scale": "u323",
        "segment_label": "动画段 1..301",
        "window_rule": "preregistered",
    }
    base.update(kw)
    return base


class CheckSidesTest(unittest.TestCase):
    """六条并列：缺一条、或两边不等，都不许比。"""

    def test_positive_both_sides_complete(self):
        got = C.check_sides(side(), side())
        self.assertEqual(got["state"], "OK", got.get("problems"))
        self.assertEqual(got["shared"]["frame_domain"], [1, 240])

    def test_missing_field_names_the_field(self):
        a = side()
        del a["baseline"]
        got = C.check_sides(a, side())
        self.assertEqual(got["state"], "INCOMPARABLE")
        self.assertIn({"field": "baseline", "side": "a", "why": "missing"}, got["problems"])

    def test_sides_differ_on_frame_domain(self):
        got = C.check_sides(side(frame_domain=[1, 240]), side(frame_domain=[1, 832]))
        self.assertEqual(got["state"], "INCOMPARABLE")
        self.assertTrue(any(p.get("why") == "sides_differ" and p.get("field") == "frame_domain"
                            for p in got["problems"]))

    def test_scale_differs_without_annotation_is_refused(self):
        got = C.check_sides(side(scale="u312"), side(scale="u323"))
        self.assertEqual(got["state"], "INCOMPARABLE")
        self.assertTrue(any(p.get("why") == "scale_differs_not_annotated"
                            for p in got["problems"]))

    def test_scale_differs_with_annotation_passes_and_says_so(self):
        a = side(scale="u312")
        a["scale_annotated"] = True
        b = side(scale="u323")
        b["scale_annotated"] = True
        got = C.check_sides(a, b)
        self.assertEqual(got["state"], "OK", got.get("problems"))
        self.assertEqual(got["shared"]["scale"], "differs(annotated)")

    def test_post_hoc_window_used_as_criterion_is_refused(self):
        a = side(window_rule="post_hoc")
        a["as_criterion"] = True
        got = C.check_sides(a, side(window_rule="post_hoc"))
        self.assertEqual(got["state"], "INCOMPARABLE")
        self.assertTrue(any(p.get("why") == "post_hoc_window_not_criterion"
                            for p in got["problems"]))

    def test_post_hoc_as_explanation_only_passes(self):
        got = C.check_sides(side(window_rule="post_hoc"), side(window_rule="post_hoc"))
        self.assertEqual(got["state"], "OK", got.get("problems"))

    def test_unknown_window_rule_refused(self):
        got = C.check_sides(side(window_rule="看着切的"), side(window_rule="看着切的"))
        self.assertEqual(got["state"], "INCOMPARABLE")
        self.assertTrue(any(p.get("why") == "not_in_closed_set" for p in got["problems"]))

    def test_check_record_requires_both_sides(self):
        with self.assertRaises(C.ComparabilityError):
            C.check_record({"a": side()})


class DomainExtremaTest(unittest.TestCase):
    """同域差由闸门自己算 —— `2号` 那个 `0.049031` 在签名层就写不出来。"""

    def test_positive_same_domain_delta(self):
        a = series(1, 240, overrides={231: -0.034219})
        b = series(1, 240, overrides={95: -0.080417})
        got = C.domain_extrema(a, b, 1, 240)
        self.assertEqual(got["state"], "OK", got.get("problems"))
        self.assertEqual(got["a"]["worst_frame"], 231)
        self.assertEqual(got["b"]["worst_frame"], 95)
        self.assertAlmostEqual(got["delta"], 0.046198, places=9)

    def test_two_scalars_rejected(self):
        """`0.049031` 的调用方式：两个标量相减。"""
        for bad in (-0.083250, 0.0, None):
            with self.assertRaises(C.ComparabilityError):
                C.domain_extrema(bad, series(1, 240), 1, 240)

    def test_missing_frames_refused(self):
        a = [r for r in series(1, 240) if r["frame"] != 100]
        got = C.domain_extrema(a, series(1, 240), 1, 240)
        self.assertEqual(got["state"], "INCOMPARABLE")
        self.assertTrue(any(p.get("why") == "missing_frames" for p in got["problems"]))

    def test_data_beyond_domain_is_recorded_not_fatal(self):
        """全域数据 + 窄域比较：只用窄域算极值，越界的帧记一笔。"""
        a = series(1, 240, overrides={231: -0.034219})
        b = series(1, 832, overrides={95: -0.080417, 304: -0.083250})
        got = C.domain_extrema(a, b, 1, 240)
        self.assertEqual(got["state"], "OK", got.get("problems"))
        # 关键：全域极值 f304 不许漏进同域比较
        self.assertEqual(got["b"]["worst_frame"], 95)
        self.assertEqual(got["data_extends_beyond_domain"], {"b": 592})

    def test_deeper_is_lower_flag(self):
        """越负越深（默认）；反过来要显式说，别靠读的人猜。"""
        a = series(1, 10, overrides={3: -0.5})
        b = series(1, 10, overrides={7: -0.1})
        self.assertEqual(C.domain_extrema(a, b, 1, 10)["a"]["worst_frame"], 3)
        flipped = C.domain_extrema(a, b, 1, 10, deeper_is_lower=False)
        self.assertEqual(flipped["a"]["worst_frame"], 1)

    def test_bad_domain_refused(self):
        for bad in ([1], [5, 1], ("1", 240), {"lo": 1}):
            with self.assertRaises(C.ComparabilityError):
                C.domain_extrema(series(1, 240), series(1, 240), bad)


class ExtremumReportTest(unittest.TestCase):
    """极值三件套 + 判词：尖峰不许当整段属性。"""

    def test_spike_is_transient(self):
        """`2号` 的 `f304`：±12 帧内只有它自己达到半量级。"""
        data = series(302, 832, overrides={304: -0.083250})
        got = C.extremum_report(data, 304)
        self.assertEqual(got["label"], C.TRANSIENT)
        self.assertFalse(got["usable_as_segment_property"])
        self.assertEqual(got["peers_at_half_magnitude"], 0)

    def test_plateau_is_usable(self):
        data = series(302, 832, overrides={f: -0.08 for f in range(600, 610)})
        got = C.extremum_report(data, 605)
        self.assertEqual(got["label"], C.PLATEAU)
        self.assertTrue(got["usable_as_segment_property"])

    def test_frame_outside_domain_rejected(self):
        """`4号` 的错：`355..832` 的句子里引用 `f353`。"""
        data = series(355, 832)
        with self.assertRaises(C.ComparabilityError):
            C.extremum_report(data, 353)

    def test_bad_window_rule_rejected(self):
        with self.assertRaises(C.ComparabilityError):
            C.extremum_report(series(1, 10), 5, window_rule="瞎写")

    def test_report_carries_all_four(self):
        got = C.extremum_report(series(1, 100, overrides={50: -0.05}), 50)
        for key in ("frame", "max_depth_m", "peers_at_half_magnitude", "window_rule"):
            self.assertIn(key, got)


class WindowCutTest(unittest.TestCase):
    """窗口规则必须「先于数据可判」，且比例本身要带敏感度。"""

    def test_segment_ratio_needs_stability_to_be_a_criterion(self):
        got = C.window_cut(302, 832, "segment_ratio", ratio=0.10)
        self.assertEqual(got["window"], [302, 354])
        self.assertEqual(got["rest"], [355, 832])
        self.assertFalse(got["usable_as_criterion"],
                         "没带敏感度的比例规则不许当判据 —— 5% 就把结论切翻了")
        self.assertIn("cut_sensitivity", got["note"])

    def test_segment_ratio_with_stable_stability_passes(self):
        data = series(302, 832, overrides={304: -0.09, 646: -0.05})
        cuts = C.ratio_cuts(302, 832, [0.10, 0.15, 0.20])
        stab = C.cut_sensitivity(data, cuts, 302, segment_end=832)
        self.assertTrue(stab["worst_frame_stable"], stab["worst_frames_by_side"])
        got = C.window_cut(302, 832, "segment_ratio", ratio=0.10, stability=stab)
        self.assertTrue(got["usable_as_criterion"])
        self.assertTrue(got["ratio_floor_checked"])

    def test_segment_ratio_with_unstable_stability_refused(self):
        """`2号` 量到的下限：5% 时 rest 的极值帧落回交接附近。"""
        data = series(302, 832, overrides={304: -0.09, 347: -0.08129, 646: -0.0656})
        cuts = C.ratio_cuts(302, 832, [0.05, 0.10])
        stab = C.cut_sensitivity(data, cuts, 302, segment_end=832)
        self.assertFalse(stab["worst_frame_stable"], stab["rows"])
        got = C.window_cut(302, 832, "segment_ratio", ratio=0.05, stability=stab)
        self.assertFalse(got["usable_as_criterion"])
        self.assertIn("切翻", got["note"])

    def test_ratio_cuts_mapping(self):
        self.assertEqual(C.ratio_cuts(302, 832, [0.05, 0.10, 0.20]), [328, 354, 407])

    def test_ratio_cuts_bad_ratio(self):
        for bad in (0, 1, -0.1):
            with self.assertRaises(C.ComparabilityError):
                C.ratio_cuts(302, 832, [bad])

    def test_preregistered_needs_explicit_cut(self):
        with self.assertRaises(C.ComparabilityError):
            C.window_cut(302, 832, "preregistered")

    def test_post_hoc_is_explanation_only(self):
        got = C.window_cut(302, 832, "post_hoc", cut=351, note="看着极端值挤在这儿")
        self.assertFalse(got["usable_as_criterion"])
        self.assertEqual(got["window"], [302, 351])

    def test_ratio_out_of_range(self):
        for bad in (0, 1, -0.1, 1.5):
            with self.assertRaises(C.ComparabilityError):
                C.window_cut(302, 832, "segment_ratio", ratio=bad)

    def test_cut_must_be_inside_segment(self):
        with self.assertRaises(C.ComparabilityError):
            C.window_cut(302, 832, "preregistered", cut=832)


class CutSensitivityTest(unittest.TestCase):
    """`4号` 的建议：稳健不稳健要由函数算，不由作者嘴说；而且**两段都要算**。"""

    def _cw2_like(self):
        """按 `C@W2` 保持段的真实结构造：prefix 极值恒为 f304，越判据帧数浮动。"""
        over = {304: -0.083250, 307: -0.041,                       # 302..315 -> 2
                317: -0.043, 325: -0.045,                           # 316..330 -> 4
                338: -0.030, 340: -0.031, 342: -0.032, 344: -0.0688,
                346: -0.0618, 347: -0.0813, 350: -0.034, 351: -0.035,
                349: -0.036, 345: -0.037, 343: -0.038,              # ..351 -> 15
                360: -0.039, 362: -0.040}                           # ..364 -> 17
        return series(302, 832, overrides=over)

    def test_conclusion_stable_number_unstable(self):
        """只看 prefix：极值帧恒为 f304，越判据帧数 2 / 4 / 15 / 17 浮动。"""
        got = C.cut_sensitivity(self._cw2_like(), [315, 330, 351, 364], 302)
        self.assertEqual(got["worst_frames"], [304])
        self.assertTrue(got["worst_frame_stable"])
        self.assertFalse(got["over_eps_stable"])
        self.assertEqual(got["over_eps_range"], [2, 17])
        self.assertEqual(got["verdict"], "CONCLUSION_STABLE_NUMBER_UNSTABLE")

    def test_prefix_only_when_no_segment_end(self):
        got = C.cut_sensitivity(self._cw2_like(), [315, 330], 302)
        self.assertEqual(got["sides"], ["prefix"])
        self.assertEqual(got["worst_frames"], [304])

    def test_stable_when_both_invariant(self):
        data = series(302, 800, overrides={304: -0.09, 646: -0.06})
        got = C.cut_sensitivity(data, [354, 381, 407], 302, segment_end=800)
        self.assertEqual(got["verdict"], "STABLE", got["rows"])

    def test_unstable_when_worst_frame_moves(self):
        """对照：极值帧随切点变 ⇒ 这条结论本身不能用事后切点。"""
        data = series(100, 200, overrides={150: -0.090, 170: -0.095})
        got = C.cut_sensitivity(data, [160, 200], 100)
        self.assertFalse(got["worst_frame_stable"])
        self.assertEqual(got["verdict"], "UNSTABLE")

    def test_rest_side_flip_is_caught(self):
        """`2号` 量到的下限：prefix 看着稳，翻的是 rest。"""
        data = series(302, 832, overrides={304: -0.09, 347: -0.08129, 646: -0.0656})
        got = C.cut_sensitivity(data, C.ratio_cuts(302, 832, [0.05, 0.10]), 302, segment_end=832)
        self.assertFalse(got["worst_frame_stable"], got["worst_frames_by_side"])
        self.assertEqual(got["worst_frames_by_side"]["prefix"], [304, 304])
        self.assertEqual(got["worst_frames_by_side"]["rest"], [347, 646])

    def test_cut_before_segment_start_refused(self):
        with self.assertRaises(C.ComparabilityError):
            C.cut_sensitivity(series(302, 400), [300], 302)

    def test_cut_not_before_segment_end_refused(self):
        with self.assertRaises(C.ComparabilityError):
            C.cut_sensitivity(series(302, 400), [400], 302, segment_end=400)


class CliTest(unittest.TestCase):
    """`python -m coordination.comparability --check <json>`：0 过 / 3 不可比 / 2 用法错。"""

    def _run(self, payload):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
            path = fh.name
        try:
            proc = subprocess.run([sys.executable, "-m", "coordination.comparability",
                                   "--check", path],
                                  cwd=ROOT, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace")
        finally:
            os.unlink(path)
        return proc

    def test_exit_0_when_comparable(self):
        proc = self._run({"a": side(), "b": side()})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["state"], "OK")

    def test_exit_3_when_incomparable(self):
        proc = self._run({"a": side(frame_domain=[1, 240]), "b": side(frame_domain=[1, 832])})
        self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["state"], "INCOMPARABLE")

    def test_exit_2_on_usage_error(self):
        proc = self._run({"a": side()})
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
