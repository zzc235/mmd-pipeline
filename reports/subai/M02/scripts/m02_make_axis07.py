"""M02 · 轴对照实验：把 18 个根部关节的**指定轴**旋转限位收紧到 ±0.7。

    blender -b -P m02_make_axis07.py -- <in.blend> <out.blend> <s2_targets.json> <axis> <out.json>

axis ∈ {x, y, z}。判据仍是「该轴限位绝对值 ≈ π/2」的结构性定位（不按名字）。
动机：S2 任务书只给 X 轴（±1.571 → ±0.7），但实测 240 帧里 rot_x 从不超过 33.16°，
限位从未被触发 —— 需要判断真正在约束摆动的是哪一根轴。

安全约定：只写 out.blend（已存在则拒绝），不覆盖入参。
"""
import json
import os
import re
import sys

import bpy

HALF_PI = 1.5707963267948966
TOL = 0.01
NEW = 0.7
PREFIX = re.compile(r"^\d+_J\.")


def parse_argv():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) < 5:
        raise SystemExit("usage: m02_make_axis07.py -- in.blend out.blend targets.json <x|y|z> out.json")
    return argv[0], argv[1], argv[2], argv[3].lower(), argv[4]


def main():
    src, dst, targets_path, axis, out_path = parse_argv()
    if axis not in ("x", "y", "z"):
        raise SystemExit("axis 必须是 x/y/z")
    if os.path.abspath(src) == os.path.abspath(dst):
        raise SystemExit("拒绝覆盖入参工程")
    if os.path.exists(dst):
        raise SystemExit("目标已存在，拒绝覆盖：%s" % dst)

    with open(targets_path, encoding="utf-8") as fh:
        pmx_targets = set(t["joint_name"] for t in json.load(fh)["targets"])

    lo_name = "limit_ang_%s_lower" % axis
    hi_name = "limit_ang_%s_upper" % axis
    use_name = "use_limit_ang_%s" % axis

    bpy.ops.wm.open_mainfile(filepath=src)
    structural = []
    for ob in bpy.data.objects:
        rbc = getattr(ob, "rigid_body_constraint", None)
        if rbc is None:
            continue
        lo, hi = getattr(rbc, lo_name), getattr(rbc, hi_name)
        if abs(abs(lo) - HALF_PI) < TOL and abs(abs(hi) - HALF_PI) < TOL:
            structural.append(ob)

    changed = []
    for ob in structural:
        rbc = ob.rigid_body_constraint
        before = [getattr(rbc, lo_name), getattr(rbc, hi_name), getattr(rbc, use_name)]
        setattr(rbc, lo_name, -NEW)
        setattr(rbc, hi_name, NEW)
        setattr(rbc, use_name, True)
        changed.append({"object": PREFIX.sub("", ob.name), "before": before,
                        "after": [getattr(rbc, lo_name), getattr(rbc, hi_name),
                                  getattr(rbc, use_name)]})

    result = {
        "task": "M02",
        "stage": "C-axis-probe",
        "axis": axis,
        "source_blend": src,
        "out_blend": dst,
        "structural_count": len(structural),
        "matched_pmx_targets": sorted(set(PREFIX.sub("", o.name) for o in structural) & pmx_targets),
        "changed": changed,
        "new_limit_rad": NEW,
        "note": "只收紧指定轴的上下限并把该轴的 use_limit 置 True；其它轴、弹簧、质量、阻尼不动",
    }
    os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=dst)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("AXIS %s structural=%d matched=%d -> %s"
          % (axis, len(structural), len(result["matched_pmx_targets"]), dst))
    sys.stdout.flush()
    os._exit(0)


main()
