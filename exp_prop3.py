"""实验 3：挂接 + 上动作 + 上材质 + 渲一帧，肉眼看位置和朝向。"""
import bpy
import addon_utils
from mathutils import Vector, Matrix
from bl_ext.user_default.mmd_tools.core import model as MModel
from bl_ext.user_default.mmd_tools.core import rigid_body as MRigid

BASE = r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309/星穹铁道—卡芙卡无外套"
PMX = BASE + "/卡芙卡3.0.pmx"
PROP = BASE + "/刀.pmx"
VMD = r"E:/blender模型/爱乐之城_LaLa Land_by_小豆芽的日常_adf026480b2d1b2f38a4e4faa785560f/爱乐之城_LaLa Land/爱乐之城.vmd"
SCALE = 0.08
BONE = "手首.R"
FRAME = 60
OUT = r"E:/dsh pr/woker2/out/prop_test_%d.png" % FRAME

addon_utils.enable("mmd_tools", default_set=True, persistent=True)
addon_utils.enable("jinfengling_hsr_addon", default_set=True, persistent=True)
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

sc = bpy.context.scene
sc.render.resolution_x, sc.render.resolution_y = 900, 900
sc.render.resolution_percentage = 100
sc.eevee.taa_render_samples = 8

before = set(o.name for o in bpy.data.objects)
bpy.ops.mmd_tools.import_model(filepath=PMX, scale=SCALE,
                               types={"MESH", "ARMATURE", "PHYSICS"},
                               clean_model=True, rename_bones=True, log_level="ERROR")
new = [bpy.data.objects[n] for n in set(o.name for o in bpy.data.objects) - before]
root = next(o for o in new if getattr(o, "mmd_type", None) == "ROOT")
arm = bpy.data.objects[root.name + "_arm"]
mesh = bpy.data.objects[root.name + "_mesh"]

MModel.Model(root).build()
MRigid.setRigidBodyWorldEnabled(True)
rbw = sc.rigidbody_world
rbw.enabled = True
rbw.substeps_per_frame = 10
rbw.solver_iterations = 20
rbw.point_cache.frame_start, rbw.point_cache.frame_end = 1, 492

bpy.ops.object.select_all(action="DESELECT")
root.select_set(True)
bpy.context.view_layer.objects.active = root
bpy.ops.mmd_tools.import_vmd(filepath=VMD, scale=SCALE, bone_mapper="PMX",
                             rename_bones=True, use_underscore=False,
                             update_scene_settings=True)

bpy.ops.object.select_all(action="DESELECT")
mesh.select_set(True)
arm.select_set(True)
bpy.context.view_layer.objects.active = mesh
for fn in (lambda: bpy.ops.jflhsr.setup_star_rail_environment(),
           lambda: bpy.ops.jflhsr.assign_star_rail_materials(reset_legacy_ramp=False),
           lambda: bpy.ops.jflhsr.set_star_rail_sdf(body_type="W168", variant="00"),
           lambda: bpy.ops.jflhsr.setup_light_vectors(),
           lambda: bpy.ops.jflhsr.setup_outlines(),
           lambda: bpy.ops.jflhsr.apply_reference_environment()):
    try:
        fn()
    except Exception as exc:
        print("HSR step fail", exc)

# 道具
before = set(o.name for o in bpy.data.objects)
bpy.ops.mmd_tools.import_model(filepath=PROP, scale=SCALE,
                               types={"MESH", "ARMATURE"},
                               clean_model=True, rename_bones=True, log_level="ERROR")
newp = [bpy.data.objects[n] for n in set(o.name for o in bpy.data.objects) - before]
prop_root = next(o for o in newp if getattr(o, "mmd_type", None) == "ROOT")
prop_arm = bpy.data.objects[prop_root.name + "_arm"]
prop_mesh = bpy.data.objects[prop_root.name + "_mesh"]

sc.frame_set(FRAME)
pb = arm.pose.bones[BONE]
hand_w = arm.matrix_world @ pb.head

prop_root.parent = arm
prop_root.parent_type = "BONE"
prop_root.parent_bone = BONE
bpy.context.view_layer.update()
delta = hand_w - (prop_arm.matrix_world @ prop_arm.pose.bones[0].head)
prop_root.matrix_world = Matrix.Translation(delta) @ prop_root.matrix_world
bpy.context.view_layer.update()
err = ((prop_arm.matrix_world @ prop_arm.pose.bones[0].head) - hand_w).length
print("PROP_ERR %.5f" % err)

xs = [(prop_mesh.matrix_world @ Vector(c)).x for c in prop_mesh.bound_box]
ys = [(prop_mesh.matrix_world @ Vector(c)).y for c in prop_mesh.bound_box]
zs = [(prop_mesh.matrix_world @ Vector(c)).z for c in prop_mesh.bound_box]
print("PROP_BBOX X %.2f..%.2f Y %.2f..%.2f Z %.2f..%.2f" % (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)))

# 相机：正对角色
center = Vector((0.0, 0.0, 0.95))
cam_data = bpy.data.cameras.new("CAM")
cam_data.lens = 50
cam = bpy.data.objects.new("CAM", cam_data)
sc.collection.objects.link(cam)
cam.location = (2.4, -3.6, 1.6)
cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
sc.camera = cam
if sc.world and sc.world.node_tree:
    bg = next((n for n in sc.world.node_tree.nodes if n.type == "BACKGROUND"), None)
    if bg:
        bg.inputs[0].default_value = (0.32, 0.34, 0.38, 1.0)
        bg.inputs[1].default_value = 0.6

sc.frame_set(FRAME)
sc.render.filepath = OUT
bpy.ops.render.render(write_still=True)
print("RENDERED", OUT)
