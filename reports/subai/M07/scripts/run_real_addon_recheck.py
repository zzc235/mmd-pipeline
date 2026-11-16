# -*- coding: utf-8 -*-
"""真 Blender：扩展「装/不装」复测的驱动（两个短进程，隔离扩展仓库）。

    python out/subai/M07/scripts/run_real_addon_recheck.py --worktree E:\\code\\mmdpipe-ai\\A4

做了什么：

1. 把本机全局装的 `mmd_tools` 扩展**复制**到临时扩展仓库（源目录只读，不改全局）；
2. 起 Blender #1（仓库里有扩展）→ 期望 `ensure_addons(("mmd_tools",))` 判 True 且算子真注册；
3. 把复制来的扩展移出仓库 → 起 Blender #2（仓库里没有扩展）→ 期望判 False；
4. 两次都顺手验反控（名字写错必须判红）与「缺失模块 enable 不抛」；
5. 比对全局 `%APPDATA%` 的扩展目录与 `userpref.blend` 前后的摘要 —— 这是「隔离真的隔住了」的正控，
   不是靠嘴说。

判据分开给、逐条可红；任一 must-pass 不过 ⇒ 退出码 1。读档由 Python 自己写 UTF-8（PowerShell
管道会把中文变成 U+FFFD），控制台只打 ASCII 摘要。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

BLENDER_DEFAULT = r"E:\code\Blender\blender-5.2.2-windows-x64\blender.exe"
BLENDER_VERSION_DIR = "5.2"
EXT_NAME = "mmd_tools"
IGNORED_DIRS = (".cache", ".local", "__pycache__")


# ---------------------------------------------------------------- 摘要

def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_digest(root: str) -> dict:
    """目录内容的可复现摘要：逐文件 (相对路径, 大小, sha256) 排序后再 sha256。"""
    rows = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root).replace("\\", "/")
            size = os.path.getsize(path)
            rows.append("%s|%d|%s" % (rel, size, _sha256(path)))
    h = hashlib.sha256()
    for row in rows:
        h.update(row.encode("utf-8") + b"\n")
    return {"files": len(rows), "sha256": h.hexdigest()}


def file_stamp(path: str) -> dict | None:
    if not os.path.isfile(path):
        return None
    st = os.stat(path)
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": _sha256(path)}


def global_state() -> dict:
    appdata = os.environ.get("APPDATA") or ""
    base = os.path.join(appdata, "Blender Foundation", "Blender", BLENDER_VERSION_DIR)
    ext = os.path.join(base, "extensions")
    cfg = os.path.join(base, "config")
    user_default = os.path.join(ext, "user_default")
    return {
        "root": base,
        "extensions": tree_digest(ext) if os.path.isdir(ext) else None,
        "user_default": tree_digest(user_default) if os.path.isdir(user_default) else None,
        "userpref": file_stamp(os.path.join(cfg, "userpref.blend")),
    }


# ---------------------------------------------------------------- 跑一次 Blender

def run_blender(blender: str, probe: str, worktree: str, mode: str, out_json: str,
                ext_root: str, timeout_s: float) -> dict:
    # 5.2 没有 `--no-prefs` 这个参数（传了会被当成要打开的文件，rc=1 且脚本不跑）；
    # 不读用户偏好要用 `--factory-startup`。扩展仓库根由 BLENDER_USER_EXTENSIONS 指定。
    cmd = [blender, "-b", "--factory-startup", "--python-exit-code", "3",
           "--python", probe, "--",
           "--worktree", worktree, "--mode", mode, "--out", out_json]
    env = dict(os.environ)
    env["BLENDER_USER_EXTENSIONS"] = ext_root       # 扩展仓库根（不是 SCRIPTS）
    env["PYTHONIOENCODING"] = "utf-8"               # 别让子进程输出被控制台代码页毁掉
    env.pop("BLENDER_USER_SCRIPTS", None)
    started = time.time()
    row = {"mode": mode, "cmd": cmd}
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, timeout=timeout_s)
        row["returncode"] = proc.returncode
        row["stdout_tail"] = proc.stdout.decode("utf-8", "replace").splitlines()[-12:]
        row["stderr_tail"] = proc.stderr.decode("utf-8", "replace").splitlines()[-12:]
    except subprocess.TimeoutExpired:
        row["returncode"] = None
        row["error"] = "timeout after %.0fs" % timeout_s
    row["seconds"] = round(time.time() - started, 1)
    row["payload"] = None
    if os.path.isfile(out_json):
        try:
            with open(out_json, "r", encoding="utf-8-sig") as fh:
                row["payload"] = json.load(fh)
        except (OSError, ValueError) as exc:
            row["payload_error"] = "%s: %s" % (type(exc).__name__, exc)
    return row


# ---------------------------------------------------------------- 主流程

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="run_real_addon_recheck")
    ap.add_argument("--worktree", default=r"E:\code\mmdpipe-ai\A4")
    ap.add_argument("--blender", default=BLENDER_DEFAULT)
    ap.add_argument("--out-dir", default="")
    ap.add_argument("--timeout", type=float, default=420.0)
    ap.add_argument("--keep", action="store_true", help="保留临时扩展仓库以便复查")
    args = ap.parse_args(argv)

    worktree = os.path.abspath(args.worktree)
    probe = os.path.join(os.path.dirname(os.path.abspath(__file__)), "real_addon_probe.py")
    out_dir = os.path.abspath(args.out_dir) if args.out_dir else os.path.join(
        worktree, "out", "subai", "M07")
    os.makedirs(out_dir, exist_ok=True)

    result = {"truth_tier": "T3", "blender_exe": args.blender, "worktree": worktree,
              "probe_script": probe, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    failed = []

    for label, path in (("blender", args.blender), ("probe", probe)):
        if not os.path.isfile(path):
            failed.append("%s_missing:%s" % (label, path))

    ext_src = os.path.join(os.environ.get("APPDATA", ""), "Blender Foundation", "Blender",
                           BLENDER_VERSION_DIR, "extensions", "user_default", EXT_NAME)
    if not os.path.isdir(ext_src):
        failed.append("global_extension_missing:%s" % ext_src)
    result["global_extension_source"] = ext_src
    if failed:
        result["failed"] = failed
        result["ok"] = False
        return _write(result, out_dir, failed)

    before = global_state()
    result["global_before"] = before

    tmp = tempfile.mkdtemp(prefix="a4_ext_recheck_")
    ext_root = os.path.join(tmp, "extensions")
    user_default = os.path.join(ext_root, "user_default")
    os.makedirs(user_default, exist_ok=True)
    copied = os.path.join(user_default, EXT_NAME)
    try:
        shutil.copytree(ext_src, copied)
        result["isolated_root"] = ext_root
        result["isolated_copy"] = tree_digest(copied)

        # ① 仓库里有扩展（= 装上了）
        row_present = run_blender(args.blender, probe, worktree, "present",
                                  os.path.join(out_dir, "real_addon_present.json"),
                                  ext_root, args.timeout)
        # ② 把扩展移出仓库（= 没装上），同一棵树、同一个进程参数
        removed = os.path.join(tmp, "removed_" + EXT_NAME)
        shutil.move(copied, removed)
        result["removed_to"] = removed
        row_absent = run_blender(args.blender, probe, worktree, "absent",
                                 os.path.join(out_dir, "real_addon_absent.json"),
                                 ext_root, args.timeout)
        result["runs"] = [row_present, row_absent]

        after = global_state()
        result["global_after"] = after

        # ---- 判据，逐条分开
        checks = {}
        for row in (row_present, row_absent):
            tag = row["mode"]
            payload = row.get("payload") or {}
            checks["%s_exit0" % tag] = row.get("returncode") == 0
            checks["%s_payload_ok" % tag] = bool(payload.get("ok"))
            expected_root = os.path.normcase(os.path.abspath(ext_root))
            got_root = payload.get("extension_root") or ""
            checks["%s_isolated_root_used" % tag] = (
                os.path.normcase(os.path.abspath(got_root)) == expected_root)
        checks["global_user_default_unchanged"] = before.get("user_default") == after.get("user_default")
        checks["global_userpref_unchanged"] = before.get("userpref") == after.get("userpref")
        checks["global_extensions_tree_unchanged"] = (
            (before.get("extensions") or {}).get("sha256") == (after.get("extensions") or {}).get("sha256"))
        # 两次的判词必须真的相反 —— 否则「装/不装」这件事对判据没有影响
        p_ok = (row_present.get("payload") or {}).get("ensure_mmd_tools", {}).get("mmd_tools")
        a_ok = (row_absent.get("payload") or {}).get("ensure_mmd_tools", {}).get("mmd_tools")
        checks["verdicts_are_opposite"] = (p_ok is True) and (a_ok is False)
        checks["experiments_really_differ"] = (
            (row_present.get("payload") or {}).get("mode") == "present"
            and (row_absent.get("payload") or {}).get("mode") == "absent")

        result["checks"] = checks
        result["failed"] = [k for k, v in checks.items() if not v]
        result["ok"] = not result["failed"]
        code = 0 if result["ok"] else 1
    finally:
        if args.keep:
            result["tmp_kept"] = tmp
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    return _write(result, out_dir, result["failed"], code)


def _write(result: dict, out_dir: str, failed, code: int = 1) -> int:
    result["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    path = os.path.join(out_dir, "real_addon_recheck.json")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    runs = result.get("runs") or []
    lines = []
    for row in runs:
        payload = row.get("payload") or {}
        lines.append("[%s] rc=%s %.1fs ok=%s failed=%s" % (
            row.get("mode"), row.get("returncode"), row.get("seconds") or 0,
            payload.get("ok"), ",".join(payload.get("failed") or []) or "-"))
    lines.append("checks: " + (", ".join("%s=%s" % (k, v)
                                         for k, v in sorted((result.get("checks") or {}).items()))
                              or "-"))
    lines.append("failed: " + (", ".join(failed) or "-"))
    lines.append("artifact: " + os.path.join(out_dir, "real_addon_recheck.json"))
    text = "\n".join(lines) + "\n"
    with open(os.path.join(out_dir, "real_addon_recheck.txt"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    sys.stdout.write(text)
    return 0 if (code == 0 and not failed) else code


if __name__ == "__main__":
    sys.exit(main())
