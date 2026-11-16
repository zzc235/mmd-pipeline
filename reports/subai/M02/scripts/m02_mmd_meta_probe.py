"""MMD 刚体元数据到底挂在哪儿：枚举 `mmd*` 相关的 RNA 属性与自定义属性。

    blender -b -P m02_mmd_meta_probe.py -- <blend> <out.json>

目的是回答「PMX 的 group/mask 在 Blender 里怎么读」，而不是靠记忆去猜属性名。
"""
import json
import os
import sys

import bpy


def mmd_attrs(obj):
    out = []
    for name in dir(obj):
        if not name.lower().startswith("mmd"):
            continue
        try:
            value = getattr(obj, name)
        except Exception:
            out.append({"name": name, "error": "unreadable"})
            continue
        fields = {}
        for field in ("collision_group_number", "collision_group_mask", "name", "name_e"):
            if hasattr(value, field):
                try:
                    fields[field] = getattr(value, field)
                except Exception as exc:
                    fields[field] = "err:%s" % exc
        out.append({"name": name, "type": type(value).__name__, "fields": fields})
    return out


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    path, out_path = argv[0], argv[1]
    bpy.ops.wm.open_mainfile(filepath=path)

    rigid = [o for o in bpy.data.objects if getattr(o, "rigid_body", None) is not None]
    sample = rigid[0] if rigid else None
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    out = {"blend": path, "rigid_objects": len(rigid),
           "sample_object": sample.name if sample else None,
           "sample_object_custom_props": sorted(sample.keys()) if sample else [],
           "sample_object_mmd_attrs": mmd_attrs(sample) if sample else [],
           "armatures": {}}
    for arm in arms:
        pose = arm.pose.bones
        target = next((pb for pb in pose if "下擺_0_17" in pb.name), pose[0] if pose else None)
        out["armatures"][arm.name] = {
            "bones": len(arm.data.bones),
            "sample_bone": target.name if target else None,
            "sample_bone_custom_props": sorted(target.keys()) if target else [],
            "sample_bone_mmd_attrs": mmd_attrs(target) if target else [],
            "sample_bone_rigid_body": bool(getattr(target, "rigid_body", None)) if target else None,
        }
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("MMD_META " + json.dumps({k: out[k] for k in ("rigid_objects", "sample_object",
                                                       "sample_object_custom_props")},
                                  ensure_ascii=False))
    print("MMD_META attrs " + json.dumps(out["sample_object_mmd_attrs"], ensure_ascii=False)[:600])
    for name, info in out["armatures"].items():
        print("MMD_META bone " + json.dumps({name: {k: info[k] for k in
                                                    ("sample_bone", "sample_bone_custom_props",
                                                     "sample_bone_rigid_body")}},
                                            ensure_ascii=False))
        print("MMD_META bone_attrs " + json.dumps(info["sample_bone_mmd_attrs"], ensure_ascii=False)[:600])
    sys.stdout.flush()
    os._exit(0)


main()
