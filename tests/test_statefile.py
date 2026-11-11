"""state 兼容性测试：能不能读、该不该拒绝、迁移是否只补字段。

失败记录第 41 条（面板/CLI/测试/续跑四处各写各的）之后，state 成了唯一真相，
所以"读不懂就明确拒绝"必须是可测试的行为，而不是注释里的一句话。
"""
import json
import os
import tempfile
import unittest

from mmdpipe import statefile


def _write(path, payload, raw=None):
    with open(path, "w", encoding="utf-8") as fh:
        if raw is not None:
            fh.write(raw)
        else:
            json.dump(payload, fh, ensure_ascii=False)


class TestSchemaRules(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mmdstate ")
        self.path = os.path.join(self.tmp, "pipeline_state.json")

    def test_missing_file(self):
        with self.assertRaises(statefile.StateIncompatible) as ctx:
            statefile.load_compatible(self.path)
        self.assertFalse(ctx.exception.newer)

    def test_missing_schema_is_old(self):
        _write(self.path, {"ok": True, "started_at": "2026-11-01 10:00:00"})
        with self.assertRaises(statefile.StateIncompatible) as ctx:
            statefile.load_compatible(self.path)
        self.assertFalse(ctx.exception.newer)

    def test_schema_1_is_rejected(self):
        _write(self.path, {"schema": 1, "ok": True})
        with self.assertRaises(statefile.StateIncompatible):
            statefile.load_compatible(self.path)

    def test_schema_2_migrates(self):
        _write(self.path, {"schema": 2, "ok": True,
                           "started_at": "2026-11-10 22:20:00"})
        state, notes = statefile.load_compatible(self.path)
        self.assertEqual(state["schema"], statefile.SCHEMA)
        self.assertEqual(state["layout"], "legacy", "v2 本来就是全写根目录")
        self.assertEqual(state["run_id"], "20261110_222000")
        self.assertTrue(notes, "迁移必须留下可读的说明")

    def test_schema_3_passes_untouched(self):
        _write(self.path, {"schema": 3, "ok": True, "layout": "isolated",
                           "run_id": "20261111_210730"})
        state, notes = statefile.load_compatible(self.path)
        self.assertEqual(notes, [])
        self.assertEqual(state["layout"], "isolated")

    def test_newer_schema_is_refused(self):
        _write(self.path, {"schema": statefile.SCHEMA + 1})
        with self.assertRaises(statefile.StateIncompatible) as ctx:
            statefile.load_compatible(self.path)
        self.assertTrue(ctx.exception.newer, "比插件新要能被调用方区分出来")

    def test_corrupt_json_is_refused(self):
        _write(self.path, None, raw="{ not json")
        with self.assertRaises(statefile.StateIncompatible):
            statefile.load_compatible(self.path)


class TestMigrate(unittest.TestCase):
    def test_does_not_mutate_input(self):
        raw = {"schema": 2, "ok": True, "started_at": "2026-11-10 22:20:00"}
        before = json.dumps(raw, sort_keys=True)
        statefile.migrate(raw)
        self.assertEqual(json.dumps(raw, sort_keys=True), before)

    def test_current_schema_is_identity(self):
        raw = {"schema": statefile.SCHEMA, "ok": False, "run_id": "r"}
        state, notes = statefile.migrate(raw)
        self.assertEqual(state, raw)
        self.assertEqual(notes, [])


class TestSummarize(unittest.TestCase):
    def test_one_liner(self):
        text = statefile.summarize({"schema": 3, "ok": True, "stages": {"a": {}},
                                    "blocked_by": [], "layout": "isolated",
                                    "run_id": "r1"})
        self.assertIn("schema=3", text)
        self.assertIn("run=r1", text)


if __name__ == "__main__":
    unittest.main()
