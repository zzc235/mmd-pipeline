"""多动作拼接的 NLA 路线（需在 Blender 内运行）。

为什么不用字节拼接：混合与对齐需要"求值后的姿态"，而字节层只能搬关键帧。
这一层用 mmd_tools 自带的 use_nla + Blender 的 NLA 烘焙 + 官方 export_vmd，
每一样都是现成能力，不自己造。

对齐发生在**烘焙之前**、只改 B 那条轨道对应的 action：
B 的条带只覆盖 B 的区间，所以改它不可能漏到 A（这正是字节层做不到的）。

    blender -b -P mmdpipe/chain_nla.py -- --pmx M --a A --b B --out O [--gap 6] [--blend 6] [--align auto]
"""
from __future__ import annotations

import argparse
import os
import sys

import bpy
import addon_utils

try:                       # 作为包的一部分（Blender 扩展里是 mmd_pipeline.mmdpipe）
    from . import vmd as vmd_mod
    from . import align as align_mod
except ImportError:        # 作为独立脚本跑：blender -b -P mmdpipe/chain_nla.py
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from mmdpipe import vmd as vmd_mod
    from mmdpipe import align as align_mod

SCALE = 0.08
MEASURE_BONE = "センター"


def _fresh_scene():
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end, sc.frame_current = 1, 250, 1
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    return sc


def _import_model(pmx):
    before = set(o.name for o in bpy.data.objects)
    bpy.ops.mmd_tools.import_model(filepath=pmx, scale=SCALE,
                                   types={"MESH", "ARMATURE"}, clean_model=True,
                                   rename_bones=True, log_level="ERROR")
    new = [bpy.data.objects[n] for n in set(o.name for o in bpy.data.objects) - before]
    root = next(o for o in new if getattr(o, "mmd_type", None) == "ROOT")
    arm = max([o for o in new if o.type == "ARMATURE"], key=lambda o: len(o.data.bones))
    return root, arm


def _import_vmd_nla(root, path, at_frame):
    sc = bpy.context.scene
    sc.frame_current = at_frame
    bpy.ops.object.select_all(action="DESELECT")
    root.select_set(True)
    bpy.context.view_layer.objects.active = root
    bpy.ops.mmd_tools.import_vmd(filepath=path, scale=SCALE, bone_mapper="PMX",
                                 rename_bones=True, use_underscore=False,
                                 use_nla=True, update_scene_settings=False)


def _world_head(arm, frame, bone):
    bpy.context.scene.frame_set(int(frame))
    # 必须强制求值：NLA 刚建好时 pose 矩阵会滞后一帧/一次更新，
    # 直接读会拿到上一状态（实测坐标系都对不上：高度跑到 Z 轴）。
    bpy.context.view_layer.update()
    pb = arm.pose.bones.get(bone)
    if pb is None:
        return None
    return (arm.matrix_world @ pb.matrix).translation.copy()


def _local_basis(arm, bone):
    """数值标定：把该骨 pose.location 沿局部三轴各推 1，量世界响应。

    比推导更可靠——骨静置基、父链、约束全被自动算进去。
    返回 3x3（世界位移 = M @ 局部位移）。
    """
    from mathutils import Matrix
    sc = bpy.context.scene
    pb = arm.pose.bones[bone]
    saved = pb.location.copy()
    base = (arm.matrix_world @ pb.matrix).translation.copy()
    cols = []
    for i in range(3):
        v = saved.copy()
        v[i] += 1.0
        pb.location = v
        bpy.context.view_layer.update()
        cols.append(((arm.matrix_world @ pb.matrix).translation - base).copy())
    pb.location = saved
    bpy.context.view_layer.update()
    return Matrix(((cols[0].x, cols[1].x, cols[2].x),
                   (cols[0].y, cols[1].y, cols[2].y),
                   (cols[0].z, cols[1].z, cols[2].z)))


def _shift_b_action(arm, action, bone_name, local_delta, frame_lo, frame_hi):
    """把 local_delta 加到 B 的 action 上该骨的位置曲线上（只影响 B 的区间）。"""
    from mathutils import Vector
    d = Vector(local_delta)
    path = 'pose.bones["%s"].location' % bone_name
    fcurves = {}
    for i in range(3):
        fc = action.fcurves.find(path, index=i)
        if fc is None:
            fc = action.fcurves.new(path, index=i, action_group=bone_name)
        fcurves[i] = fc
    any_key = False
    for i, fc in fcurves.items():
        if len(fc.keyframe_points):
            any_key = True
        for kp in fc.keyframe_points:
            kp.co[1] += d[i]
    if not any_key:
        for i, fc in fcurves.items():
            fc.keyframe_points.insert(frame_lo, d[i], options={"FAST"})
            fc.keyframe_points.insert(frame_hi, d[i], options={"FAST"})
    for fc in fcurves.values():
        fc.update()
    return len(fcurves[0].keyframe_points)


def _inject_bone(arm, measure):
    bone = arm.data.bones.get(measure)
    seen = 0
    while bone is not None and bone.parent is not None and seen < len(arm.data.bones):
        bone = bone.parent
        seen += 1
    return bone.name if bone else measure


def _measure_and_align(arm, action_b, a_last, b_first, mode):
    """在烘焙前量 A 末 / B 首的世界根位置，判定并对齐。"""
    if mode == "none":
        return {"mode": "none", "reason": "显式关闭对齐"}
    mb = MEASURE_BONE if MEASURE_BONE in arm.pose.bones else next(iter(arm.pose.bones)).name
    wa = _world_head(arm, a_last, mb)
    wb = _world_head(arm, b_first, mb)
    if wa is None or wb is None:
        return {"mode": "skip", "reason": "取不到测量骨 %s" % mb}

    feet = [n for n in ("足首.L", "足首.R", "足首", "つま先.L", "つま先.R")
            if n in arm.pose.bones]
    fa = [_world_head(arm, a_last, n) for n in feet]
    fb = [_world_head(arm, b_first, n) for n in feet]
    feet_delta = max(((b - a).length * 1000.0 for a, b in zip(fa, fb) if a and b),
                     default=0.0)

    world_delta = wb - wa
    plan = align_mod.AlignmentPlan(
        a_frame=int(a_last), b_frame=int(b_first),
        measure_bone=mb, inject_bone=_inject_bone(arm, mb),
        world_delta_mm=round(world_delta.length * 1000.0, 2),
        feet_delta_mm=round(feet_delta, 2),
    )
    align_mod.decide(plan)
    if mode == "match":
        plan.mode = align_mod.MATCH
        plan.reason = "用户显式指定 match"
    if plan.mode != align_mod.MATCH:
        return {"mode": plan.mode, "reason": plan.reason,
                "measure_bone": mb, "world_delta_mm": plan.world_delta_mm,
                "feet_delta_mm": plan.feet_delta_mm,
                "a_pos": [round(v, 4) for v in wa], "b_pos": [round(v, 4) for v in wb]}

    inject = plan.inject_bone
    M = _local_basis(arm, inject)
    try:
        local_delta = M.inverted() @ (-world_delta)   # B 往回走，使首帧与 A 末重合
    except ValueError:
        return {"mode": "skip", "reason": "局部基不可逆（%s），跳过注入" % inject}
    keys = _shift_b_action(arm, action_b, inject, local_delta, b_first, b_first + 300)
    return {
        "mode": plan.mode, "reason": plan.reason, "measure_bone": mb,
        "inject_bone": inject,
        "world_delta_mm": plan.world_delta_mm, "feet_delta_mm": plan.feet_delta_mm,
        "a_pos": [round(v, 4) for v in wa], "b_pos": [round(v, 4) for v in wb],
        "local_delta": [round(v, 5) for v in local_delta],
        "keys_touched": keys,
    }


def concat_via_nla(pmx, a_path, b_path, out_path, gap=6, blend=0,
                   align="auto", verbose=True):
    """两段动作 → NLA 分层 →（可选）根链对齐 → 交叉淡化 → 烘焙 → 导出 VMD。"""
    addon_utils.enable("mmd_tools", default_set=True, persistent=True)
    _fresh_scene()
    root, arm = _import_model(pmx)

    a_end_src = vmd_mod.load(a_path).frame_range[1]
    a_last = a_end_src + 1                 # VMD f → Blender f+1（mmd_tools margin 默认 0）
    b_first = a_last + 1 + gap
    b_len = vmd_mod.load(b_path).frame_range[1]
    b_last = b_first + b_len

    _import_vmd_nla(root, a_path, 1)
    _import_vmd_nla(root, b_path, b_first)

    tracks = arm.animation_data.nla_tracks
    for i, t in enumerate(tracks):
        for s in t.strips:
            s.blend_type = "REPLACE"
            s.extrapolation = "HOLD" if i == 0 else "NOTHING"

    action_b = tracks[-1].strips[0].action
    align_rep = _measure_and_align(arm, action_b, a_last, b_first, align)
    if verbose:
        print("  对齐：%s" % align_rep)

    if blend > 0:
        upper = tracks[-1].strips[0]
        target = a_last + 1
        shift = int(upper.frame_start - target)
        if shift > 0:
            upper.action_frame_start -= shift
            upper.action_frame_end -= shift
            upper.frame_start = target
            upper.blend_in = shift
            if verbose:
                print("  上层延伸 %d 帧 → f%d，blend_in=%d" % (shift, target, shift))

    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = int(b_last)
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.select_all(action="SELECT")
    bpy.ops.nla.bake(frame_start=1, frame_end=int(b_last), step=1,
                     only_selected=False, visual_keying=True,
                     clear_constraints=False, clear_parents=False,
                     use_current_action=True, bake_types={"POSE"})
    bpy.ops.object.mode_set(mode="OBJECT")
    action = arm.animation_data.action
    fcurves = len(action.fcurves) if action else 0

    # 复位场景帧位：mmd_tools 的 import_vmd 以 frame_current 为起点，
    # 留下来会让后续导入的动作整体平移（实测变 [454,1286]）。
    bpy.context.scene.frame_current = 1
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    bpy.ops.mmd_tools.export_vmd(filepath=out_path, scale=1.0 / SCALE)
    if verbose:
        print("  BAKE %s fcurves=%d → %s" % (action.name if action else "-", fcurves, out_path))
    return {"out": out_path, "a_last": a_last, "b_first": b_first,
            "frame_range": [0, int(b_last) - 1], "fcurves": fcurves,
            "segments": 2, "gap": gap, "blend": blend, "align": align_rep}


def main(argv=None):
    argv = argv if argv is not None else (sys.argv[sys.argv.index("--") + 1:]
                                          if "--" in sys.argv else sys.argv[1:])
    ap = argparse.ArgumentParser(prog="mmdpipe.chain_nla")
    ap.add_argument("--pmx", required=True)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--gap", type=int, default=6)
    ap.add_argument("--blend", type=int, default=0)
    ap.add_argument("--align", choices=["auto", "none", "match"], default="auto")
    args = ap.parse_args(argv)
    rep = concat_via_nla(args.pmx, args.a, args.b, args.out,
                         gap=args.gap, blend=args.blend, align=args.align)
    print("NLA_OK %s" % rep["out"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
