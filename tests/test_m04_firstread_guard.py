# -*- coding: utf-8 -*-
"""首读探针的**前置守卫**：判目标 → 判输入，都在 `import bpy` 之前。

验收用 `3号`/`4号` 20:09–20:11 收敛出来的**五件**：
①目标**已存在**（先记 `size / mtime_ns / sha256`）；②打印 `REFUSE …` 且带目标路径；
③`rc` 是语义码（10/11/12），不是 3；④`sha256` 与运行前同值；⑤`size`/`mtime_ns` 也同值。

关键点：**这些断言不需要 Blender** —— 守卫排在 `import bpy` 之前，所以普通 python 就能跑，
负控跑得快才可能真的去跑。`--force` 作为正控：它必须能过守卫（随后才在 `import bpy` 上失败）。
"""
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROBE = os.path.join(ROOT, "reports", "subai", "M04", "scripts", "m04_firstread_probe.py")

EXIT_REFUSED = 10
EXIT_BAD_INPUT = 11


def stat_of(path):
    st = os.stat(path)
    with open(path, "rb") as fh:
        blob = fh.read()
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns,
            "sha256": hashlib.sha256(blob).hexdigest()}


def run_probe(*args):
    return subprocess.run([sys.executable, PROBE, "--"] + list(args),
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


class GuardPrecedesBpyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="m04_guard_")
        cls.target = os.path.join(cls.tmp, "out.json")
        with open(cls.target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write('{"already": "here"}\n')

    def test_refuses_existing_target_with_all_five(self):
        before = stat_of(self.target)
        r = run_probe("--blend", PROBE, "--out", self.target)
        after = stat_of(self.target)
        # ③ 语义码，不是 3（3 是 Blender 意外异常的兜底、也是锁的冲突码）
        self.assertEqual(r.returncode, EXIT_REFUSED, r.stderr)
        # ② 拒绝理由 + 目标路径
        self.assertIn("REFUSE", r.stderr)
        self.assertIn(self.target, r.stderr)
        # ④⑤ sha / size / mtime 三样同值
        self.assertEqual(before["sha256"], after["sha256"])
        self.assertEqual(before["size"], after["size"])
        self.assertEqual(before["mtime_ns"], after["mtime_ns"])

    def test_missing_out_is_bad_input_not_measurement(self):
        r = run_probe("--blend", PROBE)
        self.assertEqual(r.returncode, EXIT_BAD_INPUT)
        self.assertIn("--out", r.stderr)

    def test_missing_blend_is_bad_input(self):
        r = run_probe("--blend", os.path.join(self.tmp, "nope.blend"),
                      "--out", os.path.join(self.tmp, "fresh.json"))
        self.assertEqual(r.returncode, EXIT_BAD_INPUT)
        self.assertIn("输入件不在", r.stderr)

    def test_force_gets_past_the_guard(self):
        """正控：`--force` 必须过守卫；随后在没有 Blender 的解释器里当然失败。"""
        r = run_probe("--blend", PROBE, "--out", self.target, "--force")
        self.assertNotEqual(r.returncode, EXIT_REFUSED, r.stderr)
        self.assertNotEqual(r.returncode, EXIT_BAD_INPUT, r.stderr)
        self.assertNotIn("REFUSE", r.stderr)

    def test_guard_runs_before_bpy_import(self):
        """守卫在 `import bpy` 之前：普通 python 下也走得到（否则会先报 ModuleNotFound）。"""
        r = run_probe("--blend", PROBE, "--out", self.target)
        self.assertNotIn("addon_utils", r.stderr)
        self.assertNotIn("bpy", r.stderr)


if __name__ == "__main__":
    unittest.main()
