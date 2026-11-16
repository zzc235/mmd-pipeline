# -*- coding: utf-8 -*-
"""Blender 侧探针的**语义码**不许落进 `coordination.lock` 的码区（2/3/4/5）。

触发：`4号` 20:08 在真机上量了七种形状，两件事：
①`SystemExit` 在 `--python-expr` 与 `--python <file>` 两种入口都原样带出（`rc` 各不相同，
不是撞巧给的常数）；我之前担心的「被吞」不成立，`rc=0` 是**`main()` 的返回值没人接**那种形状；
②因此 `sys.exit(n)` 是可用的 —— 但也正因此，**探针自己的码会与锁的码撞车**：
`coordination.lock` 用 `2 用法 / 3 冲突 / 4 不可判定 / 5 guard 丢锁`，而 guard 透传命令 rc
⇒ 探针用 3 报「自检没过」时，调用方分不出「脚本拒绝」还是「锁被别人占着」。

口径：**Blender 侧探针的语义码从 10 起**（10 拒绝/未测、11 输入或身份对不上、12 断言不成立），
`--python-exit-code 3` 保留为意外异常的兜底。

这里用 AST 扫源码，不 import：这些脚本在 Blender 外 import 会直接失败（`import bpy`）。
"""
import ast
import io
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "reports", "subai", "M04", "scripts")

RESERVED = {2, 3, 4, 5}
# 存量债（棘轮）：这 7 支是今晚之前就有的，码 3 已被调用方按「非 0」消费，改码要连带改
# 调用契约与（冻结链上的）重跑验证，收益为负。**清单是钉死的**：新增一支违规 ⇒ 断言红，
# 修好一支 ⇒ 也红（提示把这一行删掉）。不许静默增长，也不许静默漂移。
DEBT = {
    "m04_a0_why_blind.py",
    "m04_apply_mask_channel.py",
    "m04_capsule_probe.py",
    "m04_make_a0_scene.py",
    "m04_mesh_probe_v2.py",
    "m04_penetration_probe.py",
    "make_evidence.py",
}


def exit_codes_in(path):
    """返回源码里 `sys.exit(<常量>)` 的常量集合（含模块级常量名解析不做，只认字面量）。"""
    with io.open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    consts = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and node.value.__class__ is ast.Constant:
                    if isinstance(node.value.value, int):
                        consts[tgt.id] = node.value.value
    codes = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "exit" and len(node.args) == 1):
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, int):
                codes.append(arg.value)
            elif isinstance(arg, ast.Name) and arg.id in consts:
                codes.append(consts[arg.id])
    return codes


def scan(dirpath=None):
    """返回违规列表 `[(文件名, 码)]`；非 0 且 < 10 的码都算违规。"""
    dirpath = dirpath or SCRIPTS
    bad = []
    for name in sorted(os.listdir(dirpath)):
        if not name.endswith(".py"):
            continue
        for code in exit_codes_in(os.path.join(dirpath, name)):
            if code != 0 and code < 10:
                bad.append((name, code))
    return bad


class ReservedCodeTest(unittest.TestCase):
    def test_only_the_pinned_debt_uses_a_lock_reserved_code(self):
        """棘轮：存量债之外一律不许；债条修好也要把清单改小（否则这条会红）。"""
        offending = sorted({name for name, _code in scan()})
        self.assertEqual(offending, sorted(DEBT),
                         "新增了落进锁码区（2/3/4/5）的脚本，或已修好的没从清单里删：%s"
                         % offending)

    def test_scanner_sees_this_repos_codes(self):
        """先证明扫描器真的读到了东西，再谈「没有违规」。"""
        codes = exit_codes_in(os.path.join(SCRIPTS, "m04_firstread_probe.py"))
        self.assertIn(0, codes)
        self.assertIn(10, codes)

    def test_negative_control_flags_reserved_code(self):
        """负控：临时目录里放一个 `sys.exit(3)` 的脚本，扫描器必须报出来。"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with io.open(os.path.join(tmp, "bad_probe.py"), "w",
                         encoding="utf-8", newline="\n") as fh:
                fh.write("import sys\nif __name__ == '__main__':\n    sys.exit(3)\n")
            self.assertEqual(scan(tmp), [("bad_probe.py", 3)])

    def test_negative_control_flags_named_constant(self):
        """负控：常量写法（`EXIT_X = 4` + `sys.exit(EXIT_X)`）也要被抓到。"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with io.open(os.path.join(tmp, "bad2.py"), "w",
                         encoding="utf-8", newline="\n") as fh:
                fh.write("import sys\nEXIT_X = 4\nsys.exit(EXIT_X)\n")
            self.assertEqual(scan(tmp), [("bad2.py", 4)])


if __name__ == "__main__":
    unittest.main()
