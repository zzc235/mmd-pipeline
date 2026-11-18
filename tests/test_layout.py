"""产物布局测试：work/final 的路径规划与落地动作。

这层是纯算术 + 文件搬运，没有 bpy，所以能被单测钉死。
"""
import os
import tempfile
import unittest

from mmdpipe import layout


class TestRunId(unittest.TestCase):
    def test_from_started_at(self):
        self.assertEqual(layout.run_id("2026-11-11 21:07:30"), "20261111_210730")

    def test_bad_input_falls_back(self):
        # 时间串脏了也不能崩：这层不该有权让整条流水线失败
        for bad in ("", None, "??", "2026-11"):
            self.assertEqual(layout.run_id(bad), "run")

    def test_two_runs_differ(self):
        a = layout.run_id("2026-11-11 21:07:30")
        b = layout.run_id("2026-11-11 21:07:31")
        self.assertNotEqual(a, b)

    def test_explicit_run_id_sanitized(self):
        self.assertEqual(layout.sanitize_run_id("M02_20261116T1.2-3_abcdef12"), "M02_20261116T1.2-3_abcdef12")
        for bad in ("../x", "a/b", "", "x" * 81, ".", ".."):
            with self.assertRaises(ValueError):
                layout.sanitize_run_id(bad)


class TestPlan(unittest.TestCase):
    def test_isolated_splits_work_and_final(self):
        p = layout.plan("E:/out", "isolated", "2026-11-11 21:07:30")
        self.assertEqual(p["work"], os.path.join(os.path.abspath("E:/out"), "work", "20261111_210730"))
        self.assertEqual(p["final"], os.path.join(os.path.abspath("E:/out"), "final", "20261111_210730"))
        self.assertEqual(p["run_id"], "20261111_210730")

    def test_legacy_writes_everything_to_root(self):
        p = layout.plan("E:/out", "legacy", "2026-11-11 21:07:30")
        self.assertEqual(p["work"], os.path.abspath("E:/out"))
        self.assertEqual(p["final"], "", "legacy 没有 final，不能凭空造一个")

    def test_default_is_isolated(self):
        self.assertEqual(layout.plan("E:/out")["layout"], layout.DEFAULT_LAYOUT)
        self.assertEqual(layout.DEFAULT_LAYOUT, "isolated")

    def test_unknown_layout_rejected(self):
        with self.assertRaises(ValueError):
            layout.plan("E:/out", "nope", "")

    def test_explicit_run_id_is_used_verbatim(self):
        p = layout.plan("E:/out", "isolated", "2026-11-11 21:07:30",
                        explicit_run_id="M02_20261116T210000_abcd1234")
        self.assertEqual(p["run_id"], "M02_20261116T210000_abcd1234")
        self.assertTrue(p["work"].endswith(p["run_id"]))


class TestPromote(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mmdlayout ")
        self.work = os.path.join(self.tmp, "work", "r1")
        self.final = os.path.join(self.tmp, "final", "r1")
        os.makedirs(self.work)
        for name in ("result.mp4", "contact_sheet.png"):
            with open(os.path.join(self.work, name), "wb") as fh:
                fh.write(b"x")

    def test_copies_existing_and_skips_missing(self):
        landed = layout.promote(self.work, self.final)
        # 只搬 work 里真有的；camera.json 之类缺失不算错
        self.assertEqual(sorted(landed), ["contact_sheet.png", "result.mp4"])
        self.assertTrue(os.path.isfile(os.path.join(self.final, "result.mp4")))

    def test_work_keeps_originals(self):
        layout.promote(self.work, self.final)
        self.assertTrue(os.path.isfile(os.path.join(self.work, "result.mp4")),
                        "复制不是移动：删 work 前还要能复查")

    def test_no_final_dir_is_noop(self):
        self.assertEqual(layout.promote(self.work, ""), [])

    def test_repromote_same_bytes_is_idempotent(self):
        layout.promote(self.work, self.final)
        self.assertEqual(sorted(layout.promote(self.work, self.final)),
                         ["contact_sheet.png", "result.mp4"])

    def test_different_bytes_in_final_refuse_overwrite(self):
        layout.promote(self.work, self.final)
        with open(os.path.join(self.final, "result.mp4"), "wb") as fh:
            fh.write(b"changed")
        with self.assertRaises(FileExistsError):
            layout.promote(self.work, self.final)

    def test_describe_mentions_where(self):
        self.assertIn("isolated", layout.describe(layout.plan("E:/out", "isolated", "")))
        self.assertIn("legacy", layout.describe(layout.plan("E:/out", "legacy", "")))


if __name__ == "__main__":
    unittest.main()
