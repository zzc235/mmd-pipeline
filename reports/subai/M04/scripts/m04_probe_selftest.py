"""穿透探针的算法自检：用已知内外的偏移点验证「奇偶判内外 + 最近面距离=深度」。

对同一帧的 evaluated 网格：
  * p + 0.10·n（沿外法线外推 10 cm）→ 必须判「外部」；
  * p - 0.03·n（沿内法线内推 3 cm）→ 必须判「内部」，且深度 ≈ 0.03 m。
两条都能过，说明探针的判内外与深度标尺是正确的；过不了，前面那 240 帧的 -0.0171 就是方法偏移。

输出 JSON：样本数、各判对的比例、深度中位与偏差。
"""
import json
import sys

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
blend, out = argv[0], argv[1]

bpy.ops.wm.open_mainfile(filepath=blend)
sc = bpy.context.scene
sc.frame_set(1)
ob = None
for o in bpy.data.objects:
    if o.type == "MESH" and o.modifiers:
        ob = o
        break
dg = bpy.context.evaluated_depsgraph_get()
ev = ob.evaluated_get(dg)
me = ev.to_mesh()
mw = ev.matrix_world
co = [mw @ v.co for v in me.vertices]
polys = [tuple(p.vertices) for p in me.polygons]
bvh = BVHTree.FromPolygons(co, polys, all_triangles=False, epsilon=0.0)


def inside(p, direction=Vector((1.0, 0.0, 0.0))):
    hits, origin, guard = 0, p.copy(), 0
    while guard < 32:
        guard += 1
        loc, nor, idx, dist = bvh.ray_cast(origin, direction)
        if loc is None:
            break
        hits += 1
        origin = loc + direction * 1e-5
    return hits % 2 == 1


step = max(1, len(co) // 300)
outward_ok = inward_ok = 0
depth_err = []
n = 0
for i in range(0, len(co), step):
    p = co[i]
    loc, nor, idx, dist = bvh.find_nearest(p)
    if loc is None:
        continue
    n += 1
    out_pt = p + nor * 0.10
    if not inside(out_pt):
        outward_ok += 1
    in_pt = p - nor * 0.03
    if inside(in_pt):
        inward_ok += 1
        loc2, nor2, idx2, dist2 = bvh.find_nearest(in_pt)
        if dist2 is not None:
            depth_err.append(dist2 - 0.03)

ev.to_mesh_clear()
res = {
    "blend": blend,
    "frame": 1,
    "vertices": len(co),
    "samples": n,
    "outward_10cm_judged_outside": outward_ok,
    "outward_10cm_rate": round(outward_ok / n, 4) if n else None,
    "inward_3cm_judged_inside": inward_ok,
    "inward_3cm_rate": round(inward_ok / n, 4) if n else None,
    "inward_depth_median_err_m": round(sorted(depth_err)[len(depth_err) // 2], 6) if depth_err else None,
    "inward_depth_max_abs_err_m": round(max(abs(e) for e in depth_err), 6) if depth_err else None,
}
json.dump(res, open(out, "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=2)
print("[selftest] " + json.dumps(res, ensure_ascii=True))
