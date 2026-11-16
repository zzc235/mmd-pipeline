"""M01 环境确认（Blender 侧）：导入飞霄，确认 build 流程、胸部骨名、约束回填结构。

只读：不改 PMX、不写 blend、不渲染。
    blender -b --factory-startup -P m01_env_probe.py -- <pmx> <out.json>
"""
import json
import sys

import addon_utils
import bpy

addon_utils.enable("bl_ext.user_default.mmd_tools", default_set=True, persistent=True)
argv = sys.argv[sys.argv.index("--") + 1:]
pmx, out_json = argv[0], argv[1]

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

bpy.ops.mmd_tools.import_model(filepath=pmx, scale=0.08,
                               types={"MESH", "ARMATURE", "MORPHS", "PHYSICS"},
                               clean_model=True, rename_bones=True, log_level="ERROR")
root = next(o for o in bpy.data.objects if getattr(o, "mmd_type", None) == "ROOT")
arm = bpy.data.objects[root.name + "_arm"]
mesh = bpy.data.objects[root.name + "_mesh"]

rigid_empties = [o for o in bpy.data.objects if getattr(o, "mmd_type", None) == "RIGID_BODY"]
info = {"blender": bpy.app.version_string, "root": root.name,
        "bones": len(arm.data.bones), "verts": len(mesh.data.vertices),
        "rigid_empties_after_import": len(rigid_empties),
        "joints_after_import": len([o for o in bpy.data.objects
                                    if getattr(o, "mmd_type", None) == "JOINT"]),
        "is_built_after_import": bool(root.mmd_root.is_built),
        "constraints_after_import": sum(1 for pb in arm.pose.bones for _ in pb.constraints)}
info["chest_bones"] = [b.name for b in arm.data.bones if ("胸" in b.name or "上半身" in b.name)]
info["vgroups_chest"] = [g.name for g in mesh.vertex_groups
                         if ("胸" in g.name or "上半身" in g.name)]

from bl_ext.user_default.mmd_tools.core import model as MModel  # noqa: E402
build_error = None
try:
    MModel.Model(root).build()
except Exception as exc:  # noqa: BLE001
    build_error = str(exc)
bpy.context.view_layer.update()
info["build_error"] = build_error
info["is_built"] = bool(root.mmd_root.is_built)
info["constraints_after_build"] = sum(1 for pb in arm.pose.bones for _ in pb.constraints)
info["rbw"] = {"enabled": bool(bpy.context.scene.rigidbody_world.enabled
                               if bpy.context.scene.rigidbody_world else None),
               "substeps": bpy.context.scene.rigidbody_world.substeps_per_frame
               if bpy.context.scene.rigidbody_world else None,
               "solver": bpy.context.scene.rigidbody_world.solver_iterations
               if bpy.context.scene.rigidbody_world else None}

def body_row(o):
    mr = o.mmd_rigid
    rb = o.rigid_body
    return {"obj": o.name, "mmd_name": mr.name, "type": mr.type, "bone": mr.bone,
            "shape": mr.shape, "has_rb": rb is not None,
            "rb_enabled": (rb.enabled if rb else None),
            "kinematic": (rb.kinematic if rb else None),
            "mass": (round(rb.mass, 4) if rb else None)}

info["chest_rigids"] = [body_row(o) for o in rigid_empties
                        if o.mmd_rigid.type == "2"
                        and o.mmd_rigid.name in ("右胸", "右胸１", "右胸２", "左胸", "左胸１", "左胸２")]
modes = {}
for o in rigid_empties:
    modes[o.mmd_rigid.type] = modes.get(o.mmd_rigid.type, 0) + 1
info["rigid_types"] = modes

rows = []
for pb in arm.pose.bones:
    for c in pb.constraints:
        if "胸" in pb.name or "上半身" in pb.name:
            tgt = getattr(c, "target", None)
            rows.append({"bone": pb.name, "type": c.type, "mute": c.mute,
                         "target": (tgt.name if tgt else None),
                         "target_is_rigid": bool(tgt and getattr(tgt, "mmd_type", None) == "RIGID_BODY"),
                         "target_mmd_name": (getattr(getattr(tgt, "mmd_rigid", None), "name", None)
                                             if tgt else None)})
info["chest_constraints"] = rows

with open(out_json, "w", encoding="utf-8") as fh:
    json.dump(info, fh, ensure_ascii=False, indent=1)

print("ENV", json.dumps({k: info[k] for k in
                         ("blender", "bones", "verts", "rigid_empties_after_import",
                          "is_built_after_import", "is_built", "build_error",
                          "constraints_after_build", "rigid_types", "rbw")}, ensure_ascii=False))
print("CHEST_BONES", info["chest_bones"])
print("CHEST_RIGIDS", len(info["chest_rigids"]), [r["mmd_name"] + "/" + r["type"] for r in info["chest_rigids"]])
print("CHEST_CONS", len(rows), sorted({(r["bone"], r["type"], r["target_mmd_name"]) for r in rows}))
