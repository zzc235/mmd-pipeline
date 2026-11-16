"""D0 三条里的两条（需要 Blender，只读、不保存）：
  1. ROI 归因必须来自 `o.mmd_rigid.bone`，不许从对象名反推；
  2. 11 个 `$name_j` 占位刚体到底是什么（动静、碰撞组、掩码、有没有绑骨、参不参与解算）。

另附：骨架里到底有没有 `下擺_11_*` 这族骨（D0 说场景没有这族刚体，我要核的是「骨在不在」）。
"""
import addon_utils
import bpy
import json
from collections import Counter

OUT = r"E:\dsh pr\woker2\out\subai\M04\penetration\binding_audit.json"

for mod in ("bl_ext.user_default.mmd_tools", "mmd_tools"):
    try:
        addon_utils.enable(mod, default_set=False, handle_error=None)
        addon_ver = mod
        break
    except Exception:  # noqa: BLE001
        addon_ver = ""

bpy.ops.wm.open_mainfile(filepath=r"E:\dsh pr\woker2\out\subai\M02\blend\B_from_blend1.blend")

arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
rigids = [o for o in bpy.data.objects if getattr(o, "rigid_body", None) is not None]
meshes = [o for o in bpy.data.objects if o.type == "MESH"]

# 骨架里有没有 下擺_11_*
bone_names = set()
for a in arms:
    for b in a.data.bones:
        bone_names.add(b.name)
row11 = sorted(n for n in bone_names if n.startswith("\u4e0b\u64fa_11_"))
row0 = sorted(n for n in bone_names if n.startswith("\u4e0b\u64fa_0_"))

by_bone = Counter()
by_child = Counter()
for o in rigids:
    try:
        b = o.mmd_rigid.bone or ""
    except Exception:  # noqa: BLE001
        b = ""
    by_bone[b or "<empty>"] += 1
    ch = ""
    for c in o.constraints:
        if c.type == "CHILD_OF" and getattr(c, "subtarget", ""):
            ch = c.subtarget
            break
    by_child[ch or "<none>"] += 1

skirt_bone = {k: v for k, v in by_bone.items() if "\u4e0b\u64fa" in k}
row11_rigid = {k: v for k, v in skirt_bone.items() if k.startswith("\u4e0b\u64fa_11_")}
row0_rigid = {k: v for k, v in skirt_bone.items() if k.startswith("\u4e0b\u64fa_0_")}

placeholders = [o for o in rigids if o.name.split("_", 1)[-1].startswith("$name_j")]
ph = []
for o in placeholders:
    rb = o.rigid_body
    ph.append({
        "obj": o.name,
        "mmd_bone": (getattr(o, "mmd_rigid", None).bone if getattr(o, "mmd_rigid", None) else ""),
        "mmd_type": getattr(getattr(o, "mmd_rigid", None), "type", ""),
        "shape": rb.collision_shape,
        "kinematic": rb.kinematic,
        "enabled": rb.enabled,
        "mass": round(rb.mass, 4),
        "collision_collections": list(rb.collision_collections),
        "collision_shape": rb.collision_shape,
        "constraints": [c.type for c in o.constraints],
    })

res = {
    "blend": "out/subai/M02/blend/B_from_blend1.blend",
    "addon_enabled": addon_ver,
    "armatures": [a.name for a in arms],
    "mesh_count": len(meshes),
    "rigid_count": len(rigids),
    "bones_line11_exist": len(row11),
    "bones_line11_names": row11,
    "bones_line0_count": len(row0),
    "rigid_distinct_bones_mmd": len([k for k in by_bone if k != "<empty>"]),
    "rigid_empty_binding": by_bone.get("<empty>", 0),
    "rigid_skirt_bones": len(skirt_bone),
    "rigid_line11": row11_rigid,
    "rigid_line0_count": len(row0_rigid),
    "rigid_line0_sample": sorted(row0_rigid)[:20],
    "child_of_distinct": len([k for k in by_child if k != "<none>"]),
    "child_of_none": by_child.get("<none>", 0),
    "child_of_line11_sample": sorted(k for k in by_child if k.startswith("\u4e0b\u64fa_11_"))[:12],
    "placeholders_count": len(placeholders),
    "placeholders": ph,
}
json.dump(res, open(OUT, "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=2)
print("[audit] " + json.dumps({k: res[k] for k in (
    "addon_enabled", "rigid_count", "rigid_distinct_bones_mmd", "rigid_skirt_bones",
    "rigid_line0_count", "rigid_line11", "bones_line11_exist", "child_of_distinct",
    "child_of_none", "placeholders_count")}, ensure_ascii=True))
