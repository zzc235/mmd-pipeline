"""刚体约束清单：`RigidBodyConstraint` 按 `type` 计数（回答「PMX 的 disable_collisions 有没有
在 Blender 侧落成 DISABLE_COLLISIONS 约束」）。

    blender -b -P m02_constraint_inventory.py -- <blend> <out.json>
"""
import json
import os
import sys

import bpy


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    path, out_path = argv[0], argv[1]
    bpy.ops.wm.open_mainfile(filepath=path)
    by_type, enabled_by_type, names = {}, {}, {"DISABLE_COLLISIONS": []}
    for ob in bpy.data.objects:
        rbc = getattr(ob, "rigid_body_constraint", None)
        if rbc is None:
            continue
        kind = str(getattr(rbc, "type", "?"))
        by_type[kind] = by_type.get(kind, 0) + 1
        if getattr(rbc, "enabled", True):
            enabled_by_type[kind] = enabled_by_type.get(kind, 0) + 1
        if kind == "DISABLE_COLLISIONS":
            names["DISABLE_COLLISIONS"].append({"object": ob.name,
                                                "enabled": bool(getattr(rbc, "enabled", True)),
                                                "object1": getattr(rbc, "object1", None).name
                                                if getattr(rbc, "object1", None) else None,
                                                "object2": getattr(rbc, "object2", None).name
                                                if getattr(rbc, "object2", None) else None})
    rigid_objs = [o for o in bpy.data.objects if getattr(o, "rigid_body", None) is not None]
    bits = {}
    for ob in rigid_objs:
        rb = ob.rigid_body
        on = tuple(i for i, v in enumerate(rb.collision_collections) if v)
        bits[on] = bits.get(on, 0) + 1
    out = {"blend": path, "rigid_bodies": len(rigid_objs),
           "constraint_types_total": by_type, "constraint_types_enabled": enabled_by_type,
           "disable_collisions": names["DISABLE_COLLISIONS"],
           "collision_collections_histogram": {"|".join(map(str, k)) or "none": v
                                               for k, v in sorted(bits.items())}}
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("CONSTRAINTS " + json.dumps({"total": by_type,
                                       "disable_collisions": len(names["DISABLE_COLLISIONS"]),
                                       "collision_bits": out["collision_collections_histogram"]},
                                      ensure_ascii=False))
    sys.stdout.flush()
    os._exit(0)


main()
