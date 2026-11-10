"""社区路线最小验证：两条 VMD 用 NLA 叠加 → 烘焙 → export_vmd。

    blender -b -P nla_concat.py -- --pmx .. --a .. --b .. --gap 6 --out out/nla_chain.vmd
"""
import os
import sys
import argparse

import bpy
import addon_utils

sys.path.insert(0, r"E:/dsh pr/woker2")
from mmdpipe import vmd as V


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--pmx", required=True)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--gap", type=int, default=6)
    ap.add_argument("--out", required=True)
    ap.add_argument("--blend", type=int, default=0, help="交叉淡化帧数（0=不淡化）")
    return ap.parse_args(argv)


def main():
    a = args()
    addon_utils.enable("mmd_tools", default_set=True, persistent=True)
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end, sc.frame_current = 1, 250, 1
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)

    before = set(o.name for o in bpy.data.objects)
    bpy.ops.mmd_tools.import_model(filepath=a.pmx, scale=0.08,
                                   types={"MESH", "ARMATURE"}, clean_model=True,
                                   rename_bones=True, log_level="ERROR")
    new = [bpy.data.objects[n] for n in set(o.name for o in bpy.data.objects) - before]
    root = next(o for o in new if getattr(o, "mmd_type", None) == "ROOT")
    arm = max([o for o in new if o.type == "ARMATURE"], key=lambda o: len(o.data.bones))

    a_end_src = V.load(a.a).frame_range[1]
    a_last = a_end_src + 1          # VMD 0..N → Blender 1..N+1
    b_first = a_last + 1 + a.gap

    def imp(path, at):
        sc.frame_current = at
        bpy.ops.object.select_all(action="DESELECT")
        root.select_set(True)
        bpy.context.view_layer.objects.active = root
        bpy.ops.mmd_tools.import_vmd(filepath=path, scale=0.08, bone_mapper="PMX",
                                     rename_bones=True, use_underscore=False,
                                     use_nla=True, update_scene_settings=False)

    imp(a.a, 1)
    imp(a.b, b_first)
    b_end = b_first + V.load(a.b).frame_range[1]

    tracks = arm.animation_data.nla_tracks
    print("NLA 轨道 %d" % len(tracks))
    for t in tracks:
        for s in t.strips:
            print("  %-24s (%.0f, %.0f) blend=%s extrap=%s"
                  % (s.name, s.frame_start, s.frame_end, s.blend_type, s.extrapolation))

    # 关键：下层（A）HOLD 让末姿态延续过 gap；上层（B）必须 NOTHING，
    # 否则 B 的 HOLD 外插会向回覆盖整段 A（第一次就踩了这个，A 段被冻成 B 首帧）。
    for i, t in enumerate(tracks):
        for s in t.strips:
            s.blend_type = "REPLACE"
            s.extrapolation = "HOLD" if i == 0 else "NOTHING"
    if a.blend > 0:
        # 把上层条带向前延伸覆盖 gap：内容靠 action_frame_* 同步前移，
        # 这样它的第 0 帧仍落在 b_first，而 448..453 变成"淡入区"。
        upper = tracks[-1].strips[0]
        target_start = a_last + 1
        shift = int(upper.frame_start - target_start)
        if shift > 0:
            upper.action_frame_start -= shift
            upper.action_frame_end -= shift
            upper.frame_start = target_start
            upper.blend_in = shift
            print("  上层延伸 %d 帧到 f%d，blend_in=%d；action 区间 (%.0f, %.0f)"
                  % (shift, target_start, shift,
                     upper.action_frame_start, upper.action_frame_end))
        else:
            upper.blend_in = a.blend
            print("  上层 blend_in = %d" % a.blend)

    sc.frame_start, sc.frame_end = 1, int(b_end)
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.select_all(action="SELECT")
    bpy.ops.nla.bake(frame_start=1, frame_end=int(b_end), step=1,
                     only_selected=False, visual_keying=True,
                     clear_constraints=False, clear_parents=False,
                     use_current_action=True, bake_types={"POSE"})
    bpy.ops.object.mode_set(mode="OBJECT")

    act = arm.animation_data.action
    print("BAKE action=%s range=%s fcurves=%d"
          % (act.name if act else None,
             tuple(act.frame_range) if act else None,
             len(act.fcurves) if act else 0))

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    bpy.ops.mmd_tools.export_vmd(filepath=a.out)
    print("EXPORT -> %s" % a.out)
    print("RESULT %s" % a.out)


if __name__ == "__main__":
    main()
