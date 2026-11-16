"""M02 阶段 C 前置：确认 MMD 物理链是否已 build；未 build 就 build，另存 prepared 副本。

    blender -b -P m02_prepare_scene.py -- <in.blend> <out.blend> <out.json>

背景（历史工程自带 `关键发现_没有裙子只有飘带.md`，2026-11-06 实测）：
`mmd_root.is_built = False` 时物理链虽完整（刚体 → 骨骼 COPY_ROTATION），但**没 build 就不建约束**，
下擺骨停在初始姿态 —— 逐帧角度恒定，看起来像"模拟了但没变化"。必须先 build 才能谈动态对照。

安全约定：只写 out.blend（已存在则拒绝），不覆盖入参。
"""
import json
import os
import sys

import bpy

# 本机 mmd_tools 是扩展，模块名是 bl_ext.user_default.mmd_tools（不是短名）
from bl_ext.user_default.mmd_tools.core import model as MMDModel


def parse_argv():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) < 3:
        raise SystemExit("usage: m02_prepare_scene.py -- in.blend out.blend out.json")
    return argv[0], argv[1], argv[2]


def count_bone_constraints(arm):
    total = 0
    per_type = {}
    for pb in arm.pose.bones:
        for c in pb.constraints:
            total += 1
            per_type[c.type] = per_type.get(c.type, 0) + 1
    return total, per_type


def main():
    src, dst, out_path = parse_argv()
    if os.path.abspath(src) == os.path.abspath(dst):
        raise SystemExit("拒绝覆盖入参工程")
    if os.path.exists(dst):
        raise SystemExit("目标已存在，拒绝覆盖：%s" % dst)

    bpy.ops.wm.open_mainfile(filepath=src)
    # 严格按 mmd_type == "ROOT" 选根：非根对象也带有 mmd_root 结构（默认值），
    # 用 "有 mmd_root 属性" 当判据会选错对象（实测会抛 must be MMD ROOT type object）。
    roots = [o for o in bpy.data.objects if getattr(o, "mmd_type", None) == "ROOT"]
    if not roots:
        raise SystemExit("找不到 MMD root 对象，停止（不在不知道根对象的情况下乱 build）")
    root = roots[0]
    armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    arm = armatures[0]

    before_total, before_types = count_bone_constraints(arm)
    before_built = bool(root.mmd_root.is_built)

    built_now = False
    if not before_built:
        MMDModel.Model(root).build()
        built_now = True

    after_total, after_types = count_bone_constraints(arm)
    result = {
        "task": "M02",
        "stage": "C-prepare",
        "source_blend": src,
        "out_blend": dst,
        "mmd_root": root.name,
        "armature": arm.name,
        "is_built_before": before_built,
        "built_now": built_now,
        "is_built_after": bool(root.mmd_root.is_built),
        "bone_constraints_before": {"total": before_total, "by_type": before_types},
        "bone_constraints_after": {"total": after_total, "by_type": after_types},
        "rigid_body_objects": len([o for o in bpy.data.objects
                                   if getattr(o, "rigid_body", None)]),
        "scene_frames": [bpy.context.scene.frame_start, bpy.context.scene.frame_end],
    }
    bpy.ops.wm.save_as_mainfile(filepath=dst)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("PREPARE built_before=%s built_now=%s bone_constraints %d -> %d out=%s"
          % (before_built, built_now, before_total, after_total, dst))
    sys.stdout.flush()
    os._exit(0)


main()
