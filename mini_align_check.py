"""最小对照：同一动作，B 用原始 vs 已注入，看 全ての親 与 センター 的世界位置。"""
import sys
import bpy
import addon_utils

sys.path.insert(0, r"E:/dsh pr/woker2")
from mmdpipe import vmd as V

PMX = r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309/星穹铁道—卡芙卡无外套/卡芙卡3.0.pmx"
A = r"E:/blender模型/爱乐之城_LaLa Land_by_小豆芽的日常_adf026480b2d1b2f38a4e4faa785560f/爱乐之城_LaLa Land/爱乐之城.vmd"
B0 = r"E:/blender模型/躺姿/和刻晴睡觉.vmd"
B1 = r"E:/dsh pr/woker2/out/B_aligned.vmd"

addon_utils.enable("mmd_tools", default_set=True, persistent=True)


def run(tag, bpath):
    tmp = "E:/dsh pr/woker2/out/_mini_%s.vmd" % tag
    rep = V.concat([V.load(A), V.load(Bpath := bpath)], tmp, gap=6)
    a_end, b_start = rep["spans"][0]["dst_range"][1], rep["spans"][1]["dst_range"][0]

    sc = bpy.context.scene
    sc.frame_start, sc.frame_end, sc.frame_current = 1, 250, 1
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    before = set(o.name for o in bpy.data.objects)
    bpy.ops.mmd_tools.import_model(filepath=PMX, scale=0.08, types={"MESH", "ARMATURE"},
                                   clean_model=True, rename_bones=True, log_level="ERROR")
    new = [bpy.data.objects[n] for n in set(o.name for o in bpy.data.objects) - before]
    root = next(o for o in new if getattr(o, "mmd_type", None) == "ROOT")
    arm = bpy.data.objects[root.name + "_arm"]
    bpy.ops.object.select_all(action="DESELECT")
    root.select_set(True)
    bpy.context.view_layer.objects.active = root
    bpy.ops.mmd_tools.import_vmd(filepath=tmp, scale=0.08, bone_mapper="PMX",
                                 rename_bones=True, use_underscore=False,
                                 update_scene_settings=True)
    print("== %s  action=%s A末=%d B首=%d"
          % (tag, arm.animation_data.action.name, a_end, b_start))
    for f in (a_end, b_start):
        sc.frame_set(f)
        row = []
        for n in ("全ての親", "センター", "下半身"):
            pb = arm.pose.bones.get(n)
            if not pb:
                row.append("%s=无" % n)
                continue
            w = (arm.matrix_world @ pb.matrix).translation
            row.append("%s=%s" % (n, tuple(round(v, 4) for v in w)))
        print("   f%-4d %s" % (f, "  ".join(row)))
    # 父链检查
    b = arm.data.bones.get("センター")
    chain = []
    while b is not None:
        chain.append(b.name)
        b = b.parent
    print("   センター 父链:", " <- ".join(chain[:6]))


run("orig", B0)
run("aligned", B1)
