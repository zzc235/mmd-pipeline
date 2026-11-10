"""实验：把道具挂到角色骨骼上，看落点。"""
import bpy
import addon_utils
from mathutils import Vector, Matrix

PMX = r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309/星穹铁道—卡芙卡无外套/卡芙卡3.0.pmx"
VMD = r"E:/blender模型/爱乐之城_LaLa Land_by_小豆芽的日常_adf026480b2d1b2f38a4e4faa785560f/爱乐之城_LaLa Land/爱乐之城.vmd"
PROP = r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309/星穹铁道—卡芙卡无外套/刀.pmx"
SCALE = 0.08
BONE = "右手首"

for name in ("mmd_tools",):
    addon_utils.enable(name, default_set=True, persistent=True)
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)


def root_of(name_hint=None):
    c = [o for o in bpy.data.objects if getattr(o, "mmd_type", None) == "ROOT"]
    return c[-1] if c else None


bpy.ops.mmd_tools.import_model(filepath=PMX, scale=SCALE,
                               types={"MESH", "ARMATURE", "PHYSICS"},
                               clean_model=True, rename_bones=True, log_level="ERROR")
char = root_of()
char_arm = bpy.data.objects[char.name + "_arm"]
bpy.context.scene.frame_set(1)

# 不加动作，先用 rest 位置看关系
pb = char_arm.pose.bones.get(BONE)
print("角色骨 %s 存在=%s" % (BONE, pb is not None))
if pb:
    head_w = char_arm.matrix_world @ pb.head
    print("  骨 head 世界坐标 %s" % tuple(round(v, 4) for v in head_w))
    print("  骨世界旋转矩阵 euler %s" % tuple(round(v, 3) for v in (char_arm.matrix_world @ pb.matrix).to_euler()))

# 导入道具
bpy.ops.mmd_tools.import_model(filepath=PROP, scale=SCALE,
                               types={"MESH", "ARMATURE"},
                               clean_model=True, rename_bones=True, log_level="ERROR")
prop = [o for o in bpy.data.objects if getattr(o, "mmd_type", None) == "ROOT"][-1]
prop_arm = bpy.data.objects[prop.name + "_arm"]
prop_mesh = bpy.data.objects[prop.name + "_mesh"]
print("道具 root=%s arm=%s mesh=%s" % (prop.name, prop_arm.name, prop_mesh.name))
print("  道具 mesh 世界包围盒 Y %s .. %s" % (
    round(min((prop_mesh.matrix_world @ Vector(c)).y for c in prop_mesh.bound_box), 3),
    round(max((prop_mesh.matrix_world @ Vector(c)).y for c in prop_mesh.bound_box), 3)))
print("  道具骨 %s 世界位置 %s" % (
    [b.name for b in prop_arm.data.bones],
    tuple(round(v, 4) for v in (prop_arm.matrix_world @ prop_arm.pose.bones[0].head))))

# 挂到骨上
prop.parent = char_arm
prop.parent_type = "BONE"
prop.parent_bone = BONE
prop.matrix_parent_inverse = Matrix.Identity(4)
prop.location = (0, 0, 0)
prop.rotation_euler = (0, 0, 0)
bpy.context.view_layer.update()

pbw = char_arm.matrix_world @ pb.matrix
prop_bone_w = prop_arm.matrix_world @ prop_arm.pose.bones[0].head
print("挂上后：道具骨世界位置 %s" % (tuple(round(v, 4) for v in prop_bone_w),))
print("         角色骨世界位置 %s" % (tuple(round(v, 4) for v in (char_arm.matrix_world @ pb.head)),))
print("         道具 mesh 世界 Y %.3f .. %.3f" % (
    min((prop_mesh.matrix_world @ Vector(c)).y for c in prop_mesh.bound_box),
    max((prop_mesh.matrix_world @ Vector(c)).y for c in prop_mesh.bound_box)))
