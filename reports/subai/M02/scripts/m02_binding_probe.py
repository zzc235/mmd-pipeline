"""M02 · 刚体↔骨的绑定来源核查（18 根下摆骨到底有没有刚体、怎么绑的）。

    blender -b -P m02_binding_probe.py -- <scene.blend> <targets.json> <out.json>

背景：有队友用 `CHILD_OF.subtarget` + 自定义属性 `ob["bone"]` 两个来源统计「有刚体绑定的骨」，
得到 36 根、`下擺_0_*` 18 根「无刚体」。M02 的 `collections.json` 里明明有 `042_下擺_0_0` 这类刚体对象，
所以把绑定机制本身打出来：父级类型 / 父骨 / 约束清单 / 自定义属性键。

只读打开，绝不保存。
"""
import hashlib
import json
import os
import sys

import bpy


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) < 3:
        raise SystemExit("usage: m02_binding_probe.py -- scene.blend targets.json out.json")
    src, targets_path, out_path = argv[0], argv[1], argv[2]
    with open(targets_path, encoding="utf-8") as fh:
        targets = [t["joint_name"] for t in json.load(fh)["targets"]]

    sha_before = sha256_file(src)
    bpy.ops.wm.open_mainfile(filepath=src)

    rigids = [o for o in bpy.data.objects if getattr(o, "rigid_body", None) is not None]
    by_bone = {}
    for ob in rigids:
        bone = ob.name.split("_", 1)[-1] if "_" in ob.name else ob.name
        by_bone.setdefault(bone, []).append(ob)

    def describe(ob):
        cons = []
        for c in ob.constraints:
            cons.append({"type": c.type,
                         "subtarget": getattr(c, "subtarget", None),
                         "target": getattr(getattr(c, "target", None), "name", None),
                         "enabled": bool(getattr(c, "enabled", True))})
        return {"object": ob.name,
                "rigid_body_type": ob.rigid_body.type,
                "rigid_body_kinematic": bool(ob.rigid_body.kinematic),
                "parent": ({"type": ob.parent_type,
                            "object": getattr(ob.parent, "name", None),
                            "bone": getattr(ob, "parent_bone", None)}
                           if ob.parent else None),
                "constraints": cons,
                "custom_props": sorted(k for k in ob.keys() if not k.startswith("_")),
                "collections_bits": [i for i, v in
                                     enumerate(ob.rigid_body.collision_collections) if v]}

    per_target = {}
    for bone in targets:
        objs = by_bone.get(bone, [])
        per_target[bone] = [describe(o) for o in objs]

    # 全量统计：绑定来源计数
    src_counts = {"child_of": 0, "parent_bone": 0, "custom_bone_prop": 0,
                  "no_binding": 0, "rigid_total": len(rigids)}
    for ob in rigids:
        has_child = any(c.type == "CHILD_OF" for c in ob.constraints)
        has_parent_bone = bool(getattr(ob, "parent_bone", ""))
        has_prop = "bone" in ob.keys()
        src_counts["child_of"] += int(has_child)
        src_counts["parent_bone"] += int(has_parent_bone)
        src_counts["custom_bone_prop"] += int(has_prop)
        if not (has_child or has_parent_bone or has_prop):
            src_counts["no_binding"] += 1

    # 骨侧的绑定：mmd_tools 对「物理骨」是在 **pose bone** 上加约束指向刚体对象，
    # 只在 object 上找 CHILD_OF 会漏掉这一类。
    pose_links = {}
    for arm in [o for o in bpy.data.objects if o.type == "ARMATURE"]:
        for bone in targets:
            pb = arm.pose.bones.get(bone)
            if pb is None:
                continue
            cons = [{"type": c.type,
                     "target_object": getattr(getattr(c, "target", None), "name", None),
                     "subtarget": getattr(c, "subtarget", None),
                     "enabled": bool(getattr(c, "enabled", True))}
                    for c in pb.constraints]
            if cons:
                pose_links.setdefault(bone, {"armature": arm.name, "constraints": cons})

    # PLACEHOLDER: 占位刚体（$name_j）的绑定方式，和 PMX 原生刚体是不是同一类
    placeholder = {}
    for ob in rigids:
        if "$name_j" not in ob.name:
            continue
        placeholder[ob.name] = describe(ob)

    out = {"stage": "binding-probe", "in_blend": src,
           "in_blend_sha256": sha256_file(src),
           "source_untouched": sha_before == sha256_file(src),
           "never_saved_blend": True,
           "rigid_objects": len(rigids),
           "targets": targets,
           "targets_with_rigid_body": sorted(b for b in targets if by_bone.get(b)),
           "targets_without_rigid_body": sorted(b for b in targets if not by_bone.get(b)),
           "per_target": per_target,
           "binding_source_counts": src_counts,
           "pose_bone_links": pose_links,
           "pose_bone_links_count": len(pose_links),
           "placeholder_bodies": placeholder,
           "placeholder_count": len(placeholder)}
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("BIND rigid=%d targets=%d with_body=%d without=%d child_of=%d parent_bone=%d prop=%d"
          % (len(rigids), len(targets), len(out["targets_with_rigid_body"]),
             len(out["targets_without_rigid_body"]), src_counts["child_of"],
             src_counts["parent_bone"], src_counts["custom_bone_prop"]))
    sys.stdout.flush()
    os._exit(0)


main()
