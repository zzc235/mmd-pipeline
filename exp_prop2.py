"""实验 2：正确识别道具对象 + 用真实骨名 `手首.R` 挂接。"""
import bpy
import addon_utils
from mathutils import Vector, Matrix

BASE = r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309/星穹铁道—卡芙卡无外套"
PMX = BASE + "/卡芙卡3.0.pmx"
PROP = BASE + "/刀.pmx"
SCALE = 0.08

addon_utils.enable("mmd_tools", default_set=True, persistent=True)
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

before = set(o.name for o in bpy.data.objects)
bpy.ops.mmd_tools.import_model(filepath=PMX, scale=SCALE,
                               types={"MESH", "ARMATURE", "PHYSICS"},
                               clean_model=True, rename_bones=True, log_level="ERROR")
new = [bpy.data.objects[n] for n in set(o.name for o in bpy.data.objects) - before]
char_root = next(o for o in new if getattr(o, "mmd_type", None) == "ROOT")
char_arm = bpy.data.objects[char_root.name + "_arm"]
print("角色 root=%s arm=%s" % (char_root.name, char_arm.name))
print("MMD 骨名候选: %s" % [b.name for b in char_arm.data.bones if "手首" in b.name or "手" in b.name][:12])

BONE = "手首.R"
pb = char_arm.pose.bones.get(BONE)
print("骨 %s 存在=%s" % (BONE, pb is not None))
bpy.context.scene.frame_set(1)

before = set(o.name for o in bpy.data.objects)
bpy.ops.mmd_tools.import_model(filepath=PROP, scale=SCALE,
                               types={"MESH", "ARMATURE"},
                               clean_model=True, rename_bones=True, log_level="ERROR")
newp = [bpy.data.objects[n] for n in set(o.name for o in bpy.data.objects) - before]
print("道具新增对象: %s" % [(o.name, getattr(o, "mmd_type", None), o.type) for o in newp])
prop_root = next(o for o in newp if getattr(o, "mmd_type", None) == "ROOT")
prop_arm = bpy.data.objects[prop_root.name + "_arm"]
prop_mesh = bpy.data.objects[prop_root.name + "_mesh"]
print("道具 root=%s arm=%s mesh=%s 骨=%s"
      % (prop_root.name, prop_arm.name, prop_mesh.name,
         [b.name for b in prop_arm.data.bones]))

hand_w = char_arm.matrix_world @ pb.head
print("手首 head 世界 %s" % (tuple(round(v, 3) for v in hand_w),))
print("道具骨世界（未挂） %s" % (tuple(round(v, 3) for v in (prop_arm.matrix_world @ prop_arm.pose.bones[0].head)),))

# 挂到骨上，用矩阵反解让道具骨对准手首
prop_root.parent = char_arm
prop_root.parent_type = "BONE"
prop_root.parent_bone = BONE
bpy.context.view_layer.update()

# 让道具的那根骨世界位置 == 手首 head
prop_bone = prop_arm.pose.bones[0]
delta = hand_w - (prop_arm.matrix_world @ prop_bone.head)
prop_root.location = (prop_root.location.x + delta.x,
                      prop_root.location.y + delta.y,
                      prop_root.location.z + delta.z)
bpy.context.view_layer.update()

now = prop_arm.matrix_world @ prop_bone.head
print("挂后 道具骨世界 %s  目标 %s  误差 %.4f"
      % (tuple(round(v, 3) for v in now), tuple(round(v, 3) for v in hand_w),
         (now - hand_w).length))
ys = [(prop_mesh.matrix_world @ Vector(c)).y for c in prop_mesh.bound_box]
xs = [(prop_mesh.matrix_world @ Vector(c)).x for c in prop_mesh.bound_box]
print("道具 mesh 世界 X %.2f..%.2f  Y %.2f..%.2f" % (min(xs), max(xs), min(ys), max(ys)))
