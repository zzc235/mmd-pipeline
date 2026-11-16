"""一次性探针：`rebuild_import.blend1`（v3 覆盖保存时轮转出来的上一版，93 719 B）里到底有什么。

    blender -b -P m02_probe_blend.py -- <blend> <out.json>
"""
import json
import os
import sys

import bpy


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    path, out_path = argv[0], argv[1]
    bpy.ops.wm.open_mainfile(filepath=path)
    sc = bpy.context.scene
    rig = [o for o in bpy.data.objects if getattr(o, "rigid_body", None) is not None]
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    types = {}
    for o in bpy.data.objects:
        types[o.type] = types.get(o.type, 0) + 1
    out = {"blend": path,
           "objects": len(bpy.data.objects),
           "objects_by_type": types,
           "rigids": len(rig),
           "rigidbody_world": sc.rigidbody_world is not None,
           "frame_end": sc.frame_end,
           "armatures": {a.name: {"bones": len(a.data.bones),
                                  "verts": sum(len(m.data.vertices) for m in a.children
                                               if m.type == "MESH" and m.data)}
                         for a in arms}}
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("PROBE " + json.dumps(out, ensure_ascii=False))
    sys.stdout.flush()
    os._exit(0)


main()
