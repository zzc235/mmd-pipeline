"""`mmdpipe.cache_state` 的判据测试：七态 + 行为证据优先 + fail closed + 批量最坏码。

核心一条：`is_baked && is_outdated` **不是**缺陷证据（真烘焙件重开后也长这样，P13 实测），
所以只凭标志位只能判 `SUSPECT`(4)；要判 `DEFECT`(3) 必须有行为探针的不一致证据。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from mmdpipe import cache_state


def behavior(dist, frame=109, tol=None):
    rec = {"cold_jump_frame": frame, "cold_jump_vs_recompute_m": dist}
    if tol is not None:
        rec["tolerance_m"] = tol
    return rec


class TestClassify(unittest.TestCase):
    def test_unbaked_is_ok(self):
        self.assertEqual(cache_state.classify(has_physics=True, is_baked=False, is_outdated=None),
                         cache_state.OK_UNBAKED)
        self.assertEqual(cache_state.exit_code(cache_state.OK_UNBAKED), 0)

    def test_baked_consistent_is_ok(self):
        v = cache_state.classify(has_physics=True, is_baked=True, is_outdated=False)
        self.assertEqual(v, cache_state.OK_BAKED_CONSISTENT)
        self.assertEqual(cache_state.exit_code(v), 0)

    def test_baked_outdated_flags_only_is_suspect_not_defect(self):
        """旗标无法定性：真烘焙件重开后也是 true && true（P13）。只能判「未验证」。"""
        v = cache_state.classify(has_physics=True, is_baked=True, is_outdated=True)
        self.assertEqual(v, cache_state.SUSPECT_BAKED_OUTDATED)
        self.assertEqual(cache_state.exit_code(v), 4)

    def test_baked_outdated_with_matching_behavior_is_verified(self):
        v = cache_state.classify(has_physics=True, is_baked=True, is_outdated=True,
                                 behavior=behavior(0.0))
        self.assertEqual(v, cache_state.OK_BAKED_VERIFIED)
        self.assertEqual(cache_state.exit_code(v), 0)

    def test_baked_outdated_with_mismatching_behavior_is_defect(self):
        v = cache_state.classify(has_physics=True, is_baked=True, is_outdated=True,
                                 behavior=behavior(0.9087))
        self.assertEqual(v, cache_state.DEFECT_BAKED_OUTDATED)
        self.assertEqual(cache_state.exit_code(v), 3)

    def test_behavior_overrides_flags_both_ways(self):
        """量到的比声明的可信：旗标说一致、行为说不一致 → 判缺陷。"""
        v = cache_state.classify(has_physics=True, is_baked=True, is_outdated=False,
                                 behavior=behavior(0.9087))
        self.assertEqual(v, cache_state.DEFECT_BAKED_OUTDATED)
        v = cache_state.classify(has_physics=True, is_baked=True, is_outdated=False,
                                 behavior=behavior(0.0))
        self.assertEqual(v, cache_state.OK_BAKED_VERIFIED)

    def test_tolerance_is_honoured(self):
        near = behavior(0.0004, tol=0.001)
        far = behavior(0.002, tol=0.001)
        self.assertEqual(cache_state.classify(has_physics=True, is_baked=True, is_outdated=True,
                                              behavior=near), cache_state.OK_BAKED_VERIFIED)
        self.assertEqual(cache_state.classify(has_physics=True, is_baked=True, is_outdated=True,
                                              behavior=far), cache_state.DEFECT_BAKED_OUTDATED)

    def test_default_tolerance_is_bitwise(self):
        """默认容差 1e-6：这条判据上「冷跳 == 顺序重算」是逐位相等（P13 两次都是 0）。"""
        self.assertEqual(cache_state.DEFAULT_TOLERANCE_M, 1e-6)
        self.assertEqual(cache_state.classify(has_physics=True, is_baked=True, is_outdated=True,
                                              behavior=behavior(0.001)),
                         cache_state.DEFECT_BAKED_OUTDATED)

    def test_bad_behavior_rejected(self):
        for bad in ({"cold_jump_frame": 109},                     # 缺距离
                    {"cold_jump_frame": "109", "cold_jump_vs_recompute_m": 0.0},
                    {"cold_jump_frame": 109, "cold_jump_vs_recompute_m": "0"},
                    {"cold_jump_frame": 109, "cold_jump_vs_recompute_m": -1.0},
                    {"cold_jump_frame": 109, "cold_jump_vs_recompute_m": 0.0, "tolerance_m": -1},
                    "behavior"):
            with self.subTest(behavior=bad):
                with self.assertRaises(cache_state.CacheStateError):
                    cache_state.classify(has_physics=True, is_baked=True, is_outdated=True,
                                         behavior=bad)

    def test_no_physics_is_ok(self):
        v = cache_state.classify(has_physics=False, is_baked=None, is_outdated=None)
        self.assertEqual(v, cache_state.OK_NO_PHYSICS)
        self.assertEqual(cache_state.exit_code(v), 0)

    def test_unbaked_ignores_is_outdated(self):
        """未烘焙时 is_outdated 没有意义，三种取值都必须判 OK。"""
        for outdated in (True, False, None):
            self.assertEqual(
                cache_state.classify(has_physics=True, is_baked=False, is_outdated=outdated),
                cache_state.OK_UNBAKED)

    def test_missing_is_baked_rejected(self):
        with self.assertRaises(cache_state.CacheStateError):
            cache_state.classify(has_physics=True, is_baked=None, is_outdated=False)

    def test_missing_is_outdated_when_baked_rejected(self):
        with self.assertRaises(cache_state.CacheStateError):
            cache_state.classify(has_physics=True, is_baked=True, is_outdated=None)

    def test_unknown_verdict_rejected(self):
        with self.assertRaises(cache_state.CacheStateError):
            cache_state.exit_code("MAYBE_OK")


class TestEvaluate(unittest.TestCase):
    def test_missing_file_is_unreadable(self):
        rec = cache_state.evaluate({"exists": False})
        self.assertEqual(rec["verdict"], cache_state.UNREADABLE_VERDICT)
        self.assertEqual(rec["exit_code"], 4)

    def test_bad_field_is_unreadable_not_ok(self):
        """fail closed：字段坏了不能变成 PASS。"""
        rec = cache_state.evaluate({"exists": True, "has_physics": True, "is_baked": "yes"})
        self.assertEqual(rec["verdict"], cache_state.UNREADABLE_VERDICT)
        self.assertEqual(rec["exit_code"], 4)

    def test_suspect_explains_itself(self):
        rec = cache_state.evaluate({"exists": True, "has_physics": True,
                                    "is_baked": True, "is_outdated": True})
        self.assertEqual(rec["verdict"], cache_state.SUSPECT_BAKED_OUTDATED)
        self.assertEqual(rec["exit_code"], 4)
        self.assertIn("无法证明", rec["reason"])
        self.assertIn("行为探针", rec["reason"])

    def test_defect_carries_reason_and_behavior(self):
        rec = cache_state.evaluate({"exists": True, "has_physics": True, "is_baked": True,
                                    "is_outdated": True, "behavior": behavior(0.9087)})
        self.assertEqual(rec["exit_code"], 3)
        self.assertIn("行为探针", rec["reason"])
        self.assertEqual(rec["behavior"]["cold_jump_vs_recompute_m"], 0.9087)
        self.assertFalse(rec["behavior"]["within_tolerance"])

    def test_worst_code_wins(self):
        """最坏不是数值最大：已证实缺陷(3)比判不了(4)更坏。"""
        code, report = cache_state.evaluate_many({
            "a.blend": {"exists": True, "has_physics": True, "is_baked": False},
            "b.blend": {"exists": True, "has_physics": True, "is_baked": True,
                        "is_outdated": True},
            "c.blend": {"exists": True, "has_physics": False},
            "d.blend": {"exists": True, "has_physics": True, "is_baked": True,
                        "is_outdated": True, "behavior": behavior(0.9)},
        })
        self.assertEqual(code, 3)
        self.assertEqual(report["a.blend"]["verdict"], cache_state.OK_UNBAKED)
        self.assertEqual(report["b.blend"]["verdict"], cache_state.SUSPECT_BAKED_OUTDATED)
        self.assertEqual(report["c.blend"]["verdict"], cache_state.OK_NO_PHYSICS)
        self.assertEqual(report["d.blend"]["verdict"], cache_state.DEFECT_BAKED_OUTDATED)

    def test_suspect_alone_blocks_with_4(self):
        code, report = cache_state.evaluate_many({
            "b.blend": {"exists": True, "has_physics": True, "is_baked": True,
                        "is_outdated": True},
        })
        self.assertEqual(code, 4)
        self.assertEqual(report["b.blend"]["exit_code"], 4)

    def test_unreadable_does_not_outrank_defect(self):
        code, _ = cache_state.evaluate_many({
            "bad.blend": {"exists": False},
            "d.blend": {"exists": True, "has_physics": True, "is_baked": True,
                        "is_outdated": True, "behavior": behavior(0.9)},
        })
        self.assertEqual(code, 3)

    def test_all_ok_is_zero(self):
        code, _ = cache_state.evaluate_many({
            "a.blend": {"exists": True, "has_physics": True, "is_baked": False},
            "v.blend": {"exists": True, "has_physics": True, "is_baked": True,
                        "is_outdated": True, "behavior": behavior(0.0)},
        })
        self.assertEqual(code, 0)

    def test_empty_batch_is_ok(self):
        code, report = cache_state.evaluate_many({})
        self.assertEqual((code, report), (0, {}))


class TestPlan(unittest.TestCase):
    """判据 → 下一步动作：只回动作名，不执行。"""

    def test_suspect_plans_probe_not_delivery(self):
        """旗标只是筛选：先测，不许直接跳到修法。"""
        out = cache_state.plan({"exists": True, "has_physics": True,
                                "is_baked": True, "is_outdated": True})
        self.assertEqual(out["action"], "probe_behavior")
        self.assertIn("未验证", out["note"])
        self.assertIn("behavior", out["note"])
        self.assertIn("J_baked", out["note"])       # 反例必须写在动作里，否则下一个人还会误判

    def test_defect_plans_rebake(self):
        out = cache_state.plan({"exists": True, "has_physics": True, "is_baked": True,
                                "is_outdated": True, "behavior": behavior(0.9087)})
        self.assertEqual(out["action"], "rebake")
        self.assertIn("bake_all", out["note"])
        self.assertIn("32.2", out["note"])          # 实测耗时，让下一个人知道代价
        self.assertIn("四条条件", out["note"])       # §6 豁免条件必须随动作走

    def test_ok_plans_none(self):
        for rec in ({"exists": True, "has_physics": True, "is_baked": False},
                    {"exists": True, "has_physics": True, "is_baked": True,
                     "is_outdated": False},
                    {"exists": True, "has_physics": True, "is_baked": True,
                     "is_outdated": True, "behavior": behavior(0.0)},
                    {"exists": True, "has_physics": False}):
            self.assertEqual(cache_state.plan(rec)["action"], "none")

    def test_unreadable_plans_inspect(self):
        self.assertEqual(cache_state.plan({"exists": False})["action"], "inspect")

    def test_plan_never_emits_rejected_action(self):
        """`rebake_by_stepping` 已被 P12 证伪：它不许出现在任何判定的 plan 输出里。"""
        records = [
            {"exists": True, "has_physics": True, "is_baked": True, "is_outdated": True},
            {"exists": True, "has_physics": True, "is_baked": True, "is_outdated": True,
             "behavior": behavior(0.9087)},
            {"exists": True, "has_physics": True, "is_baked": False},
            {"exists": True, "has_physics": True, "is_baked": True, "is_outdated": False},
            {"exists": True, "has_physics": False},
            {"exists": False},
        ]
        for rec in records:
            out = cache_state.plan(rec)
            self.assertIn(out["action"], cache_state.PLAN_ACTIONS)
            self.assertNotIn(out["action"], cache_state.REJECTED_ACTIONS)

    def test_rejected_actions_carry_evidence(self):
        """证伪记录必须写清「怎么试的、看到什么」，否则下一个人会重跑一遍。"""
        for name, why in cache_state.REJECTED_ACTIONS.items():
            with self.subTest(action=name):
                self.assertGreater(len(why), 40)
        self.assertIn("1.922861", cache_state.REJECTED_ACTIONS["rebake_by_stepping"])
        self.assertIn("P12", cache_state.REJECTED_ACTIONS["rebake_by_stepping"])


class TestSidecar(unittest.TestCase):
    """交付契约 B：sidecar 随产物走，消费者自己看得出这是哪一类。"""

    def test_sidecar_fields_and_verdict(self):
        rec = {"exists": True, "has_physics": True, "is_baked": True, "is_outdated": True,
               "info": "326 frames in memory (2.9 MiB).", "bodies": 324,
               "use_disk_cache": False, "behavior": behavior(0.0)}
        side = cache_state.sidecar(rec)
        self.assertEqual(side["verdict"], cache_state.OK_BAKED_VERIFIED)
        self.assertEqual(side["exit_code"], 0)
        self.assertEqual(side["spec"], "cache_state/1")
        for key in cache_state.SIDECAR_KEYS:
            self.assertIn(key, side)
        self.assertEqual(side["bodies"], 324)
        self.assertFalse(side["use_disk_cache"])

    def test_sidecar_does_not_invent_missing_fields(self):
        """没测到就是 None，不许编成 0 / False。"""
        side = cache_state.sidecar({"exists": True, "has_physics": True, "is_baked": False})
        self.assertIsNone(side["use_disk_cache"])
        self.assertIsNone(side["bodies"])
        self.assertIsNone(side["info"])
        self.assertEqual(side["verdict"], cache_state.OK_UNBAKED)


class TestCli(unittest.TestCase):
    """CLI 子进程。**显式钉死 utf-8**：`text=True` 走本地编码时，中文输出在 GBK 控制台上
    会让 `capture_output` 抛 `UnicodeDecodeError`（`proc.stdout` 变成 `None`），
    那是测试的环境依赖，不是被测代码的缺陷（2026-11-16 在 `PYTHONIOENCODING=utf-8` 下撞到）。"""

    @staticmethod
    def run_cli(args):
        return subprocess.run([sys.executable, "-m", "mmdpipe.cache_state"] + args,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace")

    def test_cli_exit_code_follows_worst(self):
        records = {"x.blend": {"exists": True, "has_physics": True,
                               "is_baked": True, "is_outdated": True}}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "records.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(records, fh)
            proc = self.run_cli([path])
        self.assertEqual(proc.returncode, 4, proc.stderr)   # 旗标-alone = 未验证
        out = json.loads(proc.stdout)
        self.assertEqual(out["x.blend"]["verdict"], cache_state.SUSPECT_BAKED_OUTDATED)

    def test_cli_defect_exit_is_3(self):
        records = {"x.blend": {"exists": True, "has_physics": True, "is_baked": True,
                               "is_outdated": True, "behavior": behavior(0.9087)}}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "records.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(records, fh)
            proc = self.run_cli([path])
        self.assertEqual(proc.returncode, 3, proc.stderr)

    def test_cli_without_args_is_usage_error(self):
        proc = self.run_cli([])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("usage", proc.stderr)

    def test_cli_emits_utf8_even_under_gbk_locale(self):
        """CLI 输出必须是 UTF-8 字节，与控制台编码无关（main() 里显式 reconfigure）。

        这里故意把子进程的 `PYTHONIOENCODING` 设成 GBK——报告里有中文 reason，
        若 CLI 跟着控制台走，父进程按 UTF-8 解码就会失败。
        """
        records = {"x.blend": {"exists": True, "has_physics": True,
                               "is_baked": True, "is_outdated": True}}
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "gbk"
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "records.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(records, fh)
            proc = subprocess.run([sys.executable, "-m", "mmdpipe.cache_state", path],
                                  capture_output=True, env=env)
        self.assertEqual(proc.returncode, 4, proc.stderr)
        text = proc.stdout.decode("utf-8")          # 必须是合法 UTF-8，不许靠本地编码
        out = json.loads(text)
        self.assertEqual(out["x.blend"]["verdict"], cache_state.SUSPECT_BAKED_OUTDATED)
        self.assertIn("无法证明", text)              # 中文确实在输出里


if __name__ == "__main__":
    unittest.main()
