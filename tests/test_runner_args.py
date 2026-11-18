"""runner 的**参数层**回归：单段 `--vmd`、无 `--preset`、默认值同源。

为什么打桩
----------
`mmdpipe/runner.py` 顶部是 `import bpy`（L21），模块级依赖 Blender，纯 Python 环境导不进来。
这里把 `bpy` 与几个 bpy 型模块替换成占位对象，让 runner 能被导入，**只验证 `_parse_args`**。

边界（必须记住）
----------------
本文件**只覆盖参数层**：能抓「参数名改了 / 默认值漂了 / 必需项丢了 / Blender 传参约定被破坏」，
**抓不到「单段路径真跑起来对不对」**——那需要 Blender 实跑（`tests_bpy/` 或锁窗口）。
不要拿这里的绿去说「单段路径已验证」。

历史坑（任务书 §5-F2）
--------------------
改了 `runner.py`/`state` 之后，单段与无预设路径一直没有任何自动化测试兜着，
而「带参通过 ≠ 不带参也通过」这条已经在本项目踩过一次（`_fit_camera` 丢了最后一条返回路径）。
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

import importlib

_runner = None
_params = None
_patcher = None


class _Any:
    """吞掉任何属性访问与调用的占位对象。"""

    def __getattr__(self, name):        # pragma: no cover - 只为让 import 过去
        return _Any()

    def __call__(self, *args, **kwargs):  # pragma: no cover
        return _Any()

    def __or__(self, other):              # 类型注解里偶见 X | None
        return _Any()


def _bpy_stub_modules():
    bpy = types.ModuleType("bpy")
    bpy.types = types.SimpleNamespace(Object=_Any, Operator=_Any, Panel=_Any,
                                      PropertyGroup=_Any, Scene=_Any)
    for name in ("ops", "data", "context", "props", "utils", "path", "app", "msgbus"):
        setattr(bpy, name, _Any())
    mathutils = types.ModuleType("mathutils")
    for name in ("Vector", "Matrix", "Euler", "Quaternion"):
        setattr(mathutils, name, _Any())
    bpy_extras = types.ModuleType("bpy_extras")
    bpy_extras.io_utils = _Any()
    return {
        "bpy": bpy,
        "bpy.types": bpy.types,
        "bpy_extras": bpy_extras,
        "bpy_extras.io_utils": bpy_extras.io_utils,
        "mathutils": mathutils,
    }


def setUpModule():
    global _runner, _params, _patcher
    _patcher = mock.patch.dict(sys.modules, _bpy_stub_modules())
    _patcher.start()
    _runner = importlib.import_module("mmdpipe.runner")
    _params = importlib.import_module("mmdpipe.params")


def tearDownModule():
    if _patcher is not None:
        _patcher.stop()


def _parse(*argv):
    """按 Blender 的调用形态解析：`blender -b -P runner.py -- <参数>`。"""
    return _runner._parse_args(["blender", "-b", "-P", "runner.py", "--"] + list(argv))


class TestRunnerArgvSingleVmd(unittest.TestCase):
    """单段 `--vmd` 路径（任务书 §5-F2 要求补的那条）。"""

    def test_single_vmd_without_preset(self):
        a = _parse("--pmx", "m.pmx", "--vmd", "动作.vmd", "--out", "o")
        self.assertEqual(a.vmd, "动作.vmd")
        self.assertIsNone(a.motions, "单段不该带 motions")
        self.assertIsNone(a.preset, "不给 --preset 时必须真的是 None（走内置默认），不是空串")

    def test_motions_without_preset(self):
        a = _parse("--pmx", "m.pmx", "--motions", "a.vmd;b.vmd", "--out", "o")
        self.assertEqual(a.motions, "a.vmd;b.vmd")
        self.assertIsNone(a.preset)

    def test_preset_path_is_passed_through(self):
        a = _parse("--pmx", "m.pmx", "--vmd", "a.vmd", "--out", "o", "--preset", "p.json")
        self.assertEqual(a.preset, "p.json")

    def test_no_preset_key_absent_from_namespace_defaults(self):
        """不给 --preset 时，命名空间里拿到的必须是 None 而不是缺键（管线靠它判默认）。"""
        a = _parse("--pmx", "m.pmx", "--vmd", "a.vmd", "--out", "o")
        self.assertTrue(hasattr(a, "preset"))

    def test_pmx_is_required(self):
        """应当被拒的输入：缺 --pmx 必须直接退出，不能带着 None 往下跑。"""
        with self.assertRaises(SystemExit) as ctx:
            _parse("--vmd", "a.vmd", "--out", "o")
        self.assertNotEqual(ctx.exception.code, 0)

    def test_explicit_run_id_is_parsed_from_single_source(self):
        a = _parse("--pmx", "m.pmx", "--vmd", "a.vmd", "--out", "o",
                   "--run-id", "M02_20261116T210000_abcd1234")
        self.assertEqual(a.run_id, "M02_20261116T210000_abcd1234")


class TestRunnerArgvShape(unittest.TestCase):
    """Blender 传参约定：参数必须放在 `--` 之后。"""

    def test_argv_without_separator_is_rejected(self):
        """不带 `--` 时 `_parse_args` 把 argv 当空，必需项因此缺失——钉住这个坑。"""
        with self.assertRaises(SystemExit) as ctx:
            _runner._parse_args(["--pmx", "m.pmx", "--vmd", "a.vmd", "--out", "o"])
        self.assertNotEqual(ctx.exception.code, 0)


class TestRunnerDefaultsSingleSource(unittest.TestCase):
    """默认值只许在 `mmdpipe/params.py` 声明一次。

    与 D-040（gap 两处各写字面量）同一个病：CLI 与声明表的默认值一旦分叉，
    两个数都「正常」却永远对不上，而且看不出是缺陷。
    """

    def test_defaults_equal_a_fresh_parser_from_params(self):
        """runner 解析出来的默认值，必须等于直接用 `params.add_arguments` 建出来的解析器。

        注意不能拿 `Param.default` 原值比：声明表里 `fps` 的默认是字符串 `"30"`，
        `add_arguments` 会按 kind 转成 choice/int，直接比会误报。这里比的是**同一个声明源
        生成的解析结果**，这正是「单一声明源」该验的东西。
        """
        import argparse

        from mmdpipe import params as pmod

        ap = argparse.ArgumentParser()
        pmod.add_arguments(ap)
        reference = ap.parse_args(["--pmx", "m.pmx"])

        a = _parse("--pmx", "m.pmx", "--vmd", "动作.vmd", "--out", "o")
        explicit = {"pmx", "vmd", "out"}          # 本条显式给过，不参与默认值比较
        for key, want in vars(reference).items():
            if key in explicit:
                continue
            with self.subTest(param=key):
                self.assertEqual(getattr(a, key), want,
                                 "%s 的默认值与 params.PARAMS 生成的不一致" % key)

    def test_parse_args_has_no_handwritten_add_argument(self):
        """runner 不再自己手写 add_argument：只调 params.add_arguments(ap)。"""
        import inspect
        src = inspect.getsource(_runner._parse_args)
        self.assertNotIn("ap.add_argument", src,
                         "_parse_args 里出现了手写 add_argument，默认值会在两处漂移")
        self.assertIn("add_arguments(ap)", src,
                      "_parse_args 没有走 params.add_arguments，声明表形同虚设")


class TestRunnerStateMirror(unittest.TestCase):
    """收尾状态的 final 副本必须与 root/work 同源同字节。

    S7 实测抓到的缺陷：旧实现先 copy2(state_path → final) 再补写最终 state，
    final 那份因此是上一拍的旧快照（ok=False、finished=None、无 final 段），
    与同目录的成功成片自相矛盾。这里钉住「一次序列化、多处落盘」。
    """

    def setUp(self):
        import json
        import os
        import tempfile
        self.dir = tempfile.mkdtemp(prefix="mm_state_mirror_")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))
        self.root = os.path.join(self.dir, "pipeline_state.json")
        self.work = os.path.join(self.dir, "work", "pipeline_state.json")
        self.final = os.path.join(self.dir, "final", "pipeline_state.json")
        for p in (self.work, self.final):
            os.makedirs(os.path.dirname(p), exist_ok=True)

    def _load(self, path):
        import json
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_final_mirror_is_same_bytes_and_has_final_section(self):
        state = {"ok": True, "finished_at": "2026-11-18 15:13:12",
                 "run_id": "e2e_test", "final": {"dir": "final", "files": ["result.mp4"]}}
        _runner._write_state(self.root, state, self.work, mirror_paths=(self.final,))
        def raw(path):
            with open(path, "rb") as fh:
                return fh.read()

        root_bytes = raw(self.root)
        self.assertEqual(raw(self.work), root_bytes)
        self.assertEqual(raw(self.final), root_bytes)
        for p in (self.root, self.work, self.final):
            d = self._load(p)
            self.assertTrue(d["ok"], p)
            self.assertEqual(d["finished_at"], "2026-11-18 15:13:12", p)
            self.assertIsNotNone(d["final"], p)

    def test_mirror_list_skips_same_path_as_root(self):
        """root 自己混进 mirror 列表时跳过——不能把同一文件写两遍。"""
        state = {"ok": True}
        _runner._write_state(self.root, state, mirror_paths=(self.root, self.work))
        self.assertEqual(self._load(self.work), state)
        self.assertEqual(self._load(self.root), state)

    def test_no_mirror_when_final_not_requested(self):
        """没给 mirror 时只写 root，final 那份不该凭空出现。"""
        _runner._write_state(self.root, {"ok": False})
        self.assertFalse(__import__("os").path.exists(self.final))


if __name__ == "__main__":
    unittest.main()
