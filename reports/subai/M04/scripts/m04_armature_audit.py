"""D0 指令 1：把两具骨架分开点清（不用对象名推骨名）。

输出：每具 armature 的名字、骨数、其中 `下擺_*` 骨数、`下擺_11_*` 骨数；
每个刚体的 {对象名, mmd_rigid.bone, 它的父链里有哪具 armature / 属于哪个集合}；
按「所属骨架」聚合的刚体数。
"""
import addon_utils
import bpy
import json
from collections import Counter, defaultdict

OUT = r"E:\dsh pr\woker2\out\subai\M04\penetration\armature_audit.json"

for mod in ("bl_ext.user_default.mmd_tools", "mmd_tools"):
    try:
        addon_utils.enable(mod, default_set=False, handle_error=None)
        addon_name = mod
        break
    except Exception:  # noqa: BLE001
        addon_name = ""

bpy.ops.wm.open_mainfile(filepath=r"E:\dsh pr\woker2\out\subai\M02\blend\B_from_blend1.blend")

arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
arm_info = []
for a in arms:
    bones = [b.name for b in a.data.bones]
    arm_info.append({
        "name": a.name,
        "bones": len(bones),
        "skirt": sum(1 for b in bones if "\u4e0b\u64fa" in b),
        "line11": sum(1 for b in bones if b.startswith("\u4e0b\u64fa_11_")),
        "line0": sum(1 for b in bones if b.startswith("\u4e0b\u64fa_0_")),
        "children": sum(1 for o in bpy.data.objects if o.parent is a),
        "modifiers_on": sum(1 for o in bpy.data.objects
                            for m in getattr(o, "modifiers", [])
                            if m.type == "ARMATURE" and m.object is a),
    })

def owner_arm(ob):
    seen = set()
    cur = ob
    while cur is not None and cur.name not in seen:
        seen.add(cur.name)
        if cur.type == "ARMATURE":
            return cur.name
        for m in getattr(cur, "modifiers", []):
            if m.type == "ARMATURE" and m.object is not None:
                return m.object.name
        cur = cur.parent
    return ""

rigids = [o for o in bpy.data.objects if getattr(o, "rigid_body", None) is not None]
per_arm = Counter()
rows = []
for o in rigids:
    try:
        bone = o.mmd_rigid.bone or ""
    except Exception:  # noqa: BLE001
        bone = ""
    arm = owner_arm(o)
    per_arm[arm or "<none>"] += 1
    if "\u4e0b\u64fa_11_" in bone or "$name" in o.name:
        rows.append({"obj": o.name, "bone": bone, "arm": arm,
                     "parent": getattr(o.parent, "name", None),
                     "kinematic": o.rigid_body.kinematic,
                     "collections_parent": (o.parent.name if o.parent else None)})

# 骨架里到底哪具有 下擺_11_
line11_owner = {}
for a in arms:
    names = [b.name for b in a.data.bones if b.name.startswith("\u4e0b\u64fa_11_")]
    line11_owner[a.name] = len(names)

res = {
    "addon_enabled": addon_name,
    "armatures": arm_info,
    "line11_bones_per_armature": line11_owner,
    "rigids_total": len(rigids),
    "rigids_per_armature": dict(per_arm),
    "line11_or_placeholder_rows": rows,
}
json.dump(res, open(OUT, "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=2)
print("[arm] " + json.dumps({k: res[k] for k in (
    "armatures", "line11_bones_per_armature", "rigids_total", "rigids_per_armature")},
    ensure_ascii=True))
