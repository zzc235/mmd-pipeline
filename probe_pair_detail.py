"""拆解 爱乐之城 + 和刻晴睡觉 在交接处的世界位移来源。"""
import sys
import math
import bpy
import addon_utils

sys.path.insert(0, r"E:/dsh pr/woker2")
from mmdpipe import vmd as V

MODEL = r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309/星穹铁道—卡芙卡无外套/卡芙卡3.0.pmx"
M = r"E:/blender模型"
A = M + "/爱乐之城_LaLa Land_by_小豆芽的日常_adf026480b2d1b2f38a4e4faa785560f/爱乐之城_LaLa Land/爱乐之城.vmd"
B = M + "/躺姿/和刻晴睡觉.vmd"
GAP = 6
WATCH = ["全ての親", "操作中心", "センター", "グルーブ", "腰", "下半身",
         "左足", "右足", "足首.L", "足首.R", "つま先.L", "つま先.R"]

addon_utils.enable("mmd_tools", default_set=True, persistent=True)

rep = V.concat([V.load(A), V.load(B)], "E:/dsh pr/woker2/out/_probe_kq.vmd", gap=GAP)
spans = [(s["dst_range"][0], s["dst_range"][1]) for s in rep["spans"]]
a_end, b_start = spans[0][1], spans[1][0]
print("交接帧 A末=%d  B首=%d  （A 源 0..%d，B 源 0..%d）"
      % (a_end, b_start, rep["spans"][0]["src_range"][1], rep["spans"][1]["src_range"][1]))

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
before = set(o.name for o in bpy.data.objects)
bpy.ops.mmd_tools.import_model(filepath=MODEL, scale=0.08, types={"MESH", "ARMATURE"},
                               clean_model=True, rename_bones=True, log_level="ERROR")
new = [bpy.data.objects[n] for n in set(o.name for o in bpy.data.objects) - before]
root = next(o for o in new if getattr(o, "mmd_type", None) == "ROOT")
arm = bpy.data.objects[root.name + "_arm"]

bpy.ops.object.select_all(action="DESELECT")
root.select_set(True)
bpy.context.view_layer.objects.active = root
bpy.ops.mmd_tools.import_vmd(filepath="E:/dsh pr/woker2/out/_probe_kq.vmd", scale=0.08,
                             bone_mapper="PMX", rename_bones=True,
                             use_underscore=False, update_scene_settings=True)
sc = bpy.context.scene


def snap(f):
    sc.frame_set(f)
    out = {}
    for n in WATCH:
        pb = arm.pose.bones.get(n)
        if pb:
            m = arm.matrix_world @ pb.matrix
            out[n] = (m.translation.copy(), m.to_quaternion())
    return out


sa, sb = snap(a_end), snap(b_start)
print("\n%-12s %-34s %-34s %-10s %s" % ("骨", "A末 世界", "B首 世界", "位移mm", "局部差mm"))
for n in WATCH:
    if n not in sa or n not in sb:
        continue
    d = (sb[n][0] - sa[n][0]).length * 1000
    sc.frame_set(a_end)
    la = arm.pose.bones[n].location.copy()
    sc.frame_set(b_start)
    lb = arm.pose.bones[n].location.copy()
    ld = (lb - la).length * 1000
    print("%-12s %-34s %-34s %-10.1f %.1f"
          % (n, tuple(round(v, 3) for v in sa[n][0]),
             tuple(round(v, 3) for v in sb[n][0]), d, ld))

print("\n朝向（B首 相对 A末，欧拉 Z）:")
for n in ("センター", "グルーブ", "下半身"):
    if n in sa and n in sb:
        r = sb[n][1] @ sa[n][1].inverted()
        print("  %-8s Z %.1f°  X %.1f°  Y %.1f°"
              % (n, *[math.degrees(v) for v in r.to_euler()]))
