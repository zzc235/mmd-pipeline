"""实测标定：注入 VMD 三个单位轴，测世界响应，反解基变换。

不做任何假设——单位、轴向、符号全部测出来。

    blender -b -P calibrate_align.py -- --a A.vmd --b B.vmd [--gap 6]
"""
import sys
import json
import struct

sys.path.insert(0, r"E:/dsh pr/woker2")

import bpy
import addon_utils
from mathutils import Vector, Matrix

from mmdpipe import vmd as vmd_mod

PMX = r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309/星穹铁道—卡芙卡无外套/卡芙卡3.0.pmx"
M = r"E:/blender模型"
A = M + "/爱乐之城_LaLa Land_by_小豆芽的日常_adf026480b2d1b2f38a4e4faa785560f/爱乐之城_LaLa Land/爱乐之城.vmd"
B = M + "/躺姿/和刻晴睡觉.vmd"
INJECT = "全ての親"
MEASURE = "センター"
DELTA = 2.0   # PMX 单位的探针大小

addon_utils.enable("mmd_tools", default_set=True, persistent=True)


def inject_concat(base_path, a_end, delta_vec):
    """把 delta_vec 加到 B 段（frame > a_end）的注入骨记录上，并在 a_end 锚定原值。"""
    mo = vmd_mod.load(base_path)
    d = mo.raw
    recs = []
    base = (0.0, 0.0, 0.0)
    have_end = False
    for i in range(mo.bone_count):
        s = mo.bone_start + i * vmd_mod.BONE_RECORD
        rec = bytearray(d[s:s + vmd_mod.BONE_RECORD])
        nm = bytes(rec[0:15]).split(b"\x00")[0].decode("cp932", "replace")
        fr = struct.unpack_from("<I", rec, 15)[0]
        if nm == INJECT:
            if fr <= a_end:
                base = struct.unpack_from("<3f", rec, 19)
                if fr == a_end:
                    have_end = True
            else:
                p = struct.unpack_from("<3f", rec, 19)
                struct.pack_into("<3f", rec, 19, p[0] + delta_vec[0],
                                 p[1] + delta_vec[1], p[2] + delta_vec[2])
        recs.append((fr, bytes(rec)))
    if not have_end and any(abs(v) > 1e-9 for v in delta_vec):
        recs.append((a_end, vmd_mod._make_bone_record(INJECT, a_end, base,
                                                      (0.0, 0.0, 0.0, 1.0))))
    recs.sort(key=lambda x: x[0])
    head = bytearray(d[:30 + (20 if mo.magic == "0002" else 10)])
    out = bytearray(head)
    out += struct.pack("<I", len(recs))
    out += b"".join(r for _, r in recs)
    out += struct.pack("<I", mo.morph_count)
    out += d[mo.morph_start:mo.morph_end]
    out += d[mo.tail_start:] if mo.tail_start < len(d) else struct.pack("<4I", 0, 0, 0, 0)
    return bytes(out)


def measure_world(path, frame):
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
    bpy.ops.mmd_tools.import_vmd(filepath=path, scale=0.08, bone_mapper="PMX",
                                 rename_bones=True, use_underscore=False,
                                 update_scene_settings=True)
    sc.frame_set(frame)
    return (arm.matrix_world @ arm.pose.bones[MEASURE].matrix).translation.copy()


rep = vmd_mod.concat([vmd_mod.load(A), vmd_mod.load(B)],
                     "E:/dsh pr/woker2/out/_cal_base.vmd", gap=6)
a_end = rep["spans"][0]["dst_range"][1]
b_start = rep["spans"][1]["dst_range"][0]
print("CAL  a_end=%d b_start=%d" % (a_end, b_start))

base_dir = "E:/dsh pr/woker2/out/_cal_base.vmd"
# mmd_tools 把 VMD 帧 f 导入到 Blender 帧 f+1，采样必须 +1
PROBE = b_start + 1
print("  采样帧 %d（VMD b_start=%d +1）" % (PROBE, b_start))
w0 = measure_world(base_dir, PROBE)
print("  基线 world %s" % (tuple(round(v, 5) for v in w0),))

cols = []
for axis in range(3):
    vec = [0.0, 0.0, 0.0]
    vec[axis] = DELTA
    p = "E:/dsh pr/woker2/out/_cal_ax%d.vmd" % axis
    open(p, "wb").write(inject_concat(base_dir, a_end, vec))
    w = measure_world(p, PROBE)
    d = w - w0
    cols.append(d / DELTA)
    print("  轴%d 注入 %.1f → 世界位移 %s  （每单位 %s）"
          % (axis, DELTA, tuple(round(v, 5) for v in d),
             tuple(round(v, 5) for v in (d / DELTA))))

Mx = Matrix((
    (cols[0].x, cols[1].x, cols[2].x),
    (cols[0].y, cols[1].y, cols[2].y),
    (cols[0].z, cols[1].z, cols[2].z),
))
print("\n基变换 M（vmd → world）:")
for r in range(3):
    print("   %8.5f %8.5f %8.5f" % (Mx[r][0], Mx[r][1], Mx[r][2]))
print("行列式 %.6f" % Mx.determinant())

inv = Mx.inverted()
print("\n逆 M⁻¹（world → vmd）:")
for r in range(3):
    print("   %8.5f %8.5f %8.5f" % (inv[r][0], inv[r][1], inv[r][2]))

t_world = Vector((0.271611, -0.009188, -0.042218))
t_vmd = inv @ t_world
print("\nt_world %s → t_vmd %s" % (tuple(round(v, 5) for v in t_world),
                                   tuple(round(v, 5) for v in t_vmd)))
json.dump({"basis_world_per_vmd": [list(r) for r in Mx],
           "inv": [list(r) for r in inv],
           "t_world": list(t_world), "t_vmd": list(t_vmd),
           "a_end": a_end, "b_start": b_start,
           "inject": INJECT, "measure": MEASURE},
          open("E:/dsh pr/woker2/out/align_basis.json", "w"), ensure_ascii=False, indent=2)
print("BASIS_WRITTEN")
