# -*- coding: utf-8 -*-
"""快照 manifest 的「审计范围」声明与核验（三态，不许把「量不了」报成「不一致」）。

为什么有这一份
--------------
`reports/subai/M04/cd_round2/manifest.json` 的条目**只写文件名**（`name`），而 34 项产物
在 **`out/` 的批次目录**里、只有 1 项在本目录。审计方若按 manifest 所在目录做双向枚举，
会得到一堆假 `only_on_disk`：`总控` 19:50 的 `artifact_audit` 第一版就是这么在我这份上
报了 **46 条假 drift**，改完后把这一形状记成 `two_way_checked=false`。

那份文件一个字节都没动，问题在「范围」没写在盘上而只在对话里。所以这里补两件事：

1. `manifest_scope.json`：把 `base`、`path_field`、`two_way_checked` 与原因写成机器可读；
2. `resolve_scope()`：按声明的 `base` 逐条解析，返回**三态**
   `OK` / `MISMATCH` / `UNMEASURED`。`base` 不在本机（新克隆、别人树上）时是
   `UNMEASURED` —— 「量不了」不是「不一致」，这条今晚被判过四次。
"""
from __future__ import annotations

import io
import json
import os
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m04_paths as _paths  # noqa: E402

STATE_OK = "OK"
STATE_MISMATCH = "MISMATCH"
STATE_UNMEASURED = "UNMEASURED"


def load_json(path):
    with io.open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def resolve_scope(scope, manifest, exists=None):
    """按 `scope["base"]` 解析 manifest 的每一条，返回三态结论。

    `exists` 可注入（测试用），缺省 `os.path.exists`。
    """
    exists = exists or os.path.exists
    base = scope.get("base")
    field = scope.get("path_field", "name")
    if not base:
        return {"state": STATE_UNMEASURED, "reason": "scope 里没有 base，无法解析条目",
                "checked": 0, "missing": []}
    entries = manifest.get("files") or manifest.get("entries") or []
    if not entries:
        return {"state": STATE_UNMEASURED, "reason": "manifest 没有条目",
                "checked": 0, "missing": []}
    if not exists(base):
        return {"state": STATE_UNMEASURED,
                "reason": "base 不在本机：%s（换台机器/新克隆时这是「量不了」，不是「不一致」）" % base,
                "checked": 0, "missing": [], "base": base}
    missing, checked = [], 0
    for ent in entries:
        name = ent.get(field)
        if not name:
            missing.append({"entry": ent, "why": "条目没有 %r 字段" % field})
            continue
        checked += 1
        path = os.path.join(base, str(name).replace("/", os.sep))
        if not exists(path):
            missing.append({"name": name, "path": path, "why": "盘上没有这个文件"})
    state = STATE_OK if not missing else STATE_MISMATCH
    return {"state": state, "base": base, "checked": checked,
            "entries": len(entries), "missing": missing,
            "count_declared": manifest.get("count")}


def git_tracked(relpath, cwd=None):
    """该路径在 git 里有没有被跟踪：`True` / `False` / `None`（本机没有 git ⇒ 算不出）。

    19:55 main 红了一条就是因为原版用 `os.path.exists` 判副本在不在 —— 那只说明**本机**
    有没有，而 `compare.log` 被 `.gitignore:39` 的 `*.log` 吞掉、从来没进过 git。
    「本机有」和「账上有」必须分开问，问错了就是靠本机状态的绿灯。
    """
    import subprocess
    try:
        r = subprocess.run(["git", "ls-files", "--error-unmatch", relpath],
                           cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None
    if r.returncode == 0:
        return True
    if "did not match any file" in (r.stderr or ""):
        return False
    return None


def check_copies(scope, snap_dir, tracked=None, rel_snap=None):
    """核 `snapshot_copies`：`in_git=true` 的必须真的在 git 里，`false` 的必须给出原因。

    三态：`OK` / `MISMATCH` / `UNMEASURED`（git 不可用时算不出，不许算成不一致）。
    """
    tracked = tracked or git_tracked
    rel_snap = rel_snap or snap_dir
    copies = scope.get("snapshot_copies") or []
    if not copies:
        return {"state": STATE_UNMEASURED, "reason": "scope 没有 snapshot_copies"}
    ok, bad, unknown = [], [], []
    for ent in copies:
        name = ent.get("name") if isinstance(ent, dict) else ent
        in_git = ent.get("in_git") if isinstance(ent, dict) else None
        if in_git is None:
            bad.append({"name": name, "why": "缺 in_git 字段（本机有 ≠ 账上有）"})
            continue
        if not in_git:
            if not (isinstance(ent, dict) and ent.get("why_not")):
                bad.append({"name": name, "why": "in_git=false 但没写 why_not"})
            else:
                ok.append({"name": name, "in_git": False})
            continue
        rel = os.path.join(str(rel_snap).replace("\\", "/"), name).replace("\\", "/")
        got = tracked(rel)
        if got is True:
            ok.append({"name": name, "in_git": True})
        elif got is False:
            bad.append({"name": name, "why": "声明 in_git=true 但 git 里没有这个路径", "path": rel})
        else:
            unknown.append({"name": name, "path": rel})
    if bad:
        state = STATE_MISMATCH
    elif unknown:
        state = STATE_UNMEASURED
    else:
        state = STATE_OK
    return {"state": state, "checked": len(copies), "ok": len(ok),
            "bad": bad, "unknown": unknown}


def main(argv=None):
    import argparse
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    snap = os.path.join(os.path.dirname(os.path.dirname(here)), "cd_round2")
    ap = argparse.ArgumentParser(description="快照 manifest 的审计范围核验")
    ap.add_argument("--dir", default=snap, help="快照目录（含 manifest.json 与 manifest_scope.json）")
    args = ap.parse_args(argv)
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")
    scope = load_json(os.path.join(args.dir, "manifest_scope.json"))
    manifest = load_json(os.path.join(args.dir, "manifest.json"))
    out = resolve_scope(scope, manifest)
    repo_root = _paths.find_repo_root(here)
    rel_snap = os.path.relpath(args.dir, repo_root).replace("\\", "/")
    copies = check_copies(scope, args.dir, rel_snap=rel_snap)
    print(json.dumps({"manifest": out, "copies": copies},
                     ensure_ascii=False, indent=2, sort_keys=True))
    if out["state"] == STATE_MISMATCH or copies["state"] == STATE_MISMATCH:
        return 2
    if out["state"] == STATE_UNMEASURED or copies["state"] == STATE_UNMEASURED:
        return 3
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
