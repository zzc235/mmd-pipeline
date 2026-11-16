# -*- coding: utf-8 -*-
"""M04 A0 判官要能回答两个问题（`D-20261116-179`）。

同一个观测在两种问题下含义**相反**：

| 问题 | 逐位相同 |
|---|---|
| 灵敏度（A vs A0：一个开碰撞一个关碰撞） | 仪器看不见碰撞状态 ⇒ 四组作废 |
| 确定性（同一场景两次独立解算） | 正好是要的结果 ⇒ 解算确定 |

第一版只有灵敏度判官，却被拿去判确定性那一对（`a0_free_determinism.json`），
于是数据对、判词反（判成 `tier=1 / UNMEASURED / 仪器看不见`）。下面两条是回归护栏：
**确定性输入必须判 `DETERMINISTIC`、不许出 `UNMEASURED`；灵敏度输入逐位相同才判「仪器看不见」。**

判官住在 `reports/subai/M04/scripts/m04_a0_control.py`（M04 的判定器，纯 Python、不开 Blender），
这里按文件路径加载，不复制实现——测的就是线上那支。
"""
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
JUDGE_PATH = os.path.join(ROOT, "reports", "subai", "M04", "scripts", "m04_a0_control.py")


def load_judge():
    spec = importlib.util.spec_from_file_location("m04_a0_control_under_test", JUDGE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def frames(rows):
    return {f: {"max_depth_m": d, "overlapping_pairs": n, "raw_depth_m": d}
            for f, d, n in rows}


SAME = [(1, -0.017, 10), (2, -0.0150, 11), (3, -0.009, 9)]
DIFFERENT = [(1, -0.020, 12), (2, -0.0150, 11), (3, -0.009, 9)]


class JudgeTwoQuestionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.j = load_judge()

    def test_determinism_identical_is_deterministic_not_unmeasured(self):
        """要求一：确定性输入（逐位相同）⇒ DETERMINISTIC，不许出 UNMEASURED。"""
        same = frames(SAME)
        tier, word, detail = self.j.judge(same, dict(same), question="determinism")
        self.assertEqual(word, "DETERMINISTIC")
        self.assertNotEqual(word, "UNMEASURED")
        self.assertIsNone(tier, "确定性问题不套三档")
        self.assertFalse(detail.get("tier_applicable"))
        self.assertIsNone(detail.get("direction_ok"), "方向判据只属于灵敏度问题")

    def test_sensitivity_identical_is_instrument_blind(self):
        """要求二：灵敏度输入逐位相同 ⇒ 才判「仪器看不见碰撞状态」。"""
        same = frames(SAME)
        tier, word, detail = self.j.judge(same, dict(same))       # 默认 sensitivity
        self.assertEqual(tier, 1)
        self.assertEqual(word, "UNMEASURED")
        self.assertIn("仪器看不见", detail["verdict"])

    def test_determinism_differing_is_not_deterministic(self):
        tier, word, detail = self.j.judge(frames(SAME), frames(DIFFERENT), question="determinism")
        self.assertEqual(word, "NOT_DETERMINISTIC")
        self.assertNotEqual(word, "UNMEASURED", "解算不确定不是「仪器看不见」")
        self.assertIsNone(tier)

    def test_sensitivity_ladder_unchanged(self):
        """三档分层不许被这次改动挪动（预注册 v4 §二）。"""
        _, _, d_same = self.j.judge(frames(SAME), frames(SAME))
        self.assertEqual(d_same["max_abs_delta_m"], 0.0)
        tier2, _, _ = self.j.judge(frames(SAME), frames([(1, -0.0174, 10), (2, -0.015, 11), (3, -0.009, 9)]))
        self.assertEqual(tier2, 2)
        tier3, _, _ = self.j.judge(frames(SAME), frames(DIFFERENT))
        self.assertEqual(tier3, 3)

    def test_unknown_question_is_rejected(self):
        with self.assertRaises(ValueError):
            self.j.judge(frames(SAME), frames(SAME), question="whatever")


class JudgeCliTest(unittest.TestCase):
    """命令行也要按 question 落地：退出码 0、JSON 里带 question 与判词。"""

    def run_cli(self, question, rows_a, rows_b, extra=()):
        with tempfile.TemporaryDirectory() as td:
            pa = os.path.join(td, "a.meta.json")
            pb = os.path.join(td, "b.meta.json")
            pj = os.path.join(td, "out.json")
            for p, rows in ((pa, rows_a), (pb, rows_b)):
                with io.open(p, "w", encoding="utf-8") as fh:
                    json.dump({"per_frame": [{"frame": f, "max_depth_m": d, "overlapping_pairs": n,
                                              "raw_depth_m": d} for f, d, n in rows]}, fh)
            proc = subprocess.run([sys.executable, JUDGE_PATH, "--a", pa, "--a0", pb,
                                   "--question", question, "--json", pj] + list(extra),
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(proc.returncode, 0,
                             proc.stdout.decode("utf-8", "replace")[-800:])
            with io.open(pj, encoding="utf-8") as fh:
                return json.load(fh)

    def test_cli_determinism_writes_deterministic(self):
        rec = self.run_cli("determinism", SAME, SAME)
        self.assertEqual(rec["question"], "determinism")
        self.assertEqual(rec["word"], "DETERMINISTIC")
        self.assertNotEqual(rec["word"], "UNMEASURED")

    def test_cli_sensitivity_identical_still_unmeasured(self):
        rec = self.run_cli("sensitivity", SAME, SAME)
        self.assertEqual(rec["question"], "sensitivity")
        self.assertEqual(rec["tier"], 1)
        self.assertEqual(rec["word"], "UNMEASURED")

    def test_cli_supersedes_records_old_file(self):
        """替代旧判词时，旧文件的哈希与旧判词必须进新文件（谁被替代、为什么）。"""
        with tempfile.TemporaryDirectory() as td:
            old = os.path.join(td, "old.json")
            with io.open(old, "w", encoding="utf-8") as fh:
                json.dump({"spec": "m04_a0_control/1", "tier": 1, "word": "UNMEASURED",
                           "detail": {"verdict": "仪器看不见碰撞状态 ⇒ 四组全部作废"}}, fh)
            pa = os.path.join(td, "a.meta.json")
            with io.open(pa, "w", encoding="utf-8") as fh:
                json.dump({"per_frame": [{"frame": f, "max_depth_m": d, "overlapping_pairs": n,
                                          "raw_depth_m": d} for f, d, n in SAME]}, fh)
            pj = os.path.join(td, "new.json")
            proc = subprocess.run([sys.executable, JUDGE_PATH, "--a", pa, "--a0", pa,
                                   "--question", "determinism", "--json", pj,
                                   "--supersedes", old],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(proc.returncode, 0, proc.stdout.decode("utf-8", "replace")[-800:])
            with io.open(pj, encoding="utf-8") as fh:
                rec = json.load(fh)
            sup = rec["supersedes"]
            self.assertEqual(sup["word"], "UNMEASURED")
            self.assertEqual(sup["tier"], 1)
            self.assertEqual(len(sup["sha256_lf_normalized"]), 64)
            self.assertIn("判官套错对象", rec["superseded_reason"])


if __name__ == "__main__":
    unittest.main()
