"""护栏：`subprocess` 只要按**文本**取输出，就必须显式给 `encoding=`。

**为什么有这条**（2026-11-16，main 被这条打红过一次）：

```python
subprocess.run(cmd, capture_output=True, text=True)     # 没有 encoding=
```

父进程用**本地编码**（这台机器是 GBK）去解子进程的 **UTF-8** 输出，`UnicodeDecodeError` 直接抛；
更阴的是某些路径下 `stdout` 变成 `None`，于是 `json.loads(None)` → `TypeError`，报错点离病根很远。
同一天全仓有 12 处这种写法，其中一条还是**确定性测试**（比较两个子进程输出）——两次都拿到 `None`，
`None == None` 为真，那格假绿就是这么来的。

**判据只认「解码」**（3号 2026-11-16 13:44 指出第一版判据会自相矛盾）：
`text=True` 或 `universal_newlines=True` 而没有 `encoding=` → 红。
**`capture_output=True` 单独出现不算**——那是 bytes 模式，根本不解码，不会崩；
把它也算进来会逼着一批正当的 bytes 用法去挂豁免，"白名单必须为空"就变成"豁免满地"。

**扫描范围按 `git ls-files`**（只扫版本控制里的 .py）：虚拟环境、`build/`（`build_addon.py` 生成的副本）、
`reports/`、`out/` 天然被排除。不是 git 仓库时退回目录遍历，并跳过同样的目录名。

**这条护栏本身也被喂了应当被拒的输入**：`test_violation_is_reported` 用一段**故意违规**的源码要求扫描器报出来，
否则「扫描器永远返回空」和「全仓真的干净」长得一模一样。

**唯一豁免**：确实需要**字节**输出的调用（现在判据下不会红，只有显式 `text=True` 才红），
或在调用那一行写 `# noqa: subprocess-bytes`。`WHITELIST` 必须为空（有测试盯着）。
"""
import ast
import os
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "__pycache__", "build", "dist", "out", "reports", ".venv", "node_modules",
             "crawl4ai-venv", "cad-venv", "skills_probe", "_ref"}
FUNCS = {"run", "Popen", "check_output", "call", "check_call"}
OPT_OUT = "noqa: subprocess-bytes"

# 允许豁免的「文件:行号」——**必须为空**。
WHITELIST = ()


def _is_subprocess_call(node) -> bool:
    func = node.func
    return (isinstance(func, ast.Attribute) and func.attr in FUNCS
            and isinstance(func.value, ast.Name) and func.value.id == "subprocess")


def _kwarg_true(node, name) -> bool:
    for kw in node.keywords:
        if kw.arg == name:
            return isinstance(kw.value, ast.Constant) and kw.value.value is True
    return False


def scan_source(source: str, filename: str = "<string>") -> list:
    """返回违规行号（升序）。违规 = 文本模式（要解码）却没说用什么编码，且没有 opt-out 注释。

    `ast.Call.lineno` 是**调用第一行**，而豁免注释通常写在**最后一行**（多行调用时）。
    1号 2026-11-16 13:47 踩过：只查 `lineno` 那行会把豁免判成违规。所以查 `lineno..end_lineno`
    **整段**——整段里任何一行写了 opt-out 都算。
    """
    tree = ast.parse(source, filename)
    lines = source.splitlines()
    bad = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _is_subprocess_call(node)):
            continue
        wants_text = _kwarg_true(node, "text") or _kwarg_true(node, "universal_newlines")
        if not wants_text:
            continue
        if any(kw.arg == "encoding" for kw in node.keywords):
            continue
        start = max(1, node.lineno)
        end = max(start, getattr(node, "end_lineno", start) or start)
        span = lines[start - 1:min(end, len(lines))]
        if any(OPT_OUT in line for line in span):
            continue
        bad.append(node.lineno)
    return sorted(bad)


def tracked_py(root: str = ROOT) -> list:
    """版本控制里的 .py（相对路径）。不在 git 仓库时退回目录遍历。"""
    try:
        out = subprocess.run(["git", "-C", root, "ls-files", "--", "*.py"],
                             capture_output=True, text=True, encoding="utf-8", timeout=60)
    except (OSError, subprocess.SubprocessError):
        out = None
    if out is not None and out.returncode == 0 and out.stdout.strip():
        return sorted(p.strip() for p in out.stdout.splitlines() if p.strip())
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(".py"):
                path = os.path.join(dirpath, name)
                found.append(os.path.relpath(path, root).replace("\\", "/"))
    return sorted(found)


def scan_tree(root: str = ROOT) -> list:
    """返回 [(相对路径, 行号)]，按路径排序。"""
    found = []
    for rel in tracked_py(root):
        path = os.path.join(root, rel.replace("/", os.sep))
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                source = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        try:
            bad = scan_source(source, path)
        except SyntaxError:
            continue
        for lineno in bad:
            found.append((rel, lineno))
    return sorted(found)


class TestGuard(unittest.TestCase):
    def test_repo_is_clean(self):
        violations = scan_tree()
        self.assertEqual(violations, [],
                         "这些 subprocess 调用按文本取输出却没有 encoding=：%s" % (violations,))

    def test_whitelist_is_empty(self):
        self.assertEqual(WHITELIST, (), "白名单必须为空；要豁免就用行内 opt-out 并写清为什么需要字节")

    def test_violation_is_reported(self):
        """**应当被拒的输入**：扫描器本身必须先被验过。"""
        source = (
            "import subprocess\n"
            "def f(cmd):\n"
            "    return subprocess.run(cmd, capture_output=True, text=True)\n"
        )
        self.assertEqual(scan_source(source), [3])

    def test_universal_newlines_is_reported(self):
        source = "import subprocess\nsubprocess.run(['x'], universal_newlines=True)\n"
        self.assertEqual(scan_source(source), [2])

    def test_bytes_mode_is_not_reported(self):
        """`capture_output` 单独出现 = bytes 模式，不解码，不算这条缺陷类（3号 13:44）。"""
        for source in ('import subprocess\nsubprocess.run(["x"], capture_output=True)\n',
                       'import subprocess\nsubprocess.run(["x"], capture_output=True, timeout=180)\n'):
            self.assertEqual(scan_source(source), [], source)

    def test_encoding_present_passes(self):
        source = ('import subprocess\n'
                  'subprocess.run(["x"], capture_output=True, text=True, encoding="utf-8")\n')
        self.assertEqual(scan_source(source), [])

    def test_opt_out_marker_is_respected(self):
        source = ('import subprocess\n'
                  'subprocess.run(["x"], text=True)  # noqa: subprocess-bytes\n')
        self.assertEqual(scan_source(source), [])

    def test_opt_out_on_last_line_of_multiline_call(self):
        """多行调用的豁免注释常写在**最后一行**；只查 `lineno` 会把豁免判成违规（1号 踩过）。"""
        source = ('import subprocess\n'
                  'subprocess.run(\n'
                  '    ["x"],\n'
                  '    text=True,\n'
                  ')  # noqa: subprocess-bytes\n')
        self.assertEqual(scan_source(source), [])

    def test_multiline_call_without_opt_out_is_reported(self):
        source = ('import subprocess\n'
                  'subprocess.run(\n'
                  '    ["x"],\n'
                  '    text=True,\n'
                  ')\n')
        self.assertEqual(scan_source(source), [2])

    def test_temp_tree_is_found(self):
        """走一遍 scan_tree（不是只测 scan_source）：临时目录里放一份违规文件必须被抓到。"""
        tmp = tempfile.mkdtemp(prefix="m00_enc_")
        try:
            path = os.path.join(tmp, "bad_module.py")
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("import subprocess\n"
                         "subprocess.run(['x'], text=True)\n")
            self.assertEqual(scan_tree(tmp), [("bad_module.py", 2)])
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_scope_is_version_controlled_files(self):
        """扫描范围来自 `git ls-files`：`build/`「`reports/`」这类目录不进判据。"""
        files = tracked_py()
        self.assertTrue(files, "git ls-files 没返回任何 .py，扫描范围失效")
        self.assertFalse([f for f in files if f.startswith("build/")], "build/ 不该进扫描范围")
        self.assertFalse([f for f in files if f.startswith("reports/")], "reports/ 不该进扫描范围")


if __name__ == "__main__":
    unittest.main()
