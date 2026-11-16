"""多动作拼接：把几段 VMD 首尾接成一条时间轴。

    python -m mmdpipe.concatvmd a.vmd b.vmd c.vmd --out 拼接.vmd [--gap 6] [--offsets 0,300]
    python -m mmdpipe.concatvmd a.vmd b.vmd --out 拼接.vmd --expression 表情.vmd
"""
from __future__ import annotations

import argparse
import sys

from . import vmd as vmd_mod


def concat_vmd(paths, out_path, offsets=None, gap=0, model_name=None,
               expression=None, pmx=None, verbose=True, expression_offset=0,
               frames=None):
    motions = [vmd_mod.load(p) for p in paths]
    if offsets is None:
        offs = None
    else:
        offs = [int(v) for v in offsets]
    rep = vmd_mod.concat(motions, out_path, offsets=offs, gap=gap, model_name=model_name)

    # 显式截断 vs 丢段：请求帧数小于时间轴长度时，差额是"没渲"，不是"没了"。
    # 必须分开记账，否则 337→244 会被当成丢段（244 恰好也是三段偏移算错的帧数）。
    if frames is not None:
        rep["requested_render_frames"] = int(frames)
        rep["explicit_truncated_frames"] = max(0, rep["total_frames"] - int(frames))
        rep["unexplained_gap_frames"] = 0

    if expression:
        merged_path = out_path.replace(".vmd", "_expr.vmd")
        base = vmd_mod.load(out_path)
        expr = vmd_mod.load(expression)
        vmd_mod.merge(base, expr, merged_path, model_name=model_name,
                      offset=expression_offset)
        rep["expression"] = expression
        rep["expression_offset"] = expression_offset
        ex_end = vmd_mod.load(merged_path).frame_range[1]
        expr_end = max(
            [0] + [
                __import__("struct").unpack_from("<I", expr.raw,
                                                 expr.morph_start + i * 23 + 15)[0] + expression_offset
                for i in range(expr.morph_count)]) if expr.morph_count else 0
        rep["expression_end"] = int(expr_end)
        if expr_end > rep["frame_range"][1] + 1:
            print("  ! 表情延伸到 %d 帧，超出骨骼动画末端 %d 帧（尾部表情没有肢体配合）"
                  % (expr_end, expr_end - rep["frame_range"][1]))
        rep["expression_out"] = merged_path
        rep["out"] = merged_path
        base = vmd_mod.load(merged_path)
    else:
        base = vmd_mod.load(out_path)

    rep.update({
        "bone_tracks": len(base.bone_tracks),
        "morph_tracks": len(base.morph_tracks),
        "final_range": list(base.frame_range),
        "bytes_final": base.bytes_total,
    })
    if pmx:
        from . import pmx as pmx_mod
        model = pmx_mod.load(pmx)
        hit = sum(1 for n in base.morph_tracks if n in model.morph_names)
        rep["morph_hit"] = hit
        rep["morph_total"] = len(base.morph_tracks)

    if verbose:
        print("拼接 → %s" % rep["out"])
        for s in rep["spans"]:
            print("  %-34s 源 %d..%d  +%d → 时间轴 %d..%d  (%d 骨帧 / %d 表情帧)"
                  % (s["path"].split("/")[-1][:34], s["src_range"][0], s["src_range"][1],
                     s["offset"], s["dst_range"][0], s["dst_range"][1],
                     s["bone_records"], s["morph_records"]))
        print("  合计 骨骼 %d 条 / 表情 %d 条，帧范围 %d..%d，%.2f MB"
              % (rep["bone_records"], rep["morph_records"],
                 rep["final_range"][0], rep["final_range"][1], rep["bytes_final"] / 1048576))
        if rep.get("morph_total") is not None:
            print("  表情对模型 %d/%d" % (rep["morph_hit"], rep["morph_total"]))
        if rep["overlaps"]:
            print("  !! 时间轴有重叠：%s" % rep["overlaps"])
        if rep.get("explicit_truncated_frames"):
            print("  ! 显式截断：请求 %d 帧 < 时间轴 %d 帧（差分 %d 帧只渲前面，未丢段）"
                  % (rep["requested_render_frames"], rep["total_frames"],
                     rep["explicit_truncated_frames"]))
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mmdpipe.concatvmd")
    ap.add_argument("motions", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--gap", type=int, default=0, help="段间空帧数（默认 0）")
    ap.add_argument("--offsets", help="逗号分隔的起始帧，给就按它排，不给自动接")
    ap.add_argument("--model-name")
    ap.add_argument("--expression", help="拼接后再合并表情")
    ap.add_argument("--expression-offset", type=int, default=0,
                    help="表情段整体帧偏移（多段拼接时填它所属那段的 offset）")
    ap.add_argument("--pmx", help="用于表情覆盖检查")
    ap.add_argument("--frames", type=int,
                    help="计划渲染帧数：仅用于把显式截断和丢段分开记账")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    try:
        rep = concat_vmd(args.motions, args.out,
                         offsets=args.offsets.split(",") if args.offsets else None,
                         gap=args.gap, model_name=args.model_name,
                         expression=args.expression, pmx=args.pmx,
                         expression_offset=args.expression_offset,
                         frames=args.frames)
    except (vmd_mod.VMDError, OSError) as exc:
        print("拼接失败：%s" % exc, file=sys.stderr)
        return 1
    if args.json:
        from .report import dump
        dump(rep, args.json)
    return 0 if not rep["overlaps"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
