"""M02 阶段 C 前置：在候选基线工程里核「18 个 rot X = ±π/2 的根部关节」是否与 PMX 结构筛出一致。

    blender -b -P m02_check_joints.py -- <scene.blend> <s2_targets.json> <out.json>

只读，不 save。判据是**约束上的限位值**（Blender 侧真正驱动物理的量），不是对象名。

输出 out.json：
  {"blend": ..., "structural_joints": [...], "pmx_targets": [...],
   "match": bool, "only_in_blend": [...], "only_in_pmx": [...], "limit_summary": {...}}
"""
import json
import os
import re
import sys

import bpy

HALF_PI = 1.5707963267948966
TOL = 0.01
# Blender 里关节对象名带序号前缀：`006_J.下擺_0_0`；PMX 侧是 `下擺_0_0`
PREFIX = re.compile(r"^\d+_J\.")


def normalize(name: str) -> str:
    return PREFIX.sub("", name)


def parse_argv():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) < 3:
        raise SystemExit("usage: m02_check_joints.py -- scene.blend s2_targets.json out.json")
    return argv[0], argv[1], argv[2]


def main():
    blend, targets_path, out_path = parse_argv()
    with open(targets_path, encoding="utf-8") as fh:
        pmx_targets = [t["joint_name"] for t in json.load(fh)["targets"]]

    bpy.ops.wm.open_mainfile(filepath=blend)
    joints = [o for o in bpy.data.objects if getattr(o, "rigid_body_constraint", None)]

    structural, limit_rows = [], []
    for ob in joints:
        rbc = ob.rigid_body_constraint
        lo, hi = rbc.limit_ang_x_lower, rbc.limit_ang_x_upper
        if abs(abs(lo) - HALF_PI) < TOL and abs(abs(hi) - HALF_PI) < TOL:
            structural.append(ob.name)
            limit_rows.append({"object": ob.name, "limit_ang_x_lower": lo,
                               "limit_ang_x_upper": hi})

    only_blend = sorted(set(normalize(n) for n in structural) - set(pmx_targets))
    only_pmx = sorted(set(pmx_targets) - set(normalize(n) for n in structural))
    result = {
        "task": "M02",
        "stage": "C-precheck",
        "blend": blend,
        "scene": {
            "name": bpy.context.scene.name,
            "frame_start": bpy.context.scene.frame_start,
            "frame_end": bpy.context.scene.frame_end,
            "fps": bpy.context.scene.render.fps / bpy.context.scene.render.fps_base,
            "armatures": [o.name for o in bpy.data.objects if o.type == "ARMATURE"],
            "actions": [a.name for a in bpy.data.actions],
            "rigid_body_objects": len([o for o in bpy.data.objects
                                       if getattr(o, "rigid_body", None)]),
            "rigid_body_world": bool(bpy.context.scene.rigidbody_world),
            "cache_frames": (
                [bpy.context.scene.rigidbody_world.point_cache.frame_start,
                 bpy.context.scene.rigidbody_world.point_cache.frame_end]
                if bpy.context.scene.rigidbody_world else None),
        },
        "criterion": "rigid_body_constraint.limit_ang_x_lower/upper 的绝对值都落在 π/2 的 ±0.01 内",
        "joint_objects_total": len(joints),
        "structural_joints": sorted(structural),
        "structural_normalized": sorted(normalize(n) for n in structural),
        "name_rule": "Blender 关节对象名 = `<序号>_J.<PMX 关节名>`；比较时剥离前缀",
        "pmx_targets": sorted(pmx_targets),
        "match": (len(structural) == len(pmx_targets)) and not only_blend and not only_pmx,
        "only_in_blend": only_blend,
        "only_in_pmx": only_pmx,
        "limit_rows": limit_rows,
    }
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("CHECK match=%s structural=%d pmx=%d only_blend=%d only_pmx=%d"
          % (result["match"], len(structural), len(pmx_targets),
             len(only_blend), len(only_pmx)))
    sys.stdout.flush()
    os._exit(0)


main()
