"""扫「subprocess 调用带 text=True / universal_newlines=True 却没有 encoding=」的位置（v2）。

    python m02_scan_subprocess_encoding_v2.py [<root> ...]

v2 相对 v1（`m02_scan_subprocess_encoding.py`，已随 attempt 10 入库）修的是**假阴性**，
不是判据：v1 里 `except SyntaxError: return []` 会把解析失败的文件**静默当成干净**。
2号 13:49 实测：PowerShell `-Encoding utf8` 写的文件带 BOM，`encoding="utf-8"` 读进 BOM →
`ast.parse` 抛 `SyntaxError` → 他的扫描器跳过后报「0 处命中」，而负控其实是违规的。

v2 三条改动：
  1. 用 `utf-8-sig` 读（吃掉 BOM）；顺带 `errors="replace"` 不让单个坏字节否掉整棵树；
  2. **解析失败的文件单独计数并打印**——「0 命中」与「0 命中但有 12 个没扫」必须长得不一样；
  3. 判据仍只认解码（`text=True`/`universal_newlines=True` 且无 `encoding=`），与 4号 护栏口径一致；
     `capture_output` 单独出现**不算**（拿 bytes 不解码不会崩），但会作为「更严提示」单独列一行。
另保留 `# noqa: subprocess-bytes` 豁免，按 `lineno..end_lineno` 整段判（注释常落最后一行）。
"""
import ast
import os
import sys

SKIP_DIRS = {"venv", ".venv", ".git", "node_modules", "dist", "build", "__pycache__",
             ".mypy_cache", ".pytest_cache", "crawl4ai-venv", "cad-venv", "skills_probe",
             "_ref", "addon"}
FUNCS = {"run", "Popen", "check_output", "call", "check_call"}


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


def main():
    roots = sys.argv[1:] or [os.getcwd()]
    stats = {"scanned": 0, "unparsed": [], "unreadable": []}
    violations, notices = 0, 0
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
                        violations += 1
                        print("VIOLATION %s:%d %s" % (rel, lineno, kwargs))
                    else:
                        notices += 1
                        print("notice    %s:%d %s（bytes，不解码，与护栏口径无关）"
                              % (rel, lineno, kwargs))
    print("scanned=%d violations=%d bytes_notices=%d unparsed=%d unreadable=%d"
          % (stats["scanned"], violations, notices, len(stats["unparsed"]),
             len(stats["unreadable"])))
    for path, why in stats["unparsed"] + stats["unreadable"]:
        print("  SKIPPED %s：%s" % (path, why))
    # 跳过的文件必须可见：否则「0 命中」与「一个都没扫」长得一样
    return 0 if violations == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
