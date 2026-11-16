"""掩码在 Blender 侧到底有没有载荷（**必须在 enable 扩展之后读**）。

    blender -b -P m02_mask_probe_after_enable.py -- <blend> <out.json>

`mmd_rigid` 是 mmd_tools 注册的 RNA 属性：扩展没启用时 `dir(obj)` 里根本没有它，
读出来会像「这个场景没有 MMD 元数据」——那是假阴性（本文件就是因为踩了一次才写的）。
"""
import json
import os
import sys

import addon_utils
import bpy

EXTENSION = "bl_ext.user_default.mmd_tools"


def enable():
    trace = []
    for name in (EXTENSION, "mmd_tools"):
        try:
            value = addon_utils.enable(name, default_set=False, persistent=False)
            trace.append({"name": name, "ok": True, "value": str(value)})
        except Exception as exc:
            trace.append({"name": name, "ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
    try:
        bpy.ops.mmd_tools.import_model.get_rna_type()
        has_op = True
    except Exception:
        has_op = False
    return {"trace": trace, "operator_present": has_op}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    path, out_path = argv[0], argv[1]
    addon_state = enable()
    bpy.ops.wm.open_mainfile(filepath=path)

    rows = {}
    with_mask = 0
    for ob in bpy.data.objects:
        rb = getattr(ob, "rigid_body", None)
        if rb is None:
            continue
        mmd = getattr(ob, "mmd_rigid", None)
        entry = {"bits": [i for i, v in enumerate(rb.collision_collections) if v],
                 "has_mmd_rigid": mmd is not None}
        if mmd is not None:
            with_mask += 1
            entry["mmd_group"] = int(mmd.collision_group_number)
            entry["mmd_mask"] = [i for i, v in enumerate(mmd.collision_group_mask) if v]
            entry["mmd_mask_int"] = sum(1 << i for i, v in enumerate(mmd.collision_group_mask) if v)
        rows[ob.name] = entry

    constraints = {}
    for ob in bpy.data.objects:
        rbc = getattr(ob, "rigid_body_constraint", None)
        if rbc is None:
            continue
        kind = str(getattr(rbc, "type", "?"))
        constraints[kind] = constraints.get(kind, 0) + 1

    out = {"blend": path, "addon": addon_state, "rigid_objects": len(rows),
           "objects_with_mmd_rigid": with_mask,
           "rigidbody_constraint_types": constraints,
           "rows": rows}
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("MASKPROBE addon=%s rigid=%d with_mmd_rigid=%d constraints=%s"
          % (addon_state["operator_present"], len(rows), with_mask,
             json.dumps(constraints, ensure_ascii=False)))
    sys.stdout.flush()
    os._exit(0)


main()
