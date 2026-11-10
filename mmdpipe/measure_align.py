"""根链对齐测量（需在 Blender 里跑，因为世界变换要真实骨架）。

    blender -b -P mmdpipe/measure_align.py -- --pmx 模型.pmx --a A.vmd --b B.vmd [--gap 6] [--json plan.json]

做法：先把两段按 gap 拼成一条时间轴，再导入采样 A 末与 B 首两个帧。
**必须在拼接后的时间轴上测**——分开导入时，某段没有被动画的骨会落到 rest 姿势，
量出来的是"两段姿势差"，不是"交接处真实跳变"（实测差 350mm vs 19mm）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import bpy
import addon_utils

try:                       # 包内（扩展）优先，独立脚本回退
    from . import align as align_mod
    from . import vmd as vmd_mod
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from mmdpipe import align as align_mod
    from mmdpipe import vmd as vmd_mod

SCALE = 0.08
FEET = ("足首.L", "足首.R", "つま先.L", "つま先.R", "足首", "つま先")
DEFORM = ("下半身", "上半身", "上半身2", "腰", "首", "頭", "センター", "グルーブ",
          "左足", "右足", "左ひざ", "右ひざ", "左腕", "右腕")


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--pmx", required=True)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--gap", type=int, default=6)
    ap.add_argument("--json")
    ap.add_argument("--tmp", default="E:/dsh pr/woker2/out/_align_probe.vmd")
    return ap.parse_args(argv)


def _import_model(pmx):
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    before = set(o.name for o in bpy.data.objects)
    bpy.ops.mmd_tools.import_model(filepath=pmx, scale=0.08,
                                   types={"MESH", "ARMATURE"}, clean_model=True,
                                   rename_bones=True, log_level="ERROR")
    new = [bpy.data.objects[n] for n in set(o.name for o in bpy.data.objects) - before]
    root = next(o for o in new if getattr(o, "mmd_type", None) == "ROOT")
    return root, bpy.data.objects[root.name + "_arm"]


def _snap(arm, names, frame):
    bpy.context.scene.frame_set(frame)
    out = {}
    for n in names:
        pb = arm.pose.bones.get(n)
        if pb:
            m = arm.matrix_world @ pb.matrix
            out[n] = (m.translation.copy(), m.to_quaternion())
    return out


def main():
    args = _args()
    addon_utils.enable("mmd_tools", default_set=True, persistent=True)

    rep = vmd_mod.concat([vmd_mod.load(args.a), vmd_mod.load(args.b)],
                         args.tmp, gap=args.gap)
    a_end = rep["spans"][0]["dst_range"][1]
    b_start = rep["spans"][1]["dst_range"][0]

    root, arm = _import_model(args.pmx)
    bpy.ops.object.select_all(action="DESELECT")
    root.select_set(True)
    bpy.context.view_layer.objects.active = root
    bpy.ops.mmd_tools.import_vmd(filepath=args.tmp, scale=0.08, bone_mapper="PMX",
                                 rename_bones=True, use_underscore=False,
                                 update_scene_settings=True)

    names = DEFORM + FEET
    # mmd_tools 把 VMD 帧 f 导入到 Blender 帧 f+1，采样必须 +1，否则采到插值中间
    sa = _snap(arm, names, a_end + 1)
    sb = _snap(arm, names, b_start + 1)

    common = [n for n in names if n in sa and n in sb]
    deltas = {n: (sb[n][0] - sa[n][0]).length * 1000.0 for n in common}
    feet = [deltas[n] for n in FEET if n in deltas]
    feet_max = max(feet) if feet else 0.0
    ordered = sorted(deltas.values())

    def median(v):
        if not v:
            return 0.0
        k = len(v) // 2
        return v[k] if len(v) % 2 else (v[k - 1] + v[k]) / 2.0

    measure = "センター" if "センター" in deltas else (common[0] if common else "")
    heading = 0.0
    if measure in sa and measure in sb:
        import math
        r = sb[measure][1] @ sa[measure][1].inverted()
        heading = math.degrees(r.to_euler().z)

    inject = measure
    cur = arm.data.bones.get(measure)
    seen = 0
    while cur is not None and cur.parent is not None and seen < len(arm.data.bones):
        inject = cur.parent.name
        cur = cur.parent
        seen += 1

    t = [0.0, 0.0, 0.0]
    t_model = [0.0, 0.0, 0.0]
    if measure in sa and measure in sb:
        # 修正量：要加到 B 上，使 B 首帧与 A 末帧重合
        t = [sa[measure][0][i] - sb[measure][0][i] for i in range(3)]
        # 实测标定得出的基变换（calibrate_align.py 三轴探针）：
        #     world = SCALE * swapYZ(vmd)   →   vmd = swapYZ(world) / SCALE
        # 不是 R⁻¹：骨的静置基不等于这个映射（实测第三分量符号会反、缩放会丢）。
        t_model = [t[0] / SCALE, t[2] / SCALE, t[1] / SCALE]
        t = [round(v, 6) for v in t]
        t_model = [round(v, 6) for v in t_model]

    plan = align_mod.AlignmentPlan(
        a_path=args.a, b_path=args.b, a_frame=a_end, b_frame=b_start,
        measure_bone=measure, inject_bone=inject,
        world_delta_mm=round(deltas.get(measure, 0.0), 2),
        global_median_mm=round(median(ordered), 2),
        feet_delta_mm=round(feet_max, 2),
        heading_deg=round(heading, 2), t=t, t_model=t_model,
        evidence={"per_bone_mm": {k: round(v, 1) for k, v in deltas.items()},
                  "gap": args.gap, "timeline": [a_end, b_start]},
    )
    align_mod.decide(plan)

    print("MEASURE  %s | 时间轴 A末 f%d  B首 f%d | gap %d"
          % (measure, a_end, b_start, args.gap))
    print("  world %.1f mm | feet %.1f mm | median %.1f mm | heading %.1f°"
          % (plan.world_delta_mm, plan.feet_delta_mm, plan.global_median_mm,
             plan.heading_deg))
    print("  inject %s | t_world %s | t_model %s"
          % (plan.inject_bone, plan.t, plan.t_model))
    print("  MODE   %s" % plan.mode)
    print("  REASON %s" % plan.reason)
    for k in sorted(deltas, key=lambda x: -deltas[x])[:5]:
        print("    %-10s %7.1f mm" % (k, deltas[k]))

    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)) or ".", exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(plan.as_dict(), fh, ensure_ascii=False, indent=2)
        print("PLAN_WRITTEN %s" % args.json)


if __name__ == "__main__":
    main()
