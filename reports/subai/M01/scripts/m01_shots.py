"""M01 代表帧对比图：同帧、同机位、同引擎的静态图（不做序列渲染）。

    blender -b --factory-startup -P m01_shots.py -- <pmx> <vmd> <label> <out_dir> <frames> <anchor> <offx,offy,offz> <lens> <physics 0/1>

机位由**静置骨骼**位置推出，因此同一 PMX 的不同物理变体必然同机位。
引擎固定 Workbench（自发光、无需布光），保证不同变体之间只有几何差异。
"""
import os
import sys

import addon_utils
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
pmx, vmd, label, out_dir = argv[0], argv[1], argv[2], argv[3]
frames = [int(x) for x in argv[4].split(",")]
anchor = argv[5]
off = [float(x) for x in argv[6].split(",")]
lens = float(argv[7])
physics = bool(int(argv[8]))
flat = bool(int(argv[9])) if len(argv) > 9 else False
os.makedirs(out_dir, exist_ok=True)

addon_utils.enable("bl_ext.user_default.mmd_tools", default_set=True, persistent=True)
scene = bpy.context.scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

types = {"MESH", "ARMATURE", "MORPHS"} | ({"PHYSICS"} if physics else set())
bpy.ops.mmd_tools.import_model(filepath=pmx, scale=0.08, types=types,
                               clean_model=True, rename_bones=True, log_level="ERROR")
root = next(o for o in bpy.data.objects if getattr(o, "mmd_type", None) == "ROOT")
arm = bpy.data.objects[root.name + "_arm"]

if physics:
    from bl_ext.user_default.mmd_tools.core import model as MModel
    from bl_ext.user_default.mmd_tools.core import rigid_body as MRigid
    MModel.Model(root).build()
    MRigid.setRigidBodyWorldEnabled(True)
    rbw = scene.rigidbody_world
    if rbw is not None:
        rbw.enabled = True
        rbw.substeps_per_frame = 10
        rbw.solver_iterations = 20
        rbw.point_cache.frame_start = 1
bpy.context.view_layer.update()

scene.frame_current = 1
bpy.ops.object.select_all(action="DESELECT")
root.select_set(True)
bpy.context.view_layer.objects.active = root
bpy.ops.mmd_tools.import_vmd(filepath=vmd, scale=0.08, bone_mapper="PMX",
                             rename_bones=True, use_underscore=False,
                             update_scene_settings=True)

names = {b.name for b in arm.data.bones}
if anchor not in names:
    raise SystemExit("锚点骨不存在：%s" % anchor)
target = arm.matrix_world @ arm.data.bones[anchor].head_local
cam_data = bpy.data.cameras.new("m01_cam")
cam_data.lens = lens
cam = bpy.data.objects.new("m01_cam", cam_data)
scene.collection.objects.link(cam)
cam.location = target + Vector(off)
cam.rotation_euler = (target + Vector((0.0, 0.0, 0.10)) - cam.location).to_track_quat("-Z", "Y").to_euler()
scene.camera = cam

avail = {e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
engine = next((e for e in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH")
               if e in avail), None)
if engine is None:
    raise SystemExit("没有可用引擎：%s" % avail)
scene.render.engine = engine
print("ENGINE", engine)

# EEVEE 需要布光：一盏主光 + 一盏补光 + 中性世界光，保证三个变体光照完全一致
world = scene.world or bpy.data.worlds.new("m01_world")
scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
if bg is not None:
    bg.inputs[0].default_value = (0.16, 0.17, 0.20, 1.0)
    bg.inputs[1].default_value = 1.0


def add_sun(name, energy, rot):
    data = bpy.data.lights.new(name, "SUN")
    data.energy = energy
    data.angle = 0.35
    obj = bpy.data.objects.new(name, data)
    obj.rotation_euler = rot
    scene.collection.objects.link(obj)
    return obj


add_sun("key", 3.5, (0.9, 0.0, 0.6))
add_sun("fill", 1.4, (1.2, 0.0, -2.2))
add_sun("rim", 1.0, (2.2, 0.0, 3.0))

if flat:
    # 副本 PMX 换了目录，贴图会找不到（渲染成洋红）——视觉对照只看形状，统一换成中性灰材质
    neutral = bpy.data.materials.new("m01_flat")
    neutral.use_nodes = True
    bsdf = neutral.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.62, 0.63, 0.66, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.65
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        obj.data.materials.clear()
        obj.data.materials.append(neutral)
    print("FLAT material override")

scene.render.resolution_x = 512
scene.render.resolution_y = 512
scene.render.image_settings.file_format = "PNG"
scene.render.film_transparent = False

max_f = max(frames)
# 相机跟锚点骨的**世界位置**移动：骨骼头位置由动作决定，物理回填只改旋转，
# 所以同一帧在不同变体上算出的机位必然一致（同帧同机位），而主体始终在画面里。
for f in range(1, max_f + 1):
    scene.frame_set(f)
    if f not in frames:
        continue
    bpy.context.view_layer.update()
    tgt = arm.matrix_world @ arm.pose.bones[anchor].head
    cam.location = tgt + Vector(off)
    cam.rotation_euler = (tgt + Vector((0.0, 0.0, 0.10)) - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = os.path.join(out_dir, "sheet_%s_f%04d.png" % (label, f))
    bpy.ops.render.render(write_still=True)
    print("SHOT", scene.render.filepath)
print("DONE", label, frames)
