"""验证拼接后的 VMD 在 Blender 里：帧范围、两段是否真的不同。"""
import bpy
import addon_utils

BASE = r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309/星穹铁道—卡芙卡无外套/卡芙卡3.0.pmx"
VMD = r"E:/dsh pr/woker2/out/拼接测试.vmd"

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

bpy.ops.object.select_all(action="DESELECT")
root.select_set(True)
bpy.context.view_layer.objects.active = root
bpy.ops.mmd_tools.import_vmd(filepath=VMD, scale=0.08, bone_mapper="PMX",
                             rename_bones=True, use_underscore=False,
                             update_scene_settings=True)

act = arm.animation_data.action
print("ACTION %s  范围 %s  fcurves %d" % (act.name, tuple(act.frame_range), len(act.fcurves)))

pb = arm.pose.bones.get("センター")
bone2 = arm.pose.bones.get("上半身")
print("测试骨:", pb.name if pb else None, "/", bone2.name if bone2 else None)
sc = bpy.context.scene
samples = []
for f in (10, 100, 200, 300, 460, 600, 700, 800):
    sc.frame_set(f)
    r1 = tuple(round(v, 3) for v in pb.rotation_quaternion)
    r2 = tuple(round(v, 3) for v in bone2.rotation_quaternion)
    samples.append((f, r1, r2))
    print("f%-4d センター %s  上半身 %s" % (f, r1, r2))

uniq = len({s[1] for s in samples})
print("センター 不同姿态数 %d / %d 帧" % (uniq, len(samples)))
