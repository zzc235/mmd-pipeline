"""扫「subprocess 调用带 text=True / universal_newlines=True 却没有 encoding=」的位置（v3）。

    python m02_scan_subprocess_encoding_v3.py [<root> ...]
    python m02_scan_subprocess_encoding_v3.py --selftest

v3 修的是 **v2 的「不是绿就是绿」**，判据一字未改：
  * v2 里 `roots = sys.argv[1:] or [cwd]` ⇒ 传 `--help` 会被当成一个目录，`os.walk` 一步不走，
    打出 `scanned=0 violations=0` 并 **exit 0**。一次「一个文件都没扫」看起来和「全仓干净」逐字相同。
    v3：以 `-` 开头的参数只认 `--selftest`，其余是参数错 ⇒ exit 2；根目录不存在 ⇒ exit 2。
  * v2 里 `scanned` 不进退出码 ⇒ v3 按「扫到的文件数」判：`scanned == 0` 一律 exit 2
    （「没扫」不是「干净」，这条与 `D-100` 同源）。
  * v2 里解析失败只打印、不影响退出码 ⇒ v3：`unparsed` / `unreadable` 任一非空即 exit 2，
    因为「有几份没判」不能算作「判过都说没问题」。
  * 新增 `--selftest`：在临时目录造假样本（违规 / BOM / noqa 豁免 / 语法错 / 非 subprocess 调用），
    断言计数与退出码。判据本身由反控证明看得见差异，而不是由「跑一遍没报错」证明。

退出码：
    0  扫到了文件，且 0 违规、0 未解析、0 不可读
    1  有违规（判词：不干净）
    2  CANNOT：参数错 / 根不存在 / scanned==0 / 有未解析或不可读的文件

判据（与 4号 护栏一致）：`text=True` 或 `universal_newlines=True` 且没有 `encoding=` ⇒ 违规。
只有 `capture_output` / `stdout=` / `stderr=` 拿 bytes 不解码的，不违规，单列一行 `notice`。
`# noqa: subprocess-bytes` 按 `lineno..end_lineno` 整段判（注释常落最后一行）。
"""
import ast
import os
import shutil
import sys
import tempfile

SKIP_DIRS = {"venv", ".venv", ".git", "node_modules", "dist", "build", "__pycache__",
             ".mypy_cache", ".pytest_cache", "crawl4ai-venv", "cad-venv", "skills_probe",
             "_ref", "addon"}
FUNCS = {"run", "Popen", "check_output", "call", "check_call"}

EXIT_OK, EXIT_DIRTY, EXIT_CANNOT = 0, 1, 2


def is_subprocess_call(node):
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in FUNCS:
        value = func.value
        if isinstance(value, ast.Name) and value.id == "subprocess":
            return True
        if isinstance(value, ast.Attribute) and value.attr == "subprocess":
            return True
    return False


def scan_file(path, stats):
    """返回 [(lineno, kind, kwargs)]；kind 是 'decode'（违规）或 'bytes'（更严提示）。"""
    try:
        source = open(path, encoding="utf-8-sig", errors="replace").read()
    except OSError as exc:
        stats["unreadable"].append((path, str(exc)))
        return []
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        stats["unparsed"].append((path, "SyntaxError: %s" % exc))
        return []
    lines = source.splitlines()
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not is_subprocess_call(node):
            continue
        kwargs = {kw.arg for kw in node.keywords if kw.arg}
        wants_text = "text" in kwargs or "universal_newlines" in kwargs
        caps = "capture_output" in kwargs or "stdout" in kwargs or "stderr" in kwargs
        if not wants_text and not caps:
            continue
        start = max(node.lineno - 1, 0)
        end = min(getattr(node, "end_lineno", node.lineno), len(lines))
        segment = "\n".join(lines[start:end])
        if "noqa: subprocess-bytes" in segment:
            continue
        if wants_text and "encoding" not in kwargs:
            hits.append((node.lineno, "decode", sorted(kwargs)))
        elif caps and "encoding" not in kwargs:
            hits.append((node.lineno, "bytes", sorted(kwargs)))
    stats["scanned"] += 1
    return hits


def scan(roots):
    stats = {"scanned": 0, "unparsed": [], "unreadable": []}
    violations, notices = [], []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                for lineno, kind, kwargs in scan_file(path, stats):
                    rel = os.path.relpath(path, root)
                    if kind == "decode":
                        violations.append((rel, lineno, kwargs))
                    else:
                        notices.append((rel, lineno, kwargs))
    return stats, violations, notices


def report(roots):
    stats, violations, notices = scan(roots)
    for rel, lineno, kwargs in violations:
        print("VIOLATION %s:%d %s" % (rel, lineno, kwargs))
    for rel, lineno, kwargs in notices:
        print("notice    %s:%d %s（bytes，不解码，与护栏口径无关）" % (rel, lineno, kwargs))
    print("scanned=%d violations=%d bytes_notices=%d unparsed=%d unreadable=%d"
          % (stats["scanned"], len(violations), len(notices),
             len(stats["unparsed"]), len(stats["unreadable"])))
    for path, why in stats["unparsed"] + stats["unreadable"]:
        print("  SKIPPED %s：%s" % (path, why))

    if stats["scanned"] == 0:
        print("CANNOT 一个 .py 都没扫到——「没扫」不是「干净」（D-100）")
        return EXIT_CANNOT
    if stats["unparsed"] or stats["unreadable"]:
        print("CANNOT 有 %d 份没判成（未解析 %d / 不可读 %d）——不能算作「判过都说没问题」"
              % (len(stats["unparsed"]) + len(stats["unreadable"]),
                 len(stats["unparsed"]), len(stats["unreadable"])))
        return EXIT_CANNOT
    return EXIT_DIRTY if violations else EXIT_OK


# --------------------------------------------------------------------------- selftest
VIOLATION_SRC = '''import subprocess
subprocess.run(["git", "status"], text=True)
'''
CLEAN_SRC = '''import subprocess
subprocess.run(["git", "status"], text=True, encoding="utf-8")
subprocess.run(["git", "diff"], capture_output=True)   # bytes，不解码
'''
NOQA_SRC = '''import subprocess
subprocess.run(["git", "log"], capture_output=True,
               # noqa: subprocess-bytes —— 故意不解码，调用方自己按字节处理
               )
'''
BROKEN_SRC = 'def f(:\n    pass\n'
BOM_SRC = '\ufeffimport subprocess\nsubprocess.run(["git"], text=True)\n'


def selftest():
    """五份假样本 + 五条断言。判据必须**看得见差异**：违规要红、干净要绿、逃不掉要红。"""
    failures = []

    def check(label, got, want):
        if got != want:
            failures.append("%s: got %r want %r" % (label, got, want))

    tmp = tempfile.mkdtemp(prefix="m02scan_")
    try:
        def put(name, src):
            path = os.path.join(tmp, name)
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(src)
            return path

        put("violation.py", VIOLATION_SRC)
        put("clean.py", CLEAN_SRC)
        put("noqa.py", NOQA_SRC)
        put("broken.py", BROKEN_SRC)
        put("bom.py", BOM_SRC)

        stats, violations, notices = scan([tmp])
        names = sorted(os.path.basename(r) for r, _, _ in violations)
        check("违规文件（BOM 那份也要被抓到）", names, ["bom.py", "violation.py"])
        check("bytes 提示数", len(notices), 1)
        check("语法错单列", [os.path.basename(p) for p, _ in stats["unparsed"]], ["broken.py"])
        check("扫到的文件数", stats["scanned"], 4)      # 5 份里有 1 份没解析成

        empty = tempfile.mkdtemp(prefix="m02scan_empty_")
        try:
            check("空目录 ⇒ CANNOT", report([empty]), EXIT_CANNOT)
        finally:
            shutil.rmtree(empty, ignore_errors=True)
        check("有语法错 ⇒ CANNOT", report([tmp]), EXIT_CANNOT)
        check("参数错 ⇒ CANNOT", main(["--nope"]), EXIT_CANNOT)
        check("根不存在 ⇒ CANNOT", main([os.path.join(tmp, "no_such_dir")]), EXIT_CANNOT)

        clean_dir = tempfile.mkdtemp(prefix="m02scan_clean_")
        try:
            put_dir = clean_dir
            with open(os.path.join(put_dir, "clean.py"), "w", encoding="utf-8", newline="\n") as fh:
                fh.write(CLEAN_SRC)
            check("干净样本 ⇒ OK", report([clean_dir]), EXIT_OK)
            with open(os.path.join(put_dir, "violation.py"), "w", encoding="utf-8", newline="\n") as fh:
                fh.write(VIOLATION_SRC)
            check("加入违规 ⇒ DIRTY", report([clean_dir]), EXIT_DIRTY)
        finally:
            shutil.rmtree(clean_dir, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    for line in failures:
        print("SELFTEST FAIL", line)
    print("SELFTEST %s  cases=%d failures=%d" % ("PASS" if not failures else "FAIL",
                                                11, len(failures)))
    return EXIT_OK if not failures else EXIT_DIRTY


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in args:
        return selftest()
    bad = [a for a in args if a.startswith("-")]
    if bad:
        print("参数错：不认识 %r（以 - 开头的参数只认 --selftest）⇒ CANNOT" % (bad,), file=sys.stderr)
        print("用法: python m02_scan_subprocess_encoding_v3.py [<root> ...] | --selftest")
        return EXIT_CANNOT
    roots = args or [os.getcwd()]
    missing = [r for r in roots if not os.path.isdir(r)]
    if missing:
        print("参数错：不是目录 %r ⇒ CANNOT" % (missing,), file=sys.stderr)
        return EXIT_CANNOT
    return report(roots)


if __name__ == "__main__":
    sys.exit(main())
