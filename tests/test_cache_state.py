"""`mmdpipe.cache_state` 的判据测试：四个状态 + 两种应当被拒的输入 + 批量最坏码。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from mmdpipe import cache_state


class TestClassify(unittest.TestCase):
    def test_unbaked_is_ok(self):
        self.assertEqual(cache_state.classify(has_physics=True, is_baked=False, is_outdated=None),
                         cache_state.OK_UNBAKED)
        self.assertEqual(cache_state.exit_code(cache_state.OK_UNBAKED), 0)

    def test_baked_consistent_is_ok(self):
        v = cache_state.classify(has_physics=True, is_baked=True, is_outdated=False)
        self.assertEqual(v, cache_state.OK_BAKED_CONSISTENT)
        self.assertEqual(cache_state.exit_code(v), 0)

    def test_baked_outdated_is_defect(self):
        v = cache_state.classify(has_physics=True, is_baked=True, is_outdated=True)
        self.assertEqual(v, cache_state.DEFECT_BAKED_OUTDATED)
        self.assertEqual(cache_state.exit_code(v), 3)

    def test_no_physics_is_ok(self):
        v = cache_state.classify(has_physics=False, is_baked=None, is_outdated=None)
        self.assertEqual(v, cache_state.OK_NO_PHYSICS)
        self.assertEqual(cache_state.exit_code(v), 0)

    def test_unbaked_ignores_is_outdated(self):
        """未烘焙时 is_outdated 没有意义，两种取值都必须判 OK。"""
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

    def test_defect_carries_reason(self):
        rec = cache_state.evaluate({"exists": True, "has_physics": True,
                                    "is_baked": True, "is_outdated": True})
        self.assertEqual(rec["exit_code"], 3)
        self.assertIn("两条不同动画", rec["reason"])

    def test_worst_code_wins(self):
        code, report = cache_state.evaluate_many({
            "a.blend": {"exists": True, "has_physics": True, "is_baked": False},
            "b.blend": {"exists": True, "has_physics": True, "is_baked": True,
                        "is_outdated": True},
            "c.blend": {"exists": True, "has_physics": False},
        })
        self.assertEqual(code, 3)
        self.assertEqual(report["a.blend"]["verdict"], cache_state.OK_UNBAKED)
        self.assertEqual(report["b.blend"]["verdict"], cache_state.DEFECT_BAKED_OUTDATED)
        self.assertEqual(report["c.blend"]["verdict"], cache_state.OK_NO_PHYSICS)

    def test_empty_batch_is_ok(self):
        code, report = cache_state.evaluate_many({})
        self.assertEqual((code, report), (0, {}))


class TestCli(unittest.TestCase):
    def test_cli_exit_code_follows_worst(self):
        records = {"x.blend": {"exists": True, "has_physics": True,
                               "is_baked": True, "is_outdated": True}}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "records.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(records, fh)
            proc = subprocess.run([sys.executable, "-m", "mmdpipe.cache_state", path],
                                  capture_output=True, text=True)
        self.assertEqual(proc.returncode, 3, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["x.blend"]["verdict"], cache_state.DEFECT_BAKED_OUTDATED)

    def test_cli_without_args_is_usage_error(self):
        proc = subprocess.run([sys.executable, "-m", "mmdpipe.cache_state"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("usage", proc.stderr)


if __name__ == "__main__":
    unittest.main()
