"""护栏：`subprocess` 只要按文本取输出，就必须显式给 `encoding=`。

**为什么有这条**（2026-11-16，main 被这条打红过一次）：

```python
subprocess.run(cmd, capture_output=True, text=True)     # 没有 encoding=
```

父进程用**本地编码**（这台机器是 GBK）去解子进程的 **UTF-8** 输出，`UnicodeDecodeError` 直接抛；
更阴的是某些路径下 `stdout` 会变成 `None`，于是 `json.loads(None)` → `TypeError`，报错点离病根很远。
同一天全仓有 12 处这种写法，其中一条还是**确定性测试**（比较两个子进程输出）——两次都拿到 `None`，
`None == None` 为真，那格假绿就是这么来的。

**这条护栏本身也被喂了应当被拒的输入**：`test_violation_is_reported` 用一段**故意违规**的源码要求扫描器报出来，
否则「扫描器永远返回空」和「全仓真的干净」长得一模一样。

**唯一豁免**：确实需要**字节**输出的调用，在调用那一行写 `# noqa: subprocess-bytes`。
现在全仓 0 处使用；`WHITELIST` 必须为空（有测试盯着）。
"""
import ast
import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "__pycache__", "build", "dist", "out", "reports", ".venv", "node_modules"}
FUNCS = {"run", "Popen", "check_output", "call", "check_call"}
OPT_OUT = "noqa: subprocess-bytes"

# 允许豁免的「文件:行号」——**必须为空**。加一条就等于承认那处在文本/字节之间含糊。
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
    """返回违规行号（升序）。违规 = 文本模式却没说用什么编码，且没有 opt-out 注释。"""
    tree = ast.parse(source, filename)
    lines = source.splitlines()
    bad = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _is_subprocess_call(node)):
            continue
        wants_text = _kwarg_true(node, "text") or _kwarg_true(node, "capture_output")
        if not wants_text:
            continue
        if any(kw.arg == "encoding" for kw in node.keywords):
            continue
        if 0 < node.lineno <= len(lines) and OPT_OUT in lines[node.lineno - 1]:
            continue
        bad.append(node.lineno)
    return sorted(bad)


def scan_tree(root: str = ROOT) -> list:
    """返回 [(相对路径, 行号)]。"""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
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
                found.append((os.path.relpath(path, root).replace("\\", "/"), lineno))
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

    def test_capture_output_alone_is_reported(self):
        source = "import subprocess\nsubprocess.run(['x'], capture_output=True)\n"
        self.assertEqual(scan_source(source), [2])

    def test_encoding_present_passes(self):
        source = ('import subprocess\n'
                  'subprocess.run(["x"], capture_output=True, text=True, encoding="utf-8")\n')
        self.assertEqual(scan_source(source), [])

    def test_bytes_mode_is_not_reported(self):
        """不给 text/capture_output 的调用取的是字节，编码无从谈起。"""
        source = 'import subprocess\nsubprocess.run(["x"], stdout=subprocess.DEVNULL)\n'
        self.assertEqual(scan_source(source), [])

    def test_opt_out_marker_is_respected(self):
        source = ('import subprocess\n'
                  'subprocess.run(["x"], capture_output=True)  # noqa: subprocess-bytes\n')
        self.assertEqual(scan_source(source), [])

    def test_temp_file_in_tree_is_found(self):
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


if __name__ == "__main__":
    unittest.main()
