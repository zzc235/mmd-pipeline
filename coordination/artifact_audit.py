"""冻结账本审计：**盘上每个在账上、账上每个在盘上**，且账上写的哈希今天还算得出来。

## 为什么有这个东西

`D-198`/`D-203` 立的规矩是「已交付件版本化 + 冻结 + 账本双向枚举」。但冻结那一刻的
`assertions.bidirectional_ok=true` 只回答**冻结当时**；它不回答「三天后这份 manifest 还准不准」。
真正的风险不是冻结时写错，是**冻结之后有人动了字节而账本没变** —— 那时引用账本写的 sha
就是在引用一件不存在的东西。

所以这个模块只做一件读的事：把 manifest 逐项**重算一次**，并做双向枚举。

## 双向枚举的边界

manifest 与它登记的文件通常在同一个目录里（`frozen/x.blend` + `frozen/frozen_manifest.json`）。
枚举「目录里还有什么没登记」时要排除：manifest 自己、以及其他 `*manifest*.json`（多层冻结
会各自有 manifest）。除此之外多出任何一个文件都是 `only_on_disk` —— 冻结目录里多出来的
东西没人能解释，比少一个更可疑。

## 退出码

0 全部一致 / 3 有漂移（缺件、哈希不符、未登记文件）/ 4 读不到 manifest。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys

MANIFEST_GLOB = "manifest"
SKIP_SUFFIXES = (".json.bak", ".tmp")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_lf_file(path: str) -> str:
    """先把 CRLF 归一成 LF 再算（`evidence_hash_v1.md` 的口径）。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        data = fh.read()
    h.update(data.replace(b"\r\n", b"\n"))
    return h.hexdigest()


def is_readonly(path: str) -> bool:
    try:
        return not bool(os.stat(path).st_mode & stat.S_IWRITE)
    except OSError:
        return False


def _is_manifest_name(name: str) -> bool:
    low = name.lower()
    return MANIFEST_GLOB in low and low.endswith(".json")


def audit_manifest(manifest_path: str, base: str | None = None) -> dict:
    """重算一份 manifest 登记的每一项；返回 `{"ok": bool, "drift": [...], "items": [...]}`。

    `base` 用来解析**只写了文件名**的条目（`{"name": "C_W1.jsonl", ...}` 这种形状，
    `2号` 的批次 manifest 就是）。不给 `base` 时这类条目记为 **`unresolved`** ——
    **不是** `drift`：解析不了路径不等于文件被改过，把「量不了」写成「不一致」正是
    本仓反复立的规矩要杀的东西（`UNMEASURED ≠ FAIL`）。
    """
    with open(manifest_path, "rb") as fh:
        raw = fh.read()
    manifest = json.loads(raw.decode("utf-8"))
    items = manifest.get("items") or manifest.get("files") or []
    here = os.path.dirname(os.path.abspath(manifest_path))
    resolve_base = os.path.abspath(base) if base else here
    listed = set()
    drift = []
    unresolved = []
    warnings = []
    out_items = []

    for item in items:
        path = item.get("frozen_path") or item.get("path")
        bare_name = None
        if not path:
            bare_name = item.get("name") or item.get("role")
            if bare_name:
                path = os.path.join(resolve_base, bare_name)
        if not path:
            drift.append({"why": "item_without_path", "item": item})
            continue
        if not os.path.isabs(path):
            path = os.path.join(resolve_base, path)
        path = os.path.abspath(path)
        role = item.get("role") or item.get("name") or os.path.basename(path)
        rec_sha = item.get("sha256")
        rec_lf = item.get("sha256_lf_normalized")
        row = {"role": role, "path": path, "recorded_sha256": rec_sha,
               "recorded_bytes": item.get("bytes")}
        if not os.path.exists(path):
            if bare_name and not base:
                # 只写了文件名、又没给 base：量不了，不是不一致
                row["state"] = "unresolved"
                unresolved.append({"why": "bare_name_without_base", "role": role,
                                   "name": bare_name, "tried": path})
            else:
                row["state"] = "missing"
                drift.append({"why": "missing", "role": role, "path": path,
                              "recorded_sha256": rec_sha})
            out_items.append(row)
            continue
        listed.add(os.path.normcase(path))
        now_sha = sha256_file(path)
        now_lf = sha256_lf_file(path)
        now_bytes = os.path.getsize(path)
        row.update({"sha256": now_sha, "sha256_lf_normalized": now_lf, "bytes": now_bytes,
                    "readonly": is_readonly(path)})
        if rec_sha and now_sha != rec_sha:
            row["state"] = "sha_drift"
            drift.append({"why": "sha_drift", "role": role, "path": path,
                          "recorded_sha256": rec_sha, "now_sha256": now_sha})
        elif rec_lf and now_lf != rec_lf:
            row["state"] = "lf_drift"
            drift.append({"why": "lf_drift", "role": role, "path": path,
                          "recorded_sha256_lf": rec_lf, "now_sha256_lf": now_lf})
        else:
            row["state"] = "ok"
        if item.get("bytes") is not None and now_bytes != item["bytes"]:
            drift.append({"why": "bytes_drift", "role": role, "path": path,
                          "recorded_bytes": item["bytes"], "now_bytes": now_bytes})
        if item.get("readonly") is not None and bool(item["readonly"]) != row["readonly"]:
            warnings.append({"why": "readonly_changed", "role": role,
                             "recorded": bool(item["readonly"]), "now": row["readonly"]})
        out_items.append(row)

    # 双向：目录里除 manifest 自己与其他 manifest 之外，多出来的文件。
    # **只在条目都落在 manifest 自己这一层目录里时才有定义** —— 条目指向别处（批次 manifest
    # 登记的是批次目录里的产物）时，拿 manifest 所在目录去枚举会得到一堆假 only_on_disk。
    outside = sorted({os.path.dirname(p) for p in listed
                      if os.path.dirname(p) != os.path.normcase(here)})
    only_on_disk = []
    two_way_checked = not outside
    if two_way_checked:
        for name in sorted(os.listdir(here)):
            full = os.path.normcase(os.path.abspath(os.path.join(here, name)))
            if full == os.path.normcase(os.path.abspath(manifest_path)):
                continue
            if _is_manifest_name(name) or name.endswith(SKIP_SUFFIXES):
                continue
            if not os.path.isfile(os.path.join(here, name)):
                continue
            if full not in listed:
                only_on_disk.append(name)
        for name in only_on_disk:
            drift.append({"why": "only_on_disk", "name": name,
                          "path": os.path.join(here, name)})

    state = "OK" if not drift and not unresolved else ("DRIFT" if drift else "UNMEASURED")
    return {
        "manifest": os.path.abspath(manifest_path),
        "manifest_bytes": len(raw),
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "manifest_sha256_lf_normalized":
            hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest(),
        "listed": len(items),
        "listed_ok": sum(1 for r in out_items if r.get("state") == "ok"),
        "unresolved": unresolved,
        "only_on_disk": only_on_disk,
        "two_way_checked": two_way_checked,
        "entries_outside_manifest_dir": outside,
        "items": out_items,
        "drift": drift,
        "warnings": warnings,
        "state": state,
        "ok": not drift,
        "recorded_assertions": manifest.get("assertions"),
    }


def find_manifests(root: str) -> list:
    out = []
    for base, _dirs, names in os.walk(root):
        for name in names:
            if _is_manifest_name(name):
                out.append(os.path.join(base, name))
    return sorted(out)


def audit_root(root: str, base: str | None = None) -> dict:
    reports = []
    for path in find_manifests(root):
        try:
            reports.append(audit_manifest(path, base=base))
        except (OSError, ValueError) as exc:
            reports.append({"manifest": path, "ok": False, "state": "UNREADABLE",
                            "drift": [{"why": "unreadable", "error": str(exc)}],
                            "unresolved": []})
    bad = [r for r in reports if not r["ok"]]
    unmeasured = [r for r in reports if r.get("state") == "UNMEASURED"]
    return {"root": os.path.abspath(root), "base": base, "manifests": len(reports),
            "failures": len(bad), "unmeasured": len(unmeasured),
            "ok": not bad, "reports": reports}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="artifact_audit", description=__doc__.splitlines()[0])
    ap.add_argument("--manifest", help="审一份 manifest")
    ap.add_argument("--root", help="审一棵树下的所有 manifest")
    ap.add_argument("--base", help="把只写了文件名的条目解析到这个目录（不给则记 unresolved，不算 drift）")
    ap.add_argument("--json", help="把结果写到这个路径（UTF-8，无 BOM）")
    ap.add_argument("--quiet", action="store_true", help="只打一行结论")
    args = ap.parse_args(argv)
    if not args.manifest and not args.root:
        ap.print_usage(sys.stderr)
        return 4
    try:
        got = (audit_manifest(args.manifest, base=args.base) if args.manifest
               else audit_root(args.root, base=args.base))
    except (OSError, ValueError) as exc:
        sys.stdout.write("UNREADABLE: %s\n" % exc)
        return 4
    if args.json:
        d = os.path.dirname(os.path.abspath(args.json))
        if d:
            os.makedirs(d, exist_ok=True)
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(got, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    if args.quiet:
        if "drift" in got:
            sys.stdout.write("AUDIT ok=%s drift=%d\n" % (got["ok"], len(got["drift"])))
        else:
            sys.stdout.write("AUDIT ok=%s manifests=%d failures=%d unmeasured=%d\n"
                             % (got["ok"], got["manifests"], got["failures"],
                                got.get("unmeasured", 0)))
    else:
        sys.stdout.write(json.dumps({k: v for k, v in got.items() if k != "reports"},
                                    ensure_ascii=False, indent=1, sort_keys=True) + "\n")
        if "reports" in got:
            for rep in got["reports"]:
                sys.stdout.write("%-58s state=%-10s ok=%s drift=%d unresolved=%d\n"
                                 % (os.path.basename(os.path.dirname(rep["manifest"]))
                                    + "/" + os.path.basename(rep["manifest"]),
                                    rep.get("state", "?"), rep["ok"], len(rep["drift"]),
                                    len(rep.get("unresolved") or [])))
    return 0 if got["ok"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
