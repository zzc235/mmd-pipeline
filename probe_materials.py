"""按面积加权普查材质：面数 / 面积 / 是否挂了 HSR 着色组。"""
import bpy

FALLBACK = {"內著", "內著肌", "后結", "后結+", "后結透", "后結透+", "后花", "小飾品",
            "彩球", "指甲", "耳", "肌", "腕飾", "腕飾+", "腰飾", "腰飾透", "衣", "衣+",
            "袖", "袖+", "袖球", "袖球+", "鞋", "頭飾", "頭飾+", "髪"}


def base(n):
    n = n.split(" | ")[0].strip()
    while n and n[-1].isdigit() and "." in n:
        n = n.rsplit(".", 1)[0]
    return n


meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.data and o.data.polygons]
meshes.sort(key=lambda o: len(o.data.polygons), reverse=True)
print("MESHES", [(o.name, len(o.data.polygons), len(o.data.materials)) for o in meshes[:5]])

obj = meshes[0]
me = obj.data
print("TARGET", obj.name, "polys", len(me.polygons), "verts", len(me.vertices))

area = {}
count = {}
for p in me.polygons:
    i = p.material_index
    area[i] = area.get(i, 0.0) + p.area
    count[i] = count.get(i, 0) + 1

total = sum(area.values()) or 1.0
print("TOTAL_AREA %.6f" % total)

rows = []
for i, slot in enumerate(obj.material_slots):
    m = slot.material
    name = m.name if m else "<empty>"
    a = area.get(i, 0.0)
    c = count.get(i, 0)
    has_hsr = False
    groups = []
    if m and m.use_nodes and m.node_tree:
        for n in m.node_tree.nodes:
            if n.type == "GROUP" and n.node_tree:
                groups.append(n.node_tree.name)
                if "堇风铃" in n.node_tree.name or "HSR" in n.node_tree.name.upper():
                    has_hsr = True
    rows.append((a, name, c, has_hsr, groups[:2]))

rows.sort(reverse=True, key=lambda r: r[0])
print("IDX\tAREAPCT\tPOLYS\tHSRGROUP\tFALLBACK\tNAME\tGROUPS")
for a, name, c, hsr, g in rows:
    isfb = base(name) in FALLBACK
    print("%.4f\t%6.2f%%\t%5d\t%s\t%s\t%s\t%s"
          % (a, a / total * 100, c, hsr, isfb, name, g))

fb_area = sum(a for a, name, c, h, g in rows if base(name) in FALLBACK)
hsr_area = sum(a for a, name, c, h, g in rows if h)
nofb_hsr = sum(a for a, name, c, h, g in rows if h and base(name) not in FALLBACK)
print("SUMMARY fallback_area %.2f%% | hsrgroup_area %.2f%% | hsr_and_not_fallback %.2f%%"
      % (fb_area / total * 100, hsr_area / total * 100, nofb_hsr / total * 100))
print("SUMMARY fallback_slots %d / %d" % (sum(1 for r in rows if base(r[1]) in FALLBACK), len(rows)))

imgs = [i for i in bpy.data.images if i.filepath]
rel = sum(1 for i in imgs if not i.filepath.startswith("//"))
print("IMAGES total %d | absolute_path %d" % (len(imgs), rel))
