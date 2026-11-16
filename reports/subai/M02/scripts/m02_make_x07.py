"""M02 阶段 C：把 18 个根部关节的旋转 X 限位改成 ±0.7，另存为 s2_x07 副本。

    blender -b -P m02_make_x07.py -- <baseline_copy.blend> <out_x07.blend> <s2_targets.json> <out.json>

判据同 m02_check_joints.py：按**约束上限位值**（±π/2、容差 0.01）结构性定位，不按名字。
安全约定：只读入参工程，**只写 out_x07.blend 这一个新文件**；已存在则拒绝（不覆盖）。
"""
import json
import os
import re
import sys

import bpy

HALF_PI = 1.5707963267948966
TOL = 0.01
NEW_X = 0.7
PREFIX = re.compile(r"^\d+_J\.")


def parse_argv():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) < 4:
        raise SystemExit("usage: m02_make_x07.py -- baseline.blend out_x07.blend targets.json out.json")
    return argv[0], argv[1], argv[2], argv[3]


def main():
    src, dst, targets_path, out_path = parse_argv()
    if os.path.abspath(src) == os.path.abspath(dst):
        raise SystemExit("拒绝覆盖输入工程")
    if os.path.exists(dst):
        raise SystemExit("目标已存在，拒绝覆盖：%s" % dst)

    with open(targets_path, encoding="utf-8") as fh:
        pmx_targets = set(t["joint_name"] for t in json.load(fh)["targets"])

    bpy.ops.wm.open_mainfile(filepath=src)
    structural = []
    for ob in bpy.data.objects:
        rbc = getattr(ob, "rigid_body_constraint", None)
        if rbc is None:
            continue
        lo, hi = rbc.limit_ang_x_lower, rbc.limit_ang_x_upper
        if abs(abs(lo) - HALF_PI) < TOL and abs(abs(hi) - HALF_PI) < TOL:
            structural.append(ob)

    changed = []
    for ob in structural:
        rbc = ob.rigid_body_constraint
        before = [rbc.limit_ang_x_lower, rbc.limit_ang_x_upper]
        rbc.limit_ang_x_lower = -NEW_X
        rbc.limit_ang_x_upper = NEW_X
        changed.append({"object": ob.name, "before": before, "after": [rbc.limit_ang_x_lower,
                                                                     rbc.limit_ang_x_upper]})

    in_targets = sorted(set(PREFIX.sub("", o.name) for o in structural) & pmx_targets)
    result = {
        "task": "M02",
        "stage": "C-apply",
        "source_blend": src,
        "out_blend": dst,
        "structural_count": len(structural),
        "matched_pmx_targets": in_targets,
        "changed": changed,
        "new_x": NEW_X,
        "note": "只改 limit_ang_x_lower/upper；y/z 限位、弹簧、质量、阻尼一律不动",
    }
    os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=dst)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("APPLY structural=%d matched=%d -> %s"
          % (len(structural), len(in_targets), dst))
    sys.stdout.flush()
    os._exit(0)


main()
