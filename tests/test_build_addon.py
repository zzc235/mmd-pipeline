"""build_addon.py 的纯 Python 部分（不启动 Blender）。

为什么单测这里：打包脚本最容易出的不是"打不出来"，而是**打出来一个旧包**、
或者"校验失败也照样打包"。这两种都在 11 §9 里被点过名，而且都能在纯 Python
层面钉住：版本一致性、暂存内容、产物文件名选择。

`validate()` / `build()` 会起 `blender.exe --command extension …`，属 Blender 进程，
不在本文件覆盖范围（要锁）。所以这里只测"进 Blender 之前"和"从 Blender 回来之后"。
"""
import os
import shutil
import tempfile
import unittest

import build_addon


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class BuildCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mm07_build_")
        self.src = os.path.join(self.root, "addon", "mmd_pipeline")
        self.stage = os.path.join(self.root, "build", "mmd_pipeline")
        self.dist = os.path.join(self.root, "dist")
        os.makedirs(self.src)
        _write(os.path.join(self.src, "blender_manifest.toml"),
               'schema_version = "1.0.0"\nid = "mmd_pipeline"\nversion = "1.3.0"\n')
        _write(os.path.join(self.src, "__init__.py"),
               'bl_info = {\n    "name": "MMD Pipeline",\n    "version": (1, 3, 0),\n}\n')
        # 一个最小"库"与预设，供暂存用
        _write(os.path.join(self.root, "mmdpipe", "params.py"), "PARAMS = ()\n")
        _write(os.path.join(self.root, "presets", "demo.json"), "{}\n")
        _write(os.path.join(self.root, "run_pipeline.py"), "print('x')\n")
        self._saved = (build_addon.ROOT, build_addon.SRC, build_addon.STAGE, build_addon.DIST)
        build_addon.ROOT = self.root
        build_addon.SRC = self.src
        build_addon.STAGE = self.stage
        build_addon.DIST = self.dist

    def tearDown(self):
        (build_addon.ROOT, build_addon.SRC, build_addon.STAGE, build_addon.DIST) = self._saved
        shutil.rmtree(self.root, ignore_errors=True)

    def write_manifest(self, version):
        _write(os.path.join(self.src, "blender_manifest.toml"),
               'schema_version = "1.0.0"\nid = "mmd_pipeline"\nversion = "%s"\n' % version)


class TestVersion(BuildCase):
    def test_reads_version(self):
        self.assertEqual(build_addon.read_version(), "1.3.0")

    def test_version_drift_is_refused(self):
        """清单升了、bl_info 没升：拒绝打包（否则装上后版本显示还是旧的）。"""
        self.write_manifest("1.4.0")
        with self.assertRaises(SystemExit):
            build_addon.read_version()

    def test_missing_version_is_refused(self):
        _write(os.path.join(self.src, "blender_manifest.toml"), 'id = "mmd_pipeline"\n')
        with self.assertRaises(SystemExit):
            build_addon.read_version()


class TestStage(BuildCase):
    def test_stage_copies_code_and_presets(self):
        build_addon.stage()
        for rel in ("__init__.py", "run_pipeline.py", os.path.join("presets", "demo.json"),
                    os.path.join("mmdpipe", "params.py")):
            self.assertTrue(os.path.isfile(os.path.join(self.stage, rel)), rel)

    def test_stage_excludes_pycache(self):
        """暂存里不能有 __pycache__ / .pyc —— 旧版本会把它们一起打进去。"""
        _write(os.path.join(self.src, "__pycache__", "x.pyc"), "junk")
        _write(os.path.join(self.root, "mmdpipe", "__pycache__", "y.pyc"), "junk")
        build_addon.stage()
        found = [p for p in build_addon._walk(self.stage) if "__pycache__" in p or p.endswith(".pyc")]
        self.assertEqual(found, [])

    def test_stage_refuses_assets(self):
        """预设目录里混进模型/帧序列：拒绝，不静默打进包。"""
        _write(os.path.join(self.root, "presets", "偷偷混进来.pmx"), "PMX")
        with self.assertRaises(SystemExit):
            build_addon.stage()

    def test_stage_refuses_frames(self):
        _write(os.path.join(self.src, "frames", "s_0001.png"), "PNG")
        with self.assertRaises(SystemExit):
            build_addon.stage()


class TestZipSelection(BuildCase):
    def test_expected_zip_name(self):
        path = build_addon.expected_zip("1.3.0")
        self.assertTrue(path.endswith("mmd_pipeline-1.3.0.zip"))
        self.assertEqual(os.path.dirname(path), self.dist)

    def test_old_zip_is_not_the_product(self):
        """dist 里只有旧版本 zip 时，"本次产物"必须判定为缺失。"""
        os.makedirs(self.dist, exist_ok=True)
        _write(os.path.join(self.dist, "mmd_pipeline-1.2.0.zip"), "old")
        self.assertFalse(os.path.isfile(build_addon.expected_zip("1.3.0")))


class TestMainGate(BuildCase):
    """`main()` 的三道出口：校验失败不打包、打包失败不认产物、正常通过才报 PACKAGE。"""

    def test_validate_failure_returns_2_and_no_package(self):
        calls = {"build": 0}

        def fake_stage():
            calls["stage"] = calls.get("stage", 0) + 1

        def fake_validate():
            return False

        def fake_build():
            calls["build"] += 1
            return 0

        saved = (build_addon.stage, build_addon.validate, build_addon.build)
        build_addon.stage, build_addon.validate, build_addon.build = fake_stage, fake_validate, fake_build
        try:
            self.assertEqual(build_addon.main(), 2)
            self.assertEqual(calls["build"], 0, "校验失败仍然调用了 build")
            self.assertFalse(os.path.isfile(build_addon.expected_zip("1.3.0")))
        finally:
            build_addon.stage, build_addon.validate, build_addon.build = saved

    def test_build_failure_returns_3(self):
        saved = (build_addon.stage, build_addon.validate, build_addon.build)
        build_addon.stage = lambda: None
        build_addon.validate = lambda: True
        build_addon.build = lambda: 1
        try:
            self.assertEqual(build_addon.main(), 3)
        finally:
            build_addon.stage, build_addon.validate, build_addon.build = saved

    def test_expected_zip_missing_returns_4(self):
        """build 说成功、但文件名对不上（只剩旧包）→ 不认产物。"""
        saved = (build_addon.stage, build_addon.validate, build_addon.build)
        build_addon.stage = lambda: None
        build_addon.validate = lambda: True
        build_addon.build = lambda: 0
        try:
            os.makedirs(self.dist, exist_ok=True)
            _write(os.path.join(self.dist, "mmd_pipeline-1.2.0.zip"), "old")
            self.assertEqual(build_addon.main(), 4)
        finally:
            build_addon.stage, build_addon.validate, build_addon.build = saved


class TestSha(BuildCase):
    def test_sha256_of_known_content(self):
        path = os.path.join(self.root, "a.bin")
        with open(path, "wb") as fh:
            fh.write(b"abc")
        self.assertEqual(build_addon.sha256(path),
                         "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


if __name__ == "__main__":
    unittest.main(verbosity=2)
