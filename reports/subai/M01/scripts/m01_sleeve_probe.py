"""M01 S5 探针：卡芙卡袖筒「静态策略」对照。

    blender -b --factory-startup -P m01_sleeve_probe.py -- <pmx> <vmd> <variant> <out_dir> [--policy off|strict] [--frames ...] [--render 1]

variant 只用于命名；判据是数字：
  * 袖筒 48 根骨的逐帧局部转角增量（度）与 >45°/帧 次数
  * 袖筒 ROI 顶点的逐帧最大位移
  * 非袖子物理骨的同一指标（证明静态策略没有波及别的单元）

policy=strict 等于现有 `--physics-policy strict`：静音袖筒骨上的 COPY_ROTATION / COPY_TRANSFORMS。
"""
import json
import math
import os
import sys

import addon_utils
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
pmx, vmd, variant, out_dir = argv[0], argv[1], argv[2], argv[3]
policy = "off"
frames = [1, 15, 30, 45, 60]
do_render = True
i = 4
while i < len(argv):
    if argv[i] == "--policy":
        policy = argv[i + 1]; i += 2
    elif argv[i] == "--frames":
        frames = [int(x) for x in argv[i + 1].split(",")]; i += 2
    elif argv[i] == "--render":
        do_render = bool(int(argv[i + 1])); i += 2
    else:
        i += 1
os.makedirs(out_dir, exist_ok=True)

# ---- 先用纯 Python 判定器拿袖筒结构（不依赖 Blender 命名）
sys.path.insert(0, r"E:\dsh pr\woker2")
from mmdpipe import physics, pmx as pmx_mod  # noqa: E402

model = pmx_mod.load(pmx)
rep = physics.classify(model)
sleeve_units = [{"uid": u.uid, "bodies": len(u.bodies), "joints": len(u.joint_ids),
                 "cycle_rank": u.cycle_rank, "welded_ratio": round(u.welded_ratio, 3),
                 "modes": u.modes, "anchor_bone": u.anchor_bone}
                for u in rep.units
                if len(u.bodies) >= 20 and u.cycle_rank >= 20 and 2 not in (u.modes or {})]
sleeve_bones = physics.bones_for_policy(rep, "strict")
modes = {}
for r in model.rigids:
    modes[r.mode] = modes.get(r.mode, 0) + 1

addon_utils.enable("bl_ext.user_default.mmd_tools", default_set=True, persistent=True)
scene = bpy.context.scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

bpy.ops.mmd_tools.import_model(filepath=pmx, scale=0.08,
                               types={"MESH", "ARMATURE", "MORPHS", "PHYSICS"},
                               clean_model=True, rename_bones=True, log_level="ERROR")
root = next(o for o in bpy.data.objects if getattr(o, "mmd_type", None) == "ROOT")
arm = bpy.data.objects[root.name + "_arm"]
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
mesh = bpy.data.objects.get(root.name + "_mesh") or max(meshes, key=lambda o: len(o.data.vertices))

from bl_ext.user_default.mmd_tools.core import model as MModel  # noqa: E402
from bl_ext.user_default.mmd_tools.core import rigid_body as MRigid  # noqa: E402
build_error = None
try:
    MModel.Model(root).build()
except Exception as exc:  # noqa: BLE001
    build_error = str(exc)
MRigid.setRigidBodyWorldEnabled(True)
rbw = scene.rigidbody_world
if rbw is not None:
    rbw.enabled = True
    rbw.substeps_per_frame = 10
    rbw.solver_iterations = 20
    rbw.point_cache.frame_start = 1
bpy.context.view_layer.update()

info = {"variant": variant, "policy": policy, "pmx": pmx, "vmd": vmd,
        "blender": bpy.app.version_string, "build_error": build_error,
        "is_built": bool(root.mmd_root.is_built),
        "pmx_modes": modes, "sleeve_units": sleeve_units,
        "sleeve_bones_pmx": sleeve_bones,
        "rigids": len([o for o in bpy.data.objects
                       if getattr(o, "mmd_type", None) == "RIGID_BODY"])}

# ---- 静音（strict 策略）：与 stage_physics_policy 同一做法
muted, still = [], []
if policy == "strict":
    target = set(sleeve_bones)
    for pb in arm.pose.bones:
        if pb.name not in target:
            continue
        for con in pb.constraints:
            if con.type in ("COPY_ROTATION", "COPY_TRANSFORMS") and not con.mute:
                con.mute = True
                muted.append(pb.name)
    for pb in arm.pose.bones:
        if pb.name in target:
            for con in pb.constraints:
                if con.type in ("COPY_ROTATION", "COPY_TRANSFORMS") and not con.mute:
                    still.append(pb.name)
info["muted_constraints"] = len(muted)
info["muted_bones"] = len(set(muted))
info["still_unmuted"] = sorted(set(still))

sleeve_set = set(sleeve_bones)
bones_missing = sorted(b for b in sleeve_bones if b not in arm.pose.bones)
info["sleeve_bones_missing_in_blender"] = bones_missing
sleeve_present = [b for b in sleeve_bones if b in arm.pose.bones]

# 非袖子物理骨（对照组）：带 COPY_ROTATION 但不在袖筒集合里的骨
other_physics_bones = [pb.name for pb in arm.pose.bones
                       if pb.name not in sleeve_set
                       and any(c.type in ("COPY_ROTATION", "COPY_TRANSFORMS") for c in pb.constraints)]
info["other_physics_bones"] = len(other_physics_bones)

# ---- 袖筒 ROI（权重主导骨落在袖筒骨集合内的顶点）
bone_names = {b.name for b in arm.data.bones}
sleeve_parts = []
for obj in meshes:
    vg = {g.index: g.name for g in obj.vertex_groups}
    idx = []
    for v in obj.data.vertices:
        best, bw = "", -1.0
        for g in v.groups:
            if g.weight > bw and vg.get(g.group, "") in bone_names:
                best, bw = vg.get(g.group, ""), g.weight
        if best in sleeve_set:
            idx.append(v.index)
    if idx:
        sleeve_parts.append((obj, idx))
info["sleeve_roi"] = {"parts": len(sleeve_parts),
                      "verts": sum(len(x) for _, x in sleeve_parts)}
if not sleeve_parts:
    print("WARN 找不到袖筒 ROI 顶点，只报骨骼指标")

# ---- 动作
scene.frame_current = 1
bpy.ops.object.select_all(action="DESELECT")
root.select_set(True)
bpy.context.view_layer.objects.active = root
bpy.ops.mmd_tools.import_vmd(filepath=vmd, scale=0.08, bone_mapper="PMX",
                             rename_bones=True, use_underscore=False,
                             update_scene_settings=True)
action = arm.animation_data.action if arm.animation_data else None
a_start, a_end = (int(round(v)) for v in action.frame_range)
info["action"] = action.name
info["action_range"] = [a_start, a_end]
scene.frame_start, scene.frame_end = a_start, a_end
picks = [f for f in frames if a_start <= f <= a_end] or [a_start]
info["picks"] = picks
max_f = max(picks)

# ---- 相机：静置骨骼（同一 PMX，对所有变体一致）
anchor = "左ひじ" if "左ひじ" in bone_names else ("上半身2" if "上半身2" in bone_names else bone_names and next(iter(bone_names)))
target = arm.matrix_world @ arm.data.bones[anchor].head_local
cam_data = bpy.data.cameras.new("m01_cam")
cam_data.lens = 50
cam = bpy.data.objects.new("m01_cam", cam_data)
scene.collection.objects.link(cam)
cam.location = target + Vector((0.35, -1.65, 0.15))
cam.rotation_euler = (target + Vector((0.0, 0.0, 0.10)) - cam.location).to_track_quat("-Z", "Y").to_euler()
scene.camera = cam
info["camera"] = {"anchor": anchor, "target": [round(v, 4) for v in target],
                  "location": [round(v, 4) for v in cam.location]}
avail = {e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
engine = next((e for e in ("BLENDER_WORKBENCH", "BLENDER_EEVEE") if e in avail), "BLENDER_WORKBENCH")
scene.render.engine = engine
scene.render.resolution_x = 480
scene.render.resolution_y = 480
info["engine"] = engine


def quat_of(pb):
    return pb.matrix.to_quaternion()


def angle_deg(q1, q2) -> float:
    d = q1.rotation_difference(q2)
    return math.degrees(abs(d.angle))


prev = {}
rows = []
over45_total = 0
over45_frames = []
worst_all = []
max_per_frame = []
for f in range(1, max_f + 1):
    scene.frame_set(f)
    bpy.context.view_layer.update()
    cur = {b: quat_of(arm.pose.bones[b]) for b in sleeve_present}
    cur_o = {b: quat_of(arm.pose.bones[b]) for b in other_physics_bones}
    frame_delta = None
    if prev:
        deltas = {b: angle_deg(prev["bones"][b], cur[b]) for b in sleeve_present}
        odeltas = {b: angle_deg(prev["other"][b], cur_o[b]) for b in other_physics_bones}
        dv = sorted(deltas.items(), key=lambda kv: -kv[1])
        n_over = sum(1 for _, v in dv if v > 45.0)
        over45_total += n_over
        if n_over:
            over45_frames.append({"frame": f, "bones_over45": n_over,
                                  "worst_bone": dv[0][0], "worst_deg": round(dv[0][1], 3)})
        if dv:
            worst_all.append({"frame": f, "bone": dv[0][0], "deg": round(dv[0][1], 3)})
            max_per_frame.append({"frame": f, "max": round(dv[0][1], 3),
                                  "mean": round(sum(deltas.values()) / len(deltas), 3),
                                  "other_max": round(max(odeltas.values()), 3) if odeltas else None})
        frame_delta = {"max": round(dv[0][1], 4) if dv else 0.0,
                       "mean": round(sum(deltas.values()) / len(deltas), 4) if deltas else 0.0,
                       "over45": n_over,
                       "worst": [(b, round(v, 3)) for b, v in dv[:5]],
                       "other_max": round(max(odeltas.values()), 4) if odeltas else 0.0}
    if f in picks:
        dg = bpy.context.evaluated_depsgraph_get()
        pts = []
        for obj, idx in sleeve_parts:
            ev = obj.evaluated_get(dg)
            me = ev.to_mesh()
            mw = ev.matrix_world
            for vi in idx:
                p = mw @ me.vertices[vi].co
                pts.append((p.x, p.y, p.z))
            ev.to_mesh_clear()
        row = {"frame": f, "sleeve_verts": [[round(c, 6) for c in p] for p in pts],
               "sleeve_extent": ([round(max(p[k] for p in pts) - min(p[k] for p in pts), 5)
                                  for k in range(3)] if pts else None)}
        if prev.get("sleeve"):
            d = [math.dist(p, q) for p, q in zip(pts, prev["sleeve"])]
            row["sleeve_vert_delta"] = {"max": round(max(d), 6),
                                        "mean": round(sum(d) / len(d), 6)}
        if frame_delta is not None:
            row["sleeve_bone_delta"] = frame_delta
        rows.append(row)
        if do_render and (f == picks[0] or f == picks[len(picks) // 2]):
            scene.render.filepath = os.path.join(out_dir, "sleeve_%s_f%04d.png" % (variant, f))
            try:
                bpy.ops.render.render(write_still=True)
                row["render"] = scene.render.filepath
            except Exception as exc:  # noqa: BLE001
                row["render_error"] = str(exc)
    prev = {"frame": f, "bones": cur, "other": cur_o, "sleeve": pts if f in picks else prev.get("sleeve")}

info["bone_delta_stats"] = {
    "frames_stepped": max_f,
    "over45_total": over45_total,
    "over45_frames": over45_frames[:40],
    "over45_frame_count": len(over45_frames),
    "global_max": max((w["deg"] for w in worst_all), default=None),
    "global_max_at": max(worst_all, key=lambda w: w["deg"]) if worst_all else None,
    "mean_of_frame_max": round(sum(m["max"] for m in max_per_frame) / len(max_per_frame), 3)
    if max_per_frame else None,
    "other_global_max": max((m["other_max"] or 0 for m in max_per_frame), default=None),
}

out = dict(info, frames=rows)
path = os.path.join(out_dir, "sleeve_%s.json" % variant)
with open(path, "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False)

print("SLEEVE %s policy=%s built=%s rigids=%d sleeve_bones=%d muted=%d roi_verts=%d engine=%s"
      % (variant, policy, info["is_built"], info["rigids"], len(sleeve_present),
         info["muted_constraints"], info["sleeve_roi"]["verts"], engine))
for row in rows:
    b = row.get("sleeve_bone_delta") or {}
    print("  f%3d bone_max=%s over45=%s other_max=%s vert_delta=%s"
          % (row["frame"], b.get("max"), b.get("over45"), b.get("other_max"),
             (row.get("sleeve_vert_delta") or {}).get("max")))
print("SAVED", path)
