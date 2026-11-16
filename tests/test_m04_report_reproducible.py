# -*- coding: utf-8 -*-
"""**报告里的数能不能只用仓库里有的东西重算出来** —— 对着 git 视角验。

触发：`3号` 20:04 往下查了一层「证据的生成链也不在仓里」，`2号`（我）被问到的同一把尺是：
`result_cd_round2.md` 的每个头条数字，是不是都能从**仓库里那份**（而不是 `out/` 批次目录里
那份、也不是我记忆里那份）重算出来？

结论是能，而且这里是机器核的：三份 `*.meta.json` 的 `per_frame` + 三份 `baseline_*.json` +
`cmp_round2.json` 都在 git 里，逐帧读数全部可从它们重算。

三条断言分野：
1. **产物在仓里**（`git ls-files`，不是 `os.path.exists` —— 后者只说明本机有）；
2. **数字对得上**（从仓里那几份重算，逐项等于报告写的）；
3. **算的确实是它**（负控：换 ε 或删几行读数，结果必须跟着变；一直给常数就说明在念台词）。
"""
import importlib.util
import io
import json
import os
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SNAP_REL = "reports/subai/M04/cd_round2"
SNAP = os.path.join(ROOT, "reports", "subai", "M04", "cd_round2")
EPS = 0.020

REQUIRED = ("C_W1.meta.json", "C_W2.meta.json", "D.meta.json",
            "baseline_C_W1.json", "baseline_C_W2.json", "baseline_D.json",
            "cmp_round2.json", "_snapshot_index.json", "manifest.json",
            "manifest_scope.json")


def git_tracked(rel):
    r = subprocess.run(["git", "ls-files", "--error-unmatch", rel],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode == 0:
        return True
    if "did not match any file" in (r.stderr or ""):
        return False
    return None


def load(name):
    with io.open(os.path.join(SNAP, name), encoding="utf-8") as fh:
        return json.load(fh)


def over_and_deepest(rows, eps=EPS, lo=None, hi=None):
    sel = [r for r in rows
           if (lo is None or r["frame"] >= lo) and (hi is None or r["frame"] <= hi)]
    over = [r for r in sel if r["max_depth_m"] < -eps]
    deep = min(sel, key=lambda r: r["max_depth_m"])
    return len(over), round(deep["max_depth_m"] * 1000.0, 3), int(deep["frame"])


class TrackedTest(unittest.TestCase):
    def test_every_quoted_artifact_is_in_git(self):
        missing = [n for n in REQUIRED if git_tracked(SNAP_REL + "/" + n) is not True]
        self.assertEqual(missing, [], "这些被报告引用的产物不在 git 里：%s" % missing)


class HeadlineNumbersTest(unittest.TestCase):
    """报告 §二 与 §三 的头条数，从仓里那几份重算。"""

    @classmethod
    def setUpClass(cls):
        cls.w1 = load("C_W1.meta.json")
        cls.w2 = load("C_W2.meta.json")
        cls.d = load("D.meta.json")

    def test_group_rows(self):
        self.assertEqual(over_and_deepest(self.w1["per_frame"]), (3, -34.219, 231))
        self.assertEqual(over_and_deepest(self.w2["per_frame"]), (48, -83.250, 304))
        self.assertEqual(over_and_deepest(self.d["per_frame"]), (309, -81.814, 287))

    def test_same_domain_comparison(self):
        """`C@W1 vs C@W2` 必须取共同帧域 1..240；跨域的 0.049031 已作废。"""
        self.assertEqual(over_and_deepest(self.w2["per_frame"], lo=1, hi=240),
                         (17, -80.417, 95))
        self.assertEqual(over_and_deepest(self.w1["per_frame"], lo=1, hi=240),
                         (3, -34.219, 231))
        self.assertEqual(round(80.417 - 34.219, 3), 46.198)

    def test_admission_fields(self):
        for doc in (self.w1, self.w2, self.d):
            self.assertEqual(doc["pairs_without_baseline"] if "pairs_without_baseline" in doc
                             else sum(r["pairs_without_baseline"] for r in doc["per_frame"]), 0)
            self.assertEqual(doc["roi_missing"], [])
            self.assertFalse(doc["cache_state"].get("is_baked"), doc.get("blend"))

    def test_frozen_baselines_cover_the_pair_universe(self):
        for name in ("baseline_C_W1.json", "baseline_C_W2.json", "baseline_D.json"):
            doc = load(name)
            self.assertEqual(doc["pairs"], 5076)
            self.assertEqual(len(doc["baseline_m"]), 5076)
            self.assertEqual(doc["pairs_with_zero_overlap"]
                             + sum(1 for v in doc["baseline_m"].values() if v > 0), 5076)


class NegativeControlTest(unittest.TestCase):
    """负控：算的必须真的是这份数据，不能给常数。"""

    @classmethod
    def setUpClass(cls):
        cls.rows = load("C_W2.meta.json")["per_frame"]

    def test_epsilon_moves_the_count(self):
        """ε 从 20 mm 收到 50 mm、再到 100 mm，计数必须跟着变（最深才 83.250 mm）。"""
        n20, _, _ = over_and_deepest(self.rows, eps=0.020)
        n50, _, _ = over_and_deepest(self.rows, eps=0.050)
        n100, _, _ = over_and_deepest(self.rows, eps=0.100)
        self.assertEqual(n20, 48)
        self.assertTrue(0 < n50 < n20, (n50, n20))
        self.assertEqual(n100, 0)

    def test_dropping_rows_moves_the_count(self):
        fewer = [r for r in self.rows if r["frame"] != 304]
        self.assertEqual(over_and_deepest(fewer)[2], 347)  # 次深帧接管
        self.assertNotEqual(over_and_deepest(fewer)[0], over_and_deepest(self.rows)[0])

    def test_shorter_domain_changes_the_deepest_frame(self):
        """跨域与同域的最深帧不同（f304 vs f95）——这正是 19:30 那处错的形状。"""
        self.assertEqual(over_and_deepest(self.rows)[2], 304)
        self.assertEqual(over_and_deepest(self.rows, lo=1, hi=240)[2], 95)


if __name__ == "__main__":
    unittest.main()
