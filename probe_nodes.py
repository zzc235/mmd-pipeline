"""查材质内部真相：是完整 HSR 着色（多张 ramp/lightmap/mask），还是通用卡通（单色）。"""
import bpy

WANT = ["衣", "肌", "髪", "顏", "袖", "鞋", "目"]
print("=== MATERIAL NODE AUDIT ===")
for m in bpy.data.materials:
    if not m.name.startswith("堇风铃"):
        continue
    tag = None
    for w in WANT:
        if ("| %s |" % w) in m.name or ("| %s+" % w) in m.name:
            tag = w
            break
    if not tag:
        continue
    if not m.use_nodes or not m.node_tree:
        print("|", m.name, "NO NODES")
        continue
    nt = m.node_tree
    types = {}
    for n in nt.nodes:
        types[n.type] = types.get(n.type, 0) + 1
    imgs = [n.image.name for n in nt.nodes if n.type == "TEX_IMAGE" and n.image]
    groups = [n.node_tree.name for n in nt.nodes if n.type == "GROUP" and n.node_tree]
    print("---")
    print("MAT", m.name[:70])
    print("  node_types", types)
    print("  images(%d)" % len(imgs), imgs)
    print("  groups", groups)
    # 抓取 Principled / 关键输入名
    for n in nt.nodes:
        if n.type in ("BSDF_PRINCIPLED", "SHADER_TO_RGB", "MIX_SHADER", "VALTORGB") or "Group" in n.name:
            ins = [i.name for i in n.inputs][:12]
            print("  NODE", n.type, "|", n.name[:50], "| in:", ins)
print("=== END ===")
print("IMAGES_ABS", [i.filepath for i in bpy.data.images if i.filepath and not i.filepath.startswith("//")])
