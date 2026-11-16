"""只读体检：一个 .blend 里到底有多少个刚体约束 / 刚体对象（排除「假装量过」）。

    blender -b <file> --python diag_census.py
"""

import collections
import sys

import bpy

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

objs = list(bpy.data.objects)
census = {
    "objects": len(objs),
    "rigid_body_constraint": sum(1 for x in objs if getattr(x, "rigid_body_constraint", None) is not None),
    "disable_true": sum(1 for x in objs
                        if getattr(x, "rigid_body_constraint", None) is not None
                        and getattr(x.rigid_body_constraint, "disable_collisions", False)),
    "rigid_body": sum(1 for x in objs if getattr(x, "rigid_body", None) is not None),
    "mmd_type_rigid": sum(1 for x in objs if getattr(x, "mmd_type", None) == "RIGID_BODY"),
    "type_enum_hit": sum(1 for x in objs if x.type == "RIGID_BODY_CONSTRAINT"),
    "types": collections.Counter(x.type for x in objs).most_common(8),
    "scene_objects": len(bpy.context.scene.objects),
    "filepath": bpy.data.filepath,
}
for key, value in census.items():
    print("CN %s = %r" % (key, value))
sys.stdout.flush()
