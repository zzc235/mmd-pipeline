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
# 口径只管 **Blender 侧**脚本：它们的 rc 会被 `coordination.lock guard` 透传出去，
# 与锁自己的 2/3/4/5 混在一起；系统 python 的 CLI（`m04_group_compare.py` 的 0/1/2/3/4、
# `m04_run_cd.py` 的账本码、三态的 `m04_snapshot_scope.py`）是**已写进文档的契约**，
# 不在这条口径里 —— 但下面 `collision_note` 会把它们的潜在撞车记账，不假装没有。
DEBT = {
    # 今晚之前就在用码 3（「自检没过/未测」）；它们串在 `m04_run_cd.py` 里、rc 只被
    # 「是不是 0」消费，改码要连带改调用契约与（冻结链上的）重跑验证 ⇒ 记为存量债。
    "m04_a0_why_blind.py",
    "m04_apply_mask_channel.py",
    "m04_capsule_probe.py",
    "m04_make_a0_scene.py",
    "m04_mesh_probe_v2.py",
    "m04_penetration_probe.py",
}


def imports_bpy(path):
    """模块级 `import bpy` ⇒ Blender 侧脚本（口径只管这一类）。"""
    with io.open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""])
            if any(n.split(".")[0] == "bpy" for n in names):
                return True
    return False


def _is_int_const(node):
    """int 字面量；**排除 bool**（`True`/`False` 是 `int` 的子类，会把 `return True` 算成码 1）。"""
    return (isinstance(node, ast.Constant) and isinstance(node.value, int)
            and not isinstance(node.value, bool))


def _ints_in(node):
    """一个表达式里出现的 int 常量与变量名（含 `IfExp` 两臂、`and/or` 两侧）。

    `4号` 20:16 的两处就是这个形状：`code = 0 if … else 3` 再 `return code`。
    只看字面量或只看常量名都看不见它 —— 这是**数据流**，不是字面量。
    """
    out = []
    for sub in ast.walk(node):
        if _is_int_const(sub):
            out.append(sub.value)
        elif isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
            out.append(("name", sub.id))
    return out


def exit_codes_in(path):
    """返回该源码里**真正会变成进程退出码**的整数集合。

    口径（`4号` 20:16 的两处缺口逼出来的）：只看**流进 `sys.exit(...)` 的那条链** ——
    ① `sys.exit(<int>)`、`sys.exit(<名>)`；
    ② 喂给它的函数里的 `return <int>` / `return <名>`（含 `code = 0 if … else 3` 这种变量中转）；
    ③ 那条链上再调用的本文件函数（追一层 helper 足够，再深就靠人读）。
    不这么收窄就会变成噪音：任何 `return 1`（连 `return True`）都会被当成退出码。
    """
    with io.open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    consts, assigned, funcs = {}, {}, {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs[node.name] = node
        if isinstance(node, ast.Assign):
            vals = [v for v in _ints_in(node.value) if isinstance(v, int)]
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    if _is_int_const(node.value):
                        consts[tgt.id] = node.value.value
                    if vals:
                        assigned.setdefault(tgt.id, set()).update(vals)

    def resolve(node):
        if _is_int_const(node):
            return [node.value]
        if isinstance(node, ast.Name):
            got = set()
            if node.id in consts:
                got.add(consts[node.id])
            got |= assigned.get(node.id, set())
            return sorted(got)
        return []

    # 找出所有「退出码的入口」：sys.exit(x) 里那个名字/函数
    entry_funcs = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "exit" and len(node.args) == 1):
            arg = node.args[0]
            if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
                entry_funcs.add(arg.func.id)
            elif isinstance(arg, ast.Name) and arg.id in funcs:
                entry_funcs.add(arg.id)
    # 追一层：入口函数里调用的本文件函数也算
    called = set()
    for name in list(entry_funcs):
        for sub in ast.walk(funcs[name]):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) \
                    and sub.func.id in funcs and sub.func.id != name:
                called.add(sub.func.id)
    chain = entry_funcs | called

    codes = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "exit" and len(node.args) == 1):
            codes.extend(resolve(node.args[0]))
    for name in chain:
        for sub in ast.walk(funcs[name]):
            if isinstance(sub, ast.Return) and sub.value is not None:
                codes.extend(resolve(sub.value))
    return codes


def string_systemexit_in(path):
    """`raise SystemExit("消息")` ⇒ **rc=1**，与「崩了」同一个码（`4号` 20:16）。

    返回这类位置的行号：它们不是「拒绝」的合法表达，容易被读成脚本崩了。
    """
    with io.open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or node.exc is None:
            continue
        exc = node.exc
        if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name) \
                and exc.func.id == "SystemExit" and exc.args:
            arg = exc.args[0]
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, int)):
                hits.append(node.lineno)
    return hits


def scan(dirpath=None, only_bpy=True):
    """返回违规列表 `[(文件名, 码)]`：Blender 侧脚本里非 0 且 < 10 的退出码。"""
    dirpath = dirpath or SCRIPTS
    bad = []
    for name in sorted(os.listdir(dirpath)):
        if not name.endswith(".py"):
            continue
        full = os.path.join(dirpath, name)
        if only_bpy and not imports_bpy(full):
            continue
        for code in exit_codes_in(full):
            if code != 0 and code < 10:
                bad.append((name, code))
    return bad


def collision_note(dirpath=None):
    """不在这条口径里的脚本，但它们的码与锁撞车（记账用，不判红）。"""
    dirpath = dirpath or SCRIPTS
    out = []
    for name in sorted(os.listdir(dirpath)):
        if not name.endswith(".py"):
            continue
        full = os.path.join(dirpath, name)
        if imports_bpy(full):
            continue
        hit = sorted({c for c in exit_codes_in(full) if c in RESERVED})
        if hit:
            out.append((name, hit))
    return out


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
        """负控：Blender 侧脚本里 `sys.exit(3)` 必须被报出来。"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with io.open(os.path.join(tmp, "bad_probe.py"), "w",
                         encoding="utf-8", newline="\n") as fh:
                fh.write("import bpy\nimport sys\n"
                         "if __name__ == '__main__':\n    sys.exit(3)\n")
            self.assertEqual(scan(tmp), [("bad_probe.py", 3)])

    def test_negative_control_flags_variable_relay_return(self):
        """负控（`4号` 20:16 的形状）：`code = 0 if … else 3` + `return code` + `sys.exit(main())`。"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "relay.py"), "w",
                      encoding="utf-8", newline="\n") as fh:
                fh.write("import bpy\nimport sys\n\n\n"
                         "def main(ok):\n"
                         "    code = 0 if ok else 3\n"
                         "    return code\n\n\n"
                         "def helper():\n"
                         "    return 1  # 与本文件退出码无关，不该被算进来\n\n\n"
                         "if __name__ == '__main__':\n"
                         "    sys.exit(main(True))\n")
            self.assertIn(("relay.py", 3), scan(tmp))
            self.assertNotIn(("relay.py", 1), scan(tmp))

    def test_system_python_cli_is_out_of_scope_but_noted(self):
        """系统 python 的 CLI 不在这条口径里（码是文档契约），但撞车要记账。"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "cli.py"), "w",
                      encoding="utf-8", newline="\n") as fh:
                fh.write("import sys\nsys.exit(3)\n")
            self.assertEqual(scan(tmp), [])
            self.assertEqual(collision_note(tmp), [("cli.py", [3])])

    def test_boolean_returns_are_not_exit_codes(self):
        """`return True` 不许被当成码 1（bool 是 int 的子类）。"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "booly.py"), "w",
                      encoding="utf-8", newline="\n") as fh:
                fh.write("import bpy\nimport sys\n\n\n"
                         "def main():\n    return True\n\n\n"
                         "sys.exit(0 if main() else 1)\n")
            self.assertEqual([c for _n, c in scan(tmp) if c == True], [])


if __name__ == "__main__":
    unittest.main()
