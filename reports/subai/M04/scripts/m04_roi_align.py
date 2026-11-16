"""枚举「既有顶点组权重、又有刚体绑定」的骨，把两个穿进口径的 ROI 对齐到同一批骨。

为什么要这一步：网格口径的 ROI 来自 `s2_targets.json`（18 根 `下擺_0_*` 顶点组），
胶囊口径的 ROI 来自刚体绑定；实测两者不是同一批骨（刚体侧一开始只覆盖 35 根）。
不对齐就出数，等于两个口径各测各的，还都叫「裙摆」。

输出 JSON：每根骨 {bone, vgroup: bool, rigid: bool, rigids: n, shapes: [...]}，以及
both / vgroup_only / rigid_only 三个清单，方便一眼看出差在哪。
"""
import json
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
blend, out_path = argv[0], argv[1]

bpy.ops.wm.open_mainfile(filepath=blend)

# 1) 顶点组：哪些骨在网格上有权重
vgroup_bones = set()
for ob in bpy.data.objects:
    if ob.type != "MESH":
        continue
    for g in ob.vertex_groups:
        vgroup_bones.add(g.name)

# 2) 刚体绑定：CHILD_OF.subtarget 与自定义属性 bone 两个来源都读
rigid_of = {}
for ob in bpy.data.objects:
    rb = getattr(ob, "rigid_body", None)
    if rb is None:
        continue
    bone = ""
    for c in ob.constraints:
        if c.type == "CHILD_OF":
            bone = getattr(c, "subtarget", "") or ""
            if bone:
                break
    if not bone and getattr(ob, "parent_type", "") == "BONE":
        bone = str(getattr(ob, "parent_bone", "") or "")
    if not bone:
        bone = str(ob.get("bone", "") or "")
    if not bone:
        continue
    rigid_of.setdefault(bone, []).append((ob.name, (rb.collision_shape or "?").upper()))

all_bones = sorted(set(vgroup_bones) | set(rigid_of))
rows = []
for b in all_bones:
    rows.append({
        "bone": b,
        "vgroup": b in vgroup_bones,
        "rigid": b in rigid_of,
        "rigids": len(rigid_of.get(b, [])),
        "shapes": sorted({s for _, s in rigid_of.get(b, [])}),
    })
both = [r["bone"] for r in rows if r["vgroup"] and r["rigid"]]
vg_only = [r["bone"] for r in rows if r["vgroup"] and not r["rigid"]]
rg_only = [r["bone"] for r in rows if r["rigid"] and not r["vgroup"]]
skirt_both = [b for b in both if "\u4e0b\u64fa" in b]
skirt_vg = [b for b in vg_only if "\u4e0b\u64fa" in b]

res = {
    "blend": blend,
    "vgroup_bones": len(vgroup_bones),
    "rigid_bones": len(rigid_of),
    "both": both,
    "both_skirt": sorted(skirt_both),
    "vgroup_only_skirt": sorted(skirt_vg)[:40],
    "rigid_only": rg_only[:40],
    "meshes": sum(1 for o in bpy.data.objects if o.type == "MESH"),
    "rigid_objs": sum(1 for o in bpy.data.objects if getattr(o, "rigid_body", None) is not None),
}
json.dump(res, open(out_path, "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=2)
print("[align] both=%d both_skirt=%d vgroup_only_skirt=%d rigid_bones=%d"
      % (len(both), len(skirt_both), len(skirt_vg), len(rigid_of)))
print("[align] skirt both sample: " + json.dumps(sorted(skirt_both)[:20], ensure_ascii=True))
