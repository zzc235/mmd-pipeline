"""status 层单测（纯 Python，不需要 Blender）：

    python tests_bpy/test_status.py
    python -m unittest tests_bpy.test_status -v

为什么放在 tests_bpy 而不是 tests/：它测的是面板/operator 那一侧的只读层
（`addon/mmd_pipeline/status.py`），文件归属属 M07；但模块本身不 import bpy，
所以能在纯 Python 下跑，不必为它开 Blender 锁。

覆盖的正是旧代码撞过的那个坑：isolated 布局把帧放进 `work/<run>/frames`，
而 operator 数的是 `<out>/frames`——进度永远 0，测试却一直是绿的。
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
STATUS_PATH = os.path.join(os.path.dirname(HERE), "addon", "mmd_pipeline", "status.py")


def _load():
    spec = importlib.util.spec_from_file_location("mmdp_status", STATUS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


status = _load()


def _touch_frames(directory, n):
    os.makedirs(directory, exist_ok=True)
    for i in range(1, n + 1):
        open(os.path.join(directory, "s_%04d.png" % i), "wb").close()
    # 非 PNG 不算帧：ffmpeg 序列只认连续编号的图
    open(os.path.join(directory, "notes.txt"), "w").close()


def _write_state(root, payload):
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, "pipeline_state.json")
    with open(path, "w", encoding="utf-8") as fh:
        if isinstance(payload, str):
            fh.write(payload)
        else:
            json.dump(payload, fh, ensure_ascii=False)


def _isolated_state(root, run_id="20261116_120000"):
    work = os.path.join(root, "work", run_id)
    final = os.path.join(root, "final", run_id)
    return {
        "schema": 3, "layout": "isolated", "run_id": run_id, "ok": True,
        "paths": {"root": root, "work": work, "final": final},
        "stages": {}, "blocked_by": [],
    }


def _legacy_state(root):
    return {
        "schema": 3, "layout": "legacy", "run_id": "20261116_120000", "ok": False,
        "paths": {"root": root, "work": None, "final": ""},
        "stages": {}, "blocked_by": [],
    }


class TestResolve(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mmdp_status_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_isolated_frames_live_under_work(self):
        """核心回归：isolated 下帧在 work/<run>/frames，不在 <out>/frames。"""
        state = _isolated_state(self.root)
        _write_state(self.root, state)
        info = status.resolve(self.root)
        self.assertEqual(info["frames"], os.path.join(state["paths"]["work"], "frames"))
        self.assertEqual(info["final"], state["paths"]["final"])
        self.assertNotEqual(info["frames"], os.path.join(self.root, "frames"))

    def test_legacy_frames_stay_at_root(self):
        _write_state(self.root, _legacy_state(self.root))
        info = status.resolve(self.root)
        self.assertEqual(info["frames"], os.path.join(self.root, "frames"))
        self.assertEqual(info["mp4"], os.path.join(self.root, "result.mp4"))

    def test_schema2_migrated_paths_are_none(self):
        """schema 2 迁移来的 state：paths 全 None，必须退回根目录而不是拼出 'None/frames'。"""
        _write_state(self.root, {
            "schema": 3, "layout": "legacy", "run_id": "run",
            "paths": {"root": None, "work": None, "final": ""},
        })
        info = status.resolve(self.root)
        self.assertEqual(info["frames"], os.path.join(self.root, "frames"))

    def test_missing_state_does_not_raise(self):
        info = status.resolve(self.root)
        self.assertEqual(info["layout"], "legacy")
        self.assertEqual(info["frames"], os.path.join(self.root, "frames"))
        self.assertEqual(status.summary(self.root)["ok"], False)

    def test_corrupt_state_does_not_raise(self):
        _write_state(self.root, "{这不是 JSON")
        self.assertEqual(status.read_state(self.root), {})
        info = status.resolve(self.root)
        self.assertTrue(info["frames"].endswith("frames"))

    def test_state_not_a_dict(self):
        """半写完的 state 可能是列表/字符串，读出来不能当字典用。"""
        _write_state(self.root, "[1, 2, 3]")
        self.assertEqual(status.read_state(self.root), {})


class TestProgress(unittest.TestCase):
    def test_counts_only_png(self):
        root = tempfile.mkdtemp(prefix="mmdp_png_")
        try:
            _touch_frames(os.path.join(root, "frames"), 3)
            self.assertEqual(status.count_frames(os.path.join(root, "frames")), 3)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_missing_dir_is_zero(self):
        self.assertEqual(status.count_frames(os.path.join(tempfile.gettempdir(), "没有 这个目录")), 0)

    def test_pct_clamped(self):
        self.assertEqual(status.progress_pct(0, 12), 0)
        self.assertEqual(status.progress_pct(6, 12), 50)
        self.assertEqual(status.progress_pct(12, 12), 99)      # 完成由退出码判定，不封 100
        self.assertEqual(status.progress_pct(99, 12), 99)
        self.assertEqual(status.progress_pct(5, 0), 99)        # 帧数 0 时按 1 算，不除零
        self.assertEqual(status.progress_pct(-3, 12), 0)


class TestFailureReason(unittest.TestCase):
    def _state(self):
        return {
            "blocked_by": ["S3_chain"],
            "stages": {
                "S1_physics": {"ok": True, "issues": [
                    {"code": "G2", "severity": "warn", "hint": "覆盖不足"}]},
                "S3_chain": {"ok": False, "issues": [
                    {"code": "E-00", "severity": "warn", "hint": "显式截断"},
                    {"code": "E-15", "severity": "block", "hint": "拼接帧数不守恒：chain=244 帧"}]},
            },
        }

    def test_picks_block_issue_of_blocked_stage(self):
        reason = status.failure_reason(self._state())
        self.assertIn("S3_chain", reason)
        self.assertIn("E-15", reason)
        self.assertNotIn("E-00", reason)          # warn 不是失败原因

    def test_limit(self):
        state = self._state()
        state["blocked_by"] = ["S1_physics", "S3_chain"]
        state["stages"]["S1_physics"]["issues"].append(
            {"code": "G1", "severity": "block", "hint": "刚体数 0"})
        self.assertEqual(len(status.failure_reason(state).split(" / ")), 2)

    def test_empty_state(self):
        self.assertEqual(status.failure_reason({}), "")
        self.assertEqual(status.current_stage({}), "")

    def test_current_stage_is_last(self):
        self.assertEqual(status.current_stage(self._state()), "S3_chain")


class TestSummary(unittest.TestCase):
    def test_summary_isolated_counts_work_frames(self):
        root = tempfile.mkdtemp(prefix="mmdp_sum_")
        try:
            state = _isolated_state(root)
            _write_state(root, state)
            _touch_frames(os.path.join(state["paths"]["work"], "frames"), 4)
            info = status.summary(root)
            self.assertEqual(info["frames"], 4)
            self.assertEqual(info["layout"], "isolated")
            self.assertEqual(info["state"], os.path.join(root, "pipeline_state.json"))
        finally:
            shutil.rmtree(root, ignore_errors=True)


class TestReportLines(unittest.TestCase):
    """报告区显示行（面板只负责画，文本逻辑在这里可测）。"""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mmdp_lines_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_no_out_dir_says_so(self):
        self.assertEqual(status.report_lines(""), ["还没选输出目录"])

    def test_missing_state_is_not_a_traceback(self):
        lines = status.report_lines(self.root)
        self.assertTrue(lines[0].startswith("状态 未完成"))

    def test_blocked_reason_is_shown(self):
        state = _isolated_state(self.root)
        state["ok"] = False
        state["blocked_by"] = ["S3_chain"]
        state["stages"] = {"S3_chain": {"ok": False, "issues": [
            {"code": "E-15", "severity": "block", "hint": "拼接帧数不守恒"}]}}
        _write_state(self.root, state)
        lines = status.report_lines(self.root)
        text = " / ".join(lines)
        self.assertIn("S3_chain", text)
        self.assertIn("E-15", text)

    def test_completed_run_shows_frames(self):
        state = _isolated_state(self.root)
        _write_state(self.root, state)
        _touch_frames(os.path.join(state["paths"]["work"], "frames"), 5)
        lines = status.report_lines(self.root)
        self.assertIn("5", lines[0])
        self.assertIn("完成", lines[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
