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


#: 策略上排除在扫描范围外的目录：**证据脚本是 artifact，不是源码**。
#: 2026-11-16 16:44 Human 定 `reports/` 纳入 git（提交 e7d9916），于是这些 .py 进了
#: `git ls-files`。它们不该被本护栏要求「UTF-8 无 BOM、子进程调用必须带 encoding=」——
#: 这些字节的 sha256 已写进 evidence 记录，改一个字节就等于让历史记录失效（D-159 的教训）。
#: 但要排除得**说出来**：`policy_excluded()` 让「有多少文件在范围外」可见，
#: 否则"0 违规"又会变成"少扫了一堆也不知道"（D-086）。
SCOPE_EXCLUDED_PREFIXES = ("reports/",)

#: 但 `reports/` 里有**被流水线执行的代码**，它们必须进范围（D0 2026-11-16 18:18 的观察）：
#: `reports/subai/<模块>/scripts/*.py` 是重建链、补丁、摘要、读回等真正跑起来的工具。
#: 起因：`1号` 的补丁自检在 GBK 控制台里崩在打印 `⇒` 上（`UnicodeEncodeError`），
#: 而他自检在 UTF-8 下是绿的——**护栏排除了 `reports/`，于是被管线调用的代码没人管**。
#: 只放进「脚本目录」这一类；报告正文、JSON、md 仍在范围外（字节已被 evidence 引用，D-159）。
CHAIN_SCRIPT_SEGMENT = "/scripts/"


def is_chain_script(rel: str) -> bool:
    """`reports/subai/<模块>/scripts/**.py`：被交付链执行的代码，必须与源码同标准。"""
    return rel.startswith(SCOPE_EXCLUDED_PREFIXES) and CHAIN_SCRIPT_SEGMENT in rel


def in_source_scope(rel: str) -> bool:
    return (not rel.startswith(SCOPE_EXCLUDED_PREFIXES)) or is_chain_script(rel)


def chain_scripts(root: str = ROOT) -> list:
    """范围内、来自 `reports/` 的执行脚本（数量必须可见：这条范围不能被悄悄丢掉）。"""
    return [f for f in tracked_py(root, include_excluded=True) if is_chain_script(f)]


def tracked_py(root: str = ROOT, include_excluded: bool = False) -> list:
    """版本控制里的 .py（相对路径）。

    **`git` 失败就判红，不静默退回目录遍历**（D0 2026-11-16 13:50）：这个仓库永远是 git 仓库，
    而退回 `os.walk` 会让「venv/build/reports 已被排除」这个保证失效——那时"0 命中"可能是
    一个文件都没扫，也可能扫了一堆无关文件。判红没有代价。

    `include_excluded=True` 时连策略外目录一起返回（只给 `policy_excluded()` 用）。
    """
    try:
        out = subprocess.run(["git", "-C", root, "ls-files", "--", "*.py"],
                             capture_output=True, text=True, encoding="utf-8", timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("git ls-files 跑不起来，扫描范围不可信：%s" % exc)
    if out.returncode != 0:
        raise RuntimeError("git ls-files 返回 %d，扫描范围不可信：%s"
                           % (out.returncode, (out.stderr or "").strip()[:200]))
    files = sorted(p.strip() for p in out.stdout.splitlines() if p.strip())
    if not files:
        raise RuntimeError("git ls-files 没返回任何 .py——扫描范围为空时，'0 命中' 没有意义")
    if include_excluded:
        return files
    return [f for f in files if in_source_scope(f)]


def policy_excluded(root: str = ROOT) -> list:
    """在版本控制里、但被策略排除在源码范围外的 .py（必须可见，不许静默）。

    `reports/**/scripts/` 已收进范围，所以这里只剩报告/证据正文里的 .py。
    """
    return [f for f in tracked_py(root, include_excluded=True)
            if not in_source_scope(f)]


def scan_tree(root: str = ROOT) -> tuple:
    """返回 (violations, scanned, skipped)。

    * `violations`：`[(相对路径, 行号)]`；
    * `scanned`：**真正解析成功的文件数**；
    * `skipped`：`[(相对路径, 原因)]` 列表——读失败、解码失败、语法错都**必须在这里可见**，
      否则"0 违规"既可能是真干净、也可能是一个都没扫（1号 的 BOM 假阴性就是这么来的）。
    """
    violations = []
    skipped = []
    scanned = 0
    for rel in tracked_py(root):
        path = os.path.join(root, rel.replace("/", os.sep))
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                source = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            skipped.append((rel, "读失败：%s" % type(exc).__name__))
            continue
        try:
            bad = scan_source(source, path)
        except SyntaxError as exc:
            skipped.append((rel, "解析失败：line %s" % (getattr(exc, "lineno", "?"),)))
            continue
        scanned += 1
        for lineno in bad:
            violations.append((rel, lineno))
    return sorted(violations), scanned, skipped


def summary_line(violations: list, scanned: int, skipped: list, excluded: int = 0,
                 chain: int = 0) -> str:
    """固定输出形状：一眼能判绿/不判绿（1号 建议的形状）。

    `excluded`：策略上不在范围内的文件数（`reports/` 里非脚本的证据文件）。
    `chain`：范围内来自 `reports/**/scripts/` 的执行脚本数。
    两个数字都必须出现，否则「0 违规」分不清「真干净」和「少扫了一堆文件」。
    """
    head = "scanned=%d  violations=%d  skipped=%d  excluded_policy=%d  chain_scripts=%d" % (
        scanned, len(violations), len(skipped), excluded, chain)
    if skipped:
        head += "（%s）" % ", ".join("%s:%s" % (p, why) for p, why in skipped[:5])
    return head


class TestGuard(unittest.TestCase):
    def test_repo_is_clean(self):
        violations, scanned, skipped = scan_tree()
        excluded = policy_excluded()
        chain = chain_scripts()
        line = summary_line(violations, scanned, skipped, len(excluded), len(chain))
        self.assertEqual(skipped, [], "有文件没扫成（不可判绿）：%s" % line)
        self.assertGreaterEqual(scanned, 50, "扫到的文件太少，护栏可能在空转：%s" % line)
        self.assertGreaterEqual(len(chain), 10,
                                "交付链脚本没进范围（或目录结构变了）：%s" % line)
        self.assertEqual(violations, [],
                         "这些 subprocess 调用按文本取输出却没有 encoding=：%s（%s）"
                         % (violations, line))

    def test_whitelist_is_empty(self):
        self.assertEqual(WHITELIST, (), "白名单必须为空；要豁免就用行内 opt-out 并写清为什么需要字节")

    def test_scan_returns_counts_and_skips_are_visible(self):
        """`skipped` 是列表不是数字：有文件读不成时必须能被看见。"""
        tmp = tempfile.mkdtemp(prefix="m00_scan_")
        try:
            with open(os.path.join(tmp, "ok.py"), "w", encoding="utf-8", newline="\n") as fh:
                fh.write("import subprocess\nsubprocess.run(['x'], encoding='utf-8', text=True)\n")
            with open(os.path.join(tmp, "broken.py"), "w", encoding="utf-8", newline="\n") as fh:
                fh.write("def ( broken:\n")
            with open(os.path.join(tmp, "latin.py"), "wb") as fh:
                fh.write(b"\xff\xfe\x00bad")
            subprocess.run(["git", "init", "-q", tmp], check=False)
            subprocess.run(["git", "-C", tmp, "add", "-A"], check=False)
            violations, scanned, skipped = scan_tree(tmp)
            self.assertEqual(violations, [])
            self.assertEqual(scanned, 1)
            self.assertEqual(sorted(p for p, _ in skipped), ["broken.py", "latin.py"])
            self.assertIn("解析失败", dict(skipped)["broken.py"])
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_git_failure_is_red_not_silent(self):
        """`git ls-files` 失败 → 抛，不许静默退回目录遍历。"""
        tmp = tempfile.mkdtemp(prefix="m00_nogit_")
        try:
            with open(os.path.join(tmp, "a.py"), "w", encoding="utf-8") as fh:
                fh.write("x = 1\n")
            with self.assertRaises(RuntimeError):
                tracked_py(tmp)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

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
            with open(os.path.join(tmp, "bad_module.py"), "w", encoding="utf-8", newline="\n") as fh:
                fh.write("import subprocess\n"
                         "subprocess.run(['x'], text=True)\n")
            with open(os.path.join(tmp, "clean_module.py"), "w", encoding="utf-8", newline="\n") as fh:
                fh.write("import subprocess\n"
                         "subprocess.run(['x'], text=True, encoding='utf-8')\n")
            subprocess.run(["git", "init", "-q", tmp], check=False)
            subprocess.run(["git", "-C", tmp, "add", "-A"], check=False)
            violations, scanned, skipped = scan_tree(tmp)
            self.assertEqual(violations, [("bad_module.py", 2)])
            self.assertEqual(scanned, 2)
            self.assertEqual(skipped, [])
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_scope_is_version_controlled_files(self):
        """扫描范围来自 `git ls-files`，减去**明写的**策略外目录，加上**被执行的链脚本**。

        `reports/` 自 2026-11-16 16:44 起进版本控制（Human 定，`e7d9916`）。报告正文不该被
        本护栏管：那是证据脚本，字节已被 evidence 哈希引用，改字节等于让历史记录失效（`D-159`）。
        但 `reports/subai/<模块>/scripts/*.py` 是**交付链真正执行的代码**，必须进范围
        （D0 2026-11-16 18:18：`1号` 的补丁自检在 GBK 控制台崩在打印 `⇒` 上，而护栏排除了它）。
        """
        files = tracked_py()
        self.assertTrue(files, "git ls-files 没返回任何 .py，扫描范围失效")
        self.assertFalse([f for f in files if f.startswith("build/")], "build/ 不该进扫描范围")
        chain = chain_scripts()
        self.assertTrue(chain, "reports/**/scripts/ 里的链脚本必须在范围内")
        self.assertTrue(all(is_chain_script(f) for f in chain))
        self.assertEqual(sorted(f for f in files if is_chain_script(f)), sorted(chain),
                         "链脚本必须出现在 scan_tree 的范围里")
        excluded = policy_excluded()
        self.assertTrue(all(not is_chain_script(f) for f in excluded),
                        "链脚本不许出现在『策略外』清单里：%r" % [f for f in excluded if is_chain_script(f)])
        line = summary_line([], len(files), [], len(excluded), len(chain))
        self.assertIn("excluded_policy=%d" % len(excluded), line, "排除数必须在输出里可见")
        self.assertIn("chain_scripts=%d" % len(chain), line, "链脚本数必须在输出里可见")


if __name__ == "__main__":
    unittest.main()
