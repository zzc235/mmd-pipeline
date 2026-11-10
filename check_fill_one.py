"""单次会话采样一个 VMD：blender -b -P check_fill_one.py -- <vmd>"""
import sys
import bpy
import addon_utils

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
VMD = argv[0]
BASE = r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309/星穹铁道—卡芙卡无外套/卡芙卡3.0.pmx"
WATCH = ["足D.R", "ひざD.R", "足首D.R", "上半身", "上半身3", "頭", "センター", "グルーブ"]
FRAMES = (100, 600)

addon_utils.enable("mmd_tools", default_set=True, persistent=True)
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

before = set(o.name for o in bpy.data.objects)
bpy.ops.mmd_tools.import_model(filepath=BASE, scale=0.08,
                               types={"MESH", "ARMATURE"}, clean_model=True,
                               rename_bones=True, log_level="ERROR")
new = [bpy.data.objects[n] for n in set(o.name for o in bpy.data.objects) - before]
root = next(o for o in new if getattr(o, "mmd_type", None) == "ROOT")
arm = bpy.data.objects[root.name + "_arm"]
sc = bpy.context.scene

bpy.ops.object.select_all(action="DESELECT")
root.select_set(True)
bpy.context.view_layer.objects.active = root
bpy.ops.mmd_tools.import_vmd(filepath=VMD, scale=0.08, bone_mapper="PMX",
                             rename_bones=True, use_underscore=False,
                             update_scene_settings=True)
act = arm.animation_data.action
print("ACTION %s  范围 %s  fcurves %d" % (act.name, tuple(act.frame_range), len(act.fcurves)))

for f in FRAMES:
    sc.frame_set(f)
    print("FRAME %d" % f)
    for n in WATCH:
        pb = arm.pose.bones.get(n)
        if not pb:
            print("  %-10s 不存在" % n)
            continue
        w = arm.matrix_world @ pb.head
        print("  %-10s %s" % (n, tuple(round(v, 4) for v in w)))
