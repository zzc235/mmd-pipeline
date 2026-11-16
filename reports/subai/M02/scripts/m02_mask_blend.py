"""掩码对照的 Blender 侧：导出每个刚体的 `mmd_rigid.collision_group_number` 与
`rigid_body.collision_collections` 位。

    blender -b -P m02_mask_blend.py -- <blend> <out.json>
"""
import json
import os
import sys

import bpy


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    path, out_path = argv[0], argv[1]
    bpy.ops.wm.open_mainfile(filepath=path)
    rows = {}
    for ob in bpy.data.objects:
        rb = getattr(ob, "rigid_body", None)
        if rb is None:
            continue
        mmd = getattr(ob, "mmd_rigid", None)
        rows[ob.name] = {"mmd_group": int(mmd.collision_group_number) if mmd else None,
                         "bits": [i for i, v in enumerate(rb.collision_collections) if v],
                         "bitwidth": len(rb.collision_collections),
                         "type": rb.type, "kinematic": bool(rb.kinematic),
                         "shape": rb.collision_shape}
    out = {"blend": path, "count": len(rows), "rows": rows}
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("MASK_BLEND count=%d bitwidth=%s"
          % (len(rows), sorted({r["bitwidth"] for r in rows.values()})))
    sys.stdout.flush()
    os._exit(0)


main()
