"""M02 · 骨↔刚体的全量映射（不依赖 mmd_tools 扩展），用于和 PMX 侧对账。

    blender -b -P m02_bone_rigid_map.py -- <scene.blend> <out.json>

做法：遍历每个 armature 的每个 pose bone 的约束，把 `target` 对象指到刚体对象的那些挑出来。
mmd_tools 的「物理骨」就是这种写法（COPY_ROTATION ← mmd_bonetrack.N），对象级 CHILD_OF 是另一类。
输出：{bone: [{armature, type, target_object, rigid_body_type}]} + 对象→刚体对象名清单。
"""
import hashlib
import json
import os
import sys

import addon_utils
import bpy


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) < 2:
        raise SystemExit("usage: m02_bone_rigid_map.py -- scene.blend out.json")
    src, out_path = argv[0], argv[1]
    sha_before = sha256_file(src)
    bpy.ops.wm.open_mainfile(filepath=src)

    # mmd_tools 是扩展：--background 下不注册，`o.mmd_rigid` 不存在。必须先显式启用。
    enabled = addon_utils.enable("bl_ext.user_default.mmd_tools")
    rigids = {o.name: o for o in bpy.data.objects if getattr(o, "rigid_body", None) is not None}
    bone_of = {}
    for name, o in rigids.items():
        mr = getattr(o, "mmd_rigid", None)
        bone_of[name] = mr.bone if mr is not None else None
    mapping = {}
    for arm in [o for o in bpy.data.objects if o.type == "ARMATURE"]:
        for pb in arm.pose.bones:
            for c in pb.constraints:
                tgt = getattr(c, "target", None)
                if tgt is None or tgt.name not in rigids:
                    continue
                mapping.setdefault(pb.name, []).append(
                    {"armature": arm.name, "type": c.type, "target_object": tgt.name,
                     "rigid_type": rigids[tgt.name].rigid_body.type})

    # 反向：刚体对象 → 指向它的骨
    rev = {}
    for bone, links in mapping.items():
        for ln in links:
            rev.setdefault(ln["target_object"], []).append(bone)

    out = {"stage": "bone-rigid-map", "in_blend": src,
           "in_blend_sha256": sha256_file(src),
           "source_untouched": sha_before == sha256_file(src),
           "never_saved_blend": True,
           "rigid_objects": len(rigids),
           "bones_with_rigid_links": len(mapping),
           "rigid_objects_linked_from_bones": len(rev),
           "mapping": mapping,
           "reverse_map": rev,
           "addon_enabled": bool(enabled),
           "rigid_to_bone": bone_of,
           "bones_from_extension": sorted({b for b in bone_of.values() if b}),
           "note": "骨侧真正的中介是 mmd_bonetrack.NNN（COPY_ROTATION 的来源对象），它不是刚体，"
                   "所以只在约束里找不到骨↔刚体映射；必须启用扩展读 o.mmd_rigid.bone。"}
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("MAP rigid=%d bones_with_links=%d linked_objects=%d"
          % (len(rigids), len(mapping), len(rev)))
    sys.stdout.flush()
    os._exit(0)


main()
