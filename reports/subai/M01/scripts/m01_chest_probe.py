"""M01 胸部动力学探针：同一 PMX 的三个变体在相同帧、相同机位下量胸口顶点。

用法：
    blender -b --factory-startup -P m01_chest_probe.py -- <pmx> <vmd> <variant> <out_dir> [--physics 1] [--frames 1,15,30,45,60] [--render 1]

variant 只影响输出命名；判据靠数字，不靠名字。
约束：
  * 只连续步进（frame_set 逐帧），不跳帧，保证 bullet 动力学连续；
  * 相机由**静置骨骼**位置推出，三个变体必然同机位；
  * 不改源 PMX，不写 .blend。
"""
import json
import os
import sys

import addon_utils
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
pmx, vmd, variant, out_dir = argv[0], argv[1], argv[2], argv[3]
physics = True
frames = [1, 15, 30, 45, 60]
do_render = True
i = 4
while i < len(argv):
    if argv[i] == "--physics":
        physics = bool(int(argv[i + 1])); i += 2
    elif argv[i] == "--frames":
        frames = [int(x) for x in argv[i + 1].split(",")]; i += 2
    elif argv[i] == "--render":
        do_render = bool(int(argv[i + 1])); i += 2
    else:
        i += 1
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
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
mesh = bpy.data.objects.get(root.name + "_mesh") or max(meshes, key=lambda o: len(o.data.vertices))

info = {"variant": variant, "pmx": pmx, "vmd": vmd, "physics": physics,
        "blender": bpy.app.version_string}

build_error = None
if physics:
    from bl_ext.user_default.mmd_tools.core import model as MModel
    try:
        MModel.Model(root).build()
    except Exception as exc:  # noqa: BLE001
        build_error = str(exc)
    from bl_ext.user_default.mmd_tools.core import rigid_body as MRigid
    MRigid.setRigidBodyWorldEnabled(True)
    rbw = scene.rigidbody_world
    if rbw is not None:
        rbw.enabled = True
        rbw.substeps_per_frame = 10
        rbw.solver_iterations = 20
        rbw.point_cache.frame_start = 1
info["build_error"] = build_error
info["is_built"] = bool(root.mmd_root.is_built)
bpy.context.view_layer.update()

# ---- ROI：以静置骨骼名取权重主导顶点（与 PMX 刚体 24–29 的骨名一致）
CHEST_BONES = ["胸.R", "胸１.R", "胸２.R", "胸.L", "胸１.L", "胸２.L"]
TORSO_BONES = ["上半身2"]
HIP_BONES = ["下半身", "腰", "下半身2"]
bone_names = {b.name for b in arm.data.bones}
info["chest_bones_present"] = [b for b in CHEST_BONES if b in bone_names]
info["torso_bones_present"] = [b for b in TORSO_BONES if b in bone_names]
info["hip_bones_present"] = [b for b in HIP_BONES if b in bone_names]


def collect_roi(bones):
    """按"权重最大的**骨骼**组"取 ROI。

    必须排除 mmd_tools 自带的 mmd_edge_scale / mmd_vertex_order 这类非骨骼组：
    它们对每个顶点权重都是 1.0，不排除的话所有顶点都会归到它名下（实测如此）。
    """
    parts = []
    for obj in meshes:
        vg = {g.index: g.name for g in obj.vertex_groups}
        idx = []
        for v in obj.data.vertices:
            best, bw = "", -1.0
            for g in v.groups:
                if g.weight > bw and vg.get(g.group, "") in bone_names:
                    best, bw = vg.get(g.group, ""), g.weight
            if best in bones:
                idx.append(v.index)
        if idx:
            parts.append((obj, idx))
    return parts


chest_parts = collect_roi(set(CHEST_BONES))
torso_parts = collect_roi(set(TORSO_BONES))
hip_parts = collect_roi(set(HIP_BONES))
info["roi"] = {"chest_parts": len(chest_parts),
               "chest_verts": sum(len(x) for _, x in chest_parts),
               "torso_verts": sum(len(x) for _, x in torso_parts),
               "hip_verts": sum(len(x) for _, x in hip_parts)}
if not chest_parts:
    raise SystemExit("找不到胸口 ROI 顶点：%s" % CHEST_BONES)

# ---- 动作（import_vmd 的 poll 要求 root 处于选中/激活状态，否则 context incorrect）
scene.frame_current = 1
bpy.ops.object.select_all(action="DESELECT")
root.select_set(True)
bpy.context.view_layer.objects.active = root
bpy.ops.mmd_tools.import_vmd(filepath=vmd, scale=0.08, bone_mapper="PMX",
                             rename_bones=True, use_underscore=False,
                             update_scene_settings=True)
action = arm.animation_data.action if arm.animation_data else None
info["action"] = action.name if action else None
if action is None:
    raise SystemExit("动作没导入")
a_start, a_end = (int(round(v)) for v in action.frame_range)
info["action_range"] = [a_start, a_end]
scene.frame_start = a_start
scene.frame_end = a_end
picks = [f for f in frames if a_start <= f <= a_end]
if not picks:
    picks = [a_start]
info["picks"] = picks

# ---- 约束/刚体快照（build 之后、step 之前）
cons_hist = {}
for pb in arm.pose.bones:
    for c in pb.constraints:
        cons_hist[c.type] = cons_hist.get(c.type, 0) + 1
chest_cons = {}
for pb in arm.pose.bones:
    for c in pb.constraints:
        if pb.name in CHEST_BONES:
            chest_cons.setdefault(pb.name, []).append(
                {"type": c.type, "mute": c.mute,
                 "target": c.target.name if getattr(c, "target", None) else None,
                 "target_type": getattr(getattr(c, "target", None), "mmd_type", None)})
rigids = [o for o in bpy.data.objects if getattr(o, "mmd_type", None) == "RIGID_BODY"]
info["after_build"] = {"rigids": len(rigids), "constraints": cons_hist,
                       "chest_constraints": chest_cons,
                       "chest_cons_total": sum(len(v) for v in chest_cons.values())}
info["rigid_types"] = {}
for o in rigids:
    t = o.mmd_rigid.type
    info["rigid_types"][t] = info["rigid_types"].get(t, 0) + 1
info["chest_rigids"] = [
    {"obj": o.name, "mmd_name": o.mmd_rigid.name, "type": o.mmd_rigid.type,
     "bone": o.mmd_rigid.bone,
     "kinematic": o.rigid_body.kinematic if o.rigid_body else None,
     "rb_enabled": o.rigid_body.enabled if o.rigid_body else None}
    for o in rigids if o.mmd_rigid.name in ("右胸", "右胸１", "右胸２", "左胸", "左胸１", "左胸２")]
track_objs = [o for o in rigids if o.mmd_rigid.name in ("右胸", "右胸１", "右胸２",
                                                         "左胸", "左胸１", "左胸２")]
# 额外跟踪几个明显的动态体，用来证明物理真的在跑（而不是整体静止）
for nm in ("後ろ髪", "スカート", "前髪", "胸"):
    for o in rigids:
        if o.mmd_rigid.name == nm and o not in track_objs:
            track_objs.append(o)
            break
info["tracked_rigids"] = [o.name for o in track_objs]

# ---- 同机位相机：由静置骨骼推出，三个变体必然一致
chest_bone = next(b for b in CHEST_BONES if b in bone_names)
target = arm.matrix_world @ arm.data.bones[chest_bone].head_local
dist = 1.15
cam_data = bpy.data.cameras.new("m01_cam")
cam_data.lens = 60
cam = bpy.data.objects.new("m01_cam", cam_data)
scene.collection.objects.link(cam)
cam.location = target + Vector((0.0, -dist, 0.05))
cam.rotation_euler = (target + Vector((0.0, 0.0, 0.05)) - cam.location).to_track_quat("-Z", "Y").to_euler()
scene.camera = cam
info["camera"] = {"target": [round(v, 4) for v in target],
                  "location": [round(v, 4) for v in cam.location],
                  "lens": 60, "dist": dist}

avail = {e.identifier for e in
         bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
engine = next((e for e in ("BLENDER_WORKBENCH", "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE")
               if e in avail), "BLENDER_WORKBENCH")
scene.render.engine = engine
scene.render.resolution_x = 420
scene.render.resolution_y = 420
if engine == "BLENDER_WORKBENCH":
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "MATERIAL"
    shading.show_cavity = False
    shading.show_object_outline = False
    scene.render.film_transparent = False
info["engine"] = engine

rows = []
last = 0
for f in picks:
    for step in range(last + 1, f + 1):
        scene.frame_set(step)
    last = f
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()

    def sample(parts):
        pts = []
        for obj, idx in parts:
            ev = obj.evaluated_get(dg)
            me = ev.to_mesh()
            mw = ev.matrix_world
            for vi in idx:
                p = mw @ me.vertices[vi].co
                pts.append((p.x, p.y, p.z))
            ev.to_mesh_clear()
        return pts

    def stats(pts):
        if not pts:
            return None
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]; zs = [p[2] for p in pts]
        n = len(pts)
        return {"n": n,
                "extent": [round(max(xs) - min(xs), 5),
                           round(max(ys) - min(ys), 5),
                           round(max(zs) - min(zs), 5)],
                "centroid": [round(sum(xs) / n, 5), round(sum(ys) / n, 5),
                             round(sum(zs) / n, 5)]}

    chest = sample(chest_parts)
    torso = sample(torso_parts)
    hip = sample(hip_parts)
    row = {"frame": f, "chest": stats(chest), "torso": stats(torso), "hip": stats(hip),
           "chest_verts": [[round(c, 6) for c in p] for p in chest],
           "rigids": {o.name: [round(v, 5) for v in o.matrix_world.translation]
                      for o in track_objs}}
    if physics:
        rbw = scene.rigidbody_world
        row["rbw"] = {"enabled": rbw.enabled, "substeps": rbw.substeps_per_frame,
                      "solver": rbw.solver_iterations,
                      "point_cache_frame": [rbw.point_cache.frame_start, rbw.point_cache.frame_end]}
    rows.append(row)

    if do_render and f in (picks[0], picks[len(picks) // 2]):
        scene.render.filepath = os.path.join(out_dir, "shot_%s_f%04d.png" % (variant, f))
        try:
            bpy.ops.render.render(write_still=True)
            row["render"] = scene.render.filepath
        except Exception as exc:  # noqa: BLE001
            row["render_error"] = str(exc)

# 胸部相对髋的横向比例：折叠会被压小
for row in rows:
    if row["chest"] and row["hip"]:
        hx = row["hip"]["extent"][0]
        row["chest_hip_ratio"] = round(row["chest"]["extent"][0] / hx, 4) if hx > 1e-6 else None

out = dict(info, frames=rows)
path = os.path.join(out_dir, "probe_%s.json" % variant)
with open(path, "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False)

head = "PROBE %s physics=%s built=%s rigids=%s chest_cons=%s engine=%s" % (
    variant, physics, info["is_built"], len(rigids),
    info["after_build"]["chest_cons_total"], engine)
print(head)
for row in rows:
    c = row["chest"]
    print("  f%3d chest n=%d ext=%s ratio=%s"
          % (row["frame"], c["n"], c["extent"], row.get("chest_hip_ratio")))
print("SAVED", path)
