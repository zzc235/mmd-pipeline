#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""逐臂 dump 身份表（只读）：每份 `frames.jsonl` 的路径 / 字节 / sha256 / 与谁逐字节相同。

为什么要有这份表
----------------
「三个峰值数相同」和「文件逐字节相同」是两句话，混着说会把下一个人带进坑：
峰值相同只说明**这几臂算出来的运动一样**，它**不**说明文件没变（字段多了、列序变了，峰值照样相同）。
所以身份表只陈述字节级事实，峰值表另处陈述数值级事实；两份都印，读者自己看。

输出：
  - stdout：逐臂表 + 逐字节相同的分组；
  - `--json`：同样内容落盘（供预注册的校验器逐行比）。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys

DYNS = ("B2_baseline", "B2_x07", "B2_y07", "B2_z07",
        "B2r_baseline", "B2r_x07", "B_baseline", "B_x07",
        "baseline", "prepared_baseline", "prepared_x07", "x07")


def sha256_of(path):
    h = hashlib.sha256()
    with io.open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def collect(root):
    rows = []
    dyn = os.path.join(root, "dyn")
    for arm in DYNS:
        p = os.path.join(dyn, arm, "frames.jsonl")
        if os.path.exists(p):
            rows.append({"arm": arm, "kind": "dyn",
                         "path": os.path.relpath(p, root),
                         "bytes": os.path.getsize(p), "sha256": sha256_of(p)})
    s8 = os.path.join(root, "s8")
    if os.path.isdir(s8):
        for arm in sorted(os.listdir(s8)):
            p = os.path.join(s8, arm, "frames.jsonl")
            if os.path.isfile(p):
                rows.append({"arm": arm, "kind": "s8",
                             "path": os.path.relpath(p, root),
                             "bytes": os.path.getsize(p), "sha256": sha256_of(p)})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=r"E:\dsh pr\woker2\out\subai\M02")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    rows = collect(args.root)
    if not rows:
        print("扫到 0 份 frames.jsonl：不给结论（退出码 2）")
        return 2

    groups = {}
    for r in rows:
        groups.setdefault(r["sha256"], []).append(r["arm"])

    print("逐臂 dump 身份（%d 份）" % len(rows))
    print("  %-8s %-20s %10s  %-16s %s" % ("类", "臂", "字节", "sha256 前16", "与谁逐字节相同"))
    for r in rows:
        same = [a for a in groups[r["sha256"]] if a != r["arm"]]
        print("  %-8s %-20s %10d  %-16s %s"
              % (r["kind"], r["arm"], r["bytes"], r["sha256"][:16],
                 ", ".join(same) if same else "（唯一）"))
    print()
    print("逐字节相同的分组（同一 sha 下的臂）：")
    for h, arms in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(arms) > 1:
            print("  %s  ← %s" % (h[:16], ", ".join(arms)))

    if args.json:
        payload = {"root": os.path.abspath(args.root),
                   "count": len(rows),
                   "rows": rows,
                   "identical_groups": {h: sorted(a) for h, a in groups.items() if len(a) > 1}}
        with io.open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
        print("\n写出：%s（%d B）" % (args.json, os.path.getsize(args.json)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
