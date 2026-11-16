"""扫「subprocess 调用带 text=True / capture_output=True 却没有 encoding=」的位置。

    python m02_scan_subprocess_encoding.py [<root> ...]

按 AST 走，不 grep——`Get-Content` / `Select-String` 给的行号会互相矛盾（3号 也踩过）。
排除 venv / .git / node_modules / dist。
"""
import ast
import os
import sys

SKIP_DIRS = {"venv", ".venv", ".git", "node_modules", "dist", "build", "__pycache__",
             ".mypy_cache", ".pytest_cache"}
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


def scan_file(path):
    try:
        source = open(path, encoding="utf-8").read()
        tree = ast.parse(source, filename=path)
    except (SyntaxError, UnicodeDecodeError):
        return []
    lines = source.splitlines()
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not is_subprocess_call(node):
            continue
        kwargs = {kw.arg for kw in node.keywords if kw.arg}
        wants_text = "text" in kwargs or "universal_newlines" in kwargs
        caps = "capture_output" in kwargs or "stdout" in kwargs or "stderr" in kwargs
        if (wants_text or caps) and "encoding" not in kwargs:
            # 与仓库护栏一致：行内 `# noqa: subprocess-bytes` 是「真要字节输出」的豁免。
            # 调用可能跨多行，注释常落在**最后一行**，所以查整段而不是只查 node.lineno。
            start = max(node.lineno - 1, 0)
            end = min(getattr(node, "end_lineno", node.lineno), len(lines))
            segment = "\n".join(lines[start:end])
            if "noqa: subprocess-bytes" in segment:
                continue
            hits.append((node.lineno, sorted(kwargs)))
    return hits


def main():
    roots = sys.argv[1:] or [os.getcwd()]
    total = 0
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                hits = scan_file(path)
                if hits:
                    total += len(hits)
                    rel = os.path.relpath(path, root)
                    for lineno, kwargs in hits:
                        print("%s:%d %s" % (rel, lineno, kwargs))
    print("TOTAL", total)
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
