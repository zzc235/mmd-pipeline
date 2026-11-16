# -*- coding: utf-8 -*-
"""只读：把交付件里「PMX 没有的 12 个刚体」逐条读出来（名字/父骨/尺寸/质量/组/掩码/模式/位置）。

为什么：`324 − 312 = 12`，纯 Python 只能算出名字（`$name_j*` 11 个 + `地面_物理`），
说不出它们**在物理上是什么**。判断「缺了它们对 C/D 有没有影响」需要这 12 行的属性，
所以这一步必须在 Blender 里读——但仍然只读，不改场景、不存盘。

退出码：0 成功；3 失败。
"""

import json
import os
import sys
import traceback

import bpy                                            # noqa: E402
import addon_utils                                    # noqa: E402

WANT = ["$name_j"] + ["$name_j.%03d" % i for i in range(1, 11)] + ["地面_物理"]


def enable_mmd_tools():
    for mod in addon_utils.modules():
        if "mmd_tools" in getattr(mod, "__name__", ""):
            addon_utils.enable(mod.__name__, default_set=True, handle_error=None)
            return mod.__name__
    return None


def obj_row(obj):
    rb = getattr(obj, "rigid_body", None)
    row = {"name": obj.name, "type": obj.type,
           "mmd_type": getattr(obj, "mmd_type", None),
           "parent": obj.parent.name if obj.parent else None,
           "parent_bone": obj.parent_bone or None,
           "location": [round(v, 6) for v in obj.location],
           "rigid_body": rb is not None}
    if rb is not None:
        row.update({
            "mass": round(float(rb.mass), 6),
            "friction": round(float(rb.friction), 6),
            "restitution": round(float(rb.restitution), 6),
            "kinematic": bool(rb.kinematic),
            "collision_shape": str(rb.collision_shape),
            "collision_collections": [int(b) for b in rb.collision_collections],
            "collision_margin": round(float(rb.collision_margin), 6),
            "linear_damping": round(float(rb.linear_damping), 6),
            "angular_damping": round(float(rb.angular_damping), 6),
            "use_margin": bool(rb.use_margin),
        })
    rig = getattr(obj, "mmd_rigid", None)
    if rig is not None:
        try:
            row["mmd_rigid"] = {"group": int(rig.group), "mask": int(rig.collision_group_mask),
                                "shape": int(rig.shape), "mode": int(rig.mode),
                                "mass": round(float(rig.mass), 6)}
        except Exception:                              # noqa: BLE001
            row["mmd_rigid"] = "unreadable"
    return row


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out_path = argv[0] if argv else "extra_bodies.json"
    try:
        rec = {"blend": os.path.abspath(bpy.data.filepath), "addon_enabled": enable_mmd_tools(),
               "rows": []}
        by_name = {}
        for o in bpy.data.objects:
            by_name[o.name] = o
            # 交付件里对象名带 `NNN_` 前缀（`000_$name_j`），去前缀后再索引一次
            if len(o.name) > 4 and o.name[:3].isdigit() and o.name[3] == "_":
                by_name.setdefault(o.name[4:], o)
        for name in WANT:
            obj = by_name.get(name)
            rec["rows"].append(obj_row(obj) if obj is not None else
                               {"name": name, "missing_in_this_blend": True})
        rec["count_found"] = sum(1 for r in rec["rows"] if "missing_in_this_blend" not in r)
        rec["rigids_total"] = len([o for o in bpy.data.objects
                                   if getattr(o, "rigid_body", None) is not None])
        with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(rec, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
        print("EXTRA_BODIES %s  found=%d rigids_total=%d"
              % (out_path, rec["count_found"], rec["rigids_total"]))
        return 0
    except BaseException:                              # noqa: BLE001
        traceback.print_exc()
        print("EXTRA_BODIES ERROR")
        return 3


if __name__ == "__main__":
    sys.exit(main())
