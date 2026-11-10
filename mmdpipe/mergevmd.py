"""VMD 合并：动作的骨骼段 + 表情文件的表情段。

    python -m mmdpipe.mergevmd 动作.vmd 表情.vmd --out 合并.vmd [--pmx 模型.pmx]
"""
from __future__ import annotations

import argparse
import sys

from . import vmd as vmd_mod


def merge_vmd(motion_path, expr_path, out_path, model_name=None, pmx=None,
              verbose=True, offset=0):
    motion = vmd_mod.load(motion_path)
    expr = vmd_mod.load(expr_path)
    if not expr.morph_count:
        raise vmd_mod.VMDError("表情文件里没有表情轨：%s" % expr_path)
    vmd_mod.merge(motion, expr, out_path, model_name=model_name, offset=offset)
    merged = vmd_mod.load(out_path)

    report = {
        "motion": motion_path,
        "expression": expr_path,
        "out": out_path,
        "bone_tracks": len(merged.bone_tracks),
        "bone_frames": merged.bone_count,
        "morph_tracks": len(merged.morph_tracks),
        "morph_frames": merged.morph_count,
        "frame_range": list(merged.frame_range),
        "bytes": merged.bytes_total,
        "expression_offset": offset,
        "ok_bones": len(merged.bone_tracks) == len(motion.bone_tracks),
        "ok_morphs": len(merged.morph_tracks) == len(expr.morph_tracks),
    }
    if pmx:
        from . import pmx as pmx_mod
        model = pmx_mod.load(pmx)
        hit = sorted(n for n in merged.morph_tracks if n in model.morph_names)
        miss = sorted(n for n in merged.morph_tracks if n not in model.morph_names)
        report["morph_hit"] = len(hit)
        report["morph_miss"] = miss
        report["morph_coverage"] = round(len(hit) / len(merged.morph_tracks), 4) if merged.morph_tracks else 1.0

    if verbose:
        print("合并 → %s（%d 字节）" % (out_path, merged.bytes_total))
        print("  骨骼 %d 轨 / %d 帧   表情 %d 轨（%d 帧）"
              % (len(merged.bone_tracks), merged.bone_count,
                 len(merged.morph_tracks), merged.morph_count))
        print("  帧范围 %d..%d" % merged.frame_range)
        if report.get("morph_coverage") is not None:
            print("  表情对模型覆盖 %.1f%%（命中 %d）"
                  % (report["morph_coverage"] * 100, report["morph_hit"]))
            if report["morph_miss"]:
                print("  模型没有的表情：%s" % ", ".join(report["morph_miss"][:10]))
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mmdpipe.mergevmd")
    ap.add_argument("motion")
    ap.add_argument("expression")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model-name")
    ap.add_argument("--pmx")
    ap.add_argument("--offset", type=int, default=0,
                    help="表情段整体帧偏移（多段拼接时用）")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    try:
        rep = merge_vmd(args.motion, args.expression, args.out,
                        args.model_name, args.pmx, offset=args.offset)
    except (vmd_mod.VMDError, OSError) as exc:
        print("合并失败：%s" % exc, file=sys.stderr)
        return 1
    if args.json:
        from .report import dump
        dump(rep, args.json)
    return 0 if rep["ok_bones"] and rep["ok_morphs"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
