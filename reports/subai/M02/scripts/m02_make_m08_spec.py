#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成 M08 交付重建的 `coordination.preflight` 请求 JSON（纯 Python，不开 Blender）。

为什么要这脚本：`cap` 不许手写。它必须来自唯一一处口径——
`mmdpipe.stage.constraint_limit()`（`D-144③`）。但 `stage.py` 在模块顶层 `import bpy`，
所以在 Blender 之外没法直接 import。

本脚本的做法（**不复制那条规则**）：
  1. 从 `mmdpipe/mask.py` 读护栏常量 `DEFAULT_MAX_CONSTRAINTS`（纯模块，无 bpy）；
  2. 从 `mmdpipe/stage.py` 里用 AST 取 `constraint_limit()` 的**源码文本**并核对它确实引用
     `DEFAULT_MAX_CONSTRAINTS`、且「`max_constraints is None` ⇒ 上限 = 需求」这条分支在；
  3. 按该分支算 cap，并把 **cap 的来源三者**（函数路径 / 护栏常量 / 分支）写进 spec，
     供复核者不信任本脚本也能自己算一遍。

如果第 2 步核对失败（函数被改名、分支被删、护栏换了名字），脚本**退出码 2**，不产出 spec：
「算不出来」不能退化成「写个数字先跑」。

用法：
  python m02_make_m08_spec.py --worktree "E:\\code\\mmdpipe-ai\\A1" \
      --needs 8298 --planned 10111 --out out/subai/M00/preflight_delivery_spec.json [--lease false]
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import re
import sys
import time


def read(path):
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


def guardrail_constant(tree_dir):
    src = read(os.path.join(tree_dir, "mmdpipe", "mask.py"))
    m = re.search(r"(?m)^DEFAULT_MAX_CONSTRAINTS\s*=\s*(\d+)\s*$", src)
    if not m:
        raise SystemExit("mask.py 里找不到 DEFAULT_MAX_CONSTRAINTS 的整数字面量：护栏口径变了？")
    return int(m.group(1))


def constraint_limit_source(tree_dir):
    """取 `constraint_limit()` 的源码文本与它是否引用护栏常量。"""
    path = os.path.join(tree_dir, "mmdpipe", "stage.py")
    src = read(path)
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "constraint_limit":
            return ast.get_source_segment(src, node) or ""
    raise SystemExit("stage.py 里找不到 constraint_limit()：口径变了，本脚本不猜")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--worktree", required=True)
    ap.add_argument("--needs", type=int, default=None,
                    help="本次要建的约束条数；默认从 --planned-from 的 constraints_to_add 取，"
                         "手给必须配 --needs-source")
    ap.add_argument("--needs-source", default=None, help="手给 --needs 时这数从哪来")
    ap.add_argument("--planned", type=int, default=None,
                    help="plan() 实测需求，必须同时给 --planned-source")
    ap.add_argument("--planned-source", default=None,
                    help="这个 planned 从哪来（人/文件/命令），写进 spec，供复核者判断值不值")
    ap.add_argument("--planned-from", default=None,
                    help="从一份已有的场景记录里读 constraints_needed（如 m08_round1/stage_mask_*.json），"
                         "比手传数字更硬：数从产物来，不从记忆来")
    ap.add_argument("--out", required=True)
    ap.add_argument("--run-id", default=None,
                    help="本次运行标识（默认时间戳）；带 run_id 的目标路径自带认领，不覆盖上一次")
    ap.add_argument("--lease", default="true", choices=("true", "false"))
    args = ap.parse_args(argv)
    run_id = args.run_id or time.strftime("run_%Y%m%d_%H%M%S")

    # 需求条数不许来自记忆：要么给一份真产物让它读，要么给数字 + 来源。两者都不给 ⇒ 停。
    if args.planned_from:
        with io.open(args.planned_from, encoding="utf-8-sig") as fh:
            rec = json.load(fh)
        rec = rec.get("mask_wired_record") or rec
        if "constraints_needed" not in rec or rec["constraints_needed"] is None:
            raise SystemExit("%s 里没有 constraints_needed：不编数，停。" % args.planned_from)
        planned = int(rec["constraints_needed"])
        planned_source = "file:%s#constraints_needed" % os.path.abspath(args.planned_from)
        # 同一棵树上的「本次要建多少」= constraints_to_add；拿另一棵树的数配这一棵的 cap 就是两树拼数
        if args.needs is None:
            if rec.get("constraints_to_add") is None:
                raise SystemExit("%s 里没有 constraints_to_add：needs 没法同源，停。"
                                 % args.planned_from)
            needs = int(rec["constraints_to_add"])
            needs_source = "file:%s#constraints_to_add" % os.path.abspath(args.planned_from)
        else:
            if not args.needs_source:
                raise SystemExit("手给 --needs 必须同时给 --needs-source。")
            needs = int(args.needs)
            needs_source = str(args.needs_source)
    elif args.planned is not None and args.planned_source:
        planned = int(args.planned)
        planned_source = str(args.planned_source)
        if args.needs is None or not args.needs_source:
            raise SystemExit("手给 --planned 时，--needs 与 --needs-source 也必须给。")
        needs = int(args.needs)
        needs_source = str(args.needs_source)
    else:
        raise SystemExit("必须给 --planned-from，或 --planned 同时给 --planned-source。"
                         "（手抄一个数字、不写来源，就是今天反复出现的「凭记忆构造样例」。停。）")

    wtree = os.path.abspath(args.worktree)
    guard = guardrail_constant(wtree)
    body = constraint_limit_source(wtree)
    if "DEFAULT_MAX_CONSTRAINTS" not in body:
        raise SystemExit("constraint_limit() 不再引用 DEFAULT_MAX_CONSTRAINTS：护栏与上限脱钩，停。")
    if "max_constraints is not None" not in body:
        raise SystemExit("constraint_limit() 的「未显式给上限」分支找不到：口径变了，停。")

    planned = int(planned)
    cap = planned if planned <= guard else guard
    guardrail_hit = planned > guard

    spec = {
        "task_id": "M08",
        "provenance": {
            "stage_file": os.path.join(wtree, "mmdpipe", "stage.py"),
            "mask_file": os.path.join(wtree, "mmdpipe", "mask.py"),
            "preset_file": os.path.join(wtree, "presets", "feiying.json"),
            "build_script": os.path.join(wtree, "reports", "subai", "M02", "scripts",
                                         "m02_build_delivery.py"),
        },
        "needs": needs,
        "needs_source": needs_source,
        "needs_planned": planned,
        "needs_planned_source": planned_source,
        "cap": cap,
        "cap_source": {
            "rule": "mmdpipe.stage.constraint_limit(needed, max_constraints=None) -> (needed, False)",
            "guardrail_constant": "mmdpipe.mask.DEFAULT_MAX_CONSTRAINTS = %d" % guard,
            "guardrail_hit": guardrail_hit,
            "function_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        },
        "skipped": 0,
        "lease": args.lease == "true",
        "expect_owner": "模块负责1|A1",
        "run_id": run_id,
        # 目标写进 <root>/<run_id>/：新 run_id 自带认领，不需要 overwrite 裁决；
        # 上一次的产物留在自己的 run 目录里，不会被静默覆盖。
        "outputs": [
            os.path.join(wtree, "out", "subai", "M08", run_id, "delivery_v1.blend"),
            os.path.join(wtree, "out", "subai", "M08", run_id),
        ],
        "note": ("cap 由 constraint_limit() 的分支与护栏常量现算，不手写；"
                 "needs=任务书需求，needs_planned=plan() 实测，两者都要在报告里对账。"),
    }
    if guardrail_hit:
        print("护栏咬住了：planned=%d > guardrail=%d ⇒ guardrail_hit=True" % (planned, guard))
        return 2

    out = args.out if os.path.isabs(args.out) else os.path.join(wtree, args.out)
    d = os.path.dirname(out)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with io.open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(spec, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")

    print("spec = %s（%d B）" % (out, os.path.getsize(out)))
    print("  needs=%d  needs_planned=%d  cap=%d  guardrail=%d  guardrail_hit=%s  lease=%s"
          % (spec["needs"], planned, cap, guard, guardrail_hit, spec["lease"]))
    print("  constraint_limit() 源码 sha256 = %s" % spec["cap_source"]["function_sha256"])
    for key, val in spec["provenance"].items():
        ok = os.path.abspath(val).startswith(wtree)
        print("  provenance.%-12s %s  %s" % (key, "在树内" if ok else "**在树外**", val))
        if not ok:
            print("      ⇒ 在树外，preflight 会判 PROVENANCE_INVALID（除显式 external_roots）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
