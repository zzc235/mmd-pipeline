"""验证根链对齐注入（在拼接时间轴上注入）：
   1) 测量交接处差
   2) 施加 plan（单位换算 + 端点锚定）
   3) 重测：测量骨应 < 1mm；脚部应改善约等于注入量；B 段内部应整体平移、相对不变
"""
import json
import sys

sys.path.insert(0, r"E:/dsh pr/woker2")

import bpy
import addon_utils
from mathutils import Vector

from mmdpipe import align as align_mod
from mmdpipe import vmd as vmd_mod

PMX = r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309/星穹铁道—卡芙卡无外套/卡芙卡3.0.pmx"
PLAN = r"E:/dsh pr/woker2/out/align_plan.json"
CONCAT = r"E:/dsh pr/woker2/out/_align_check.vmd"
CONCAT2 = r"E:/dsh pr/woker2/out/_align_check2.vmd"
GAP = 6
SCALE = 0.08
WATCH = ["センター", "下半身", "足首.L", "足首.R", "頭", "手首.R", "全ての親"]

addon_utils.enable("mmd_tools", default_set=True, persistent=True)


def measure(path, a_end, b_start, watch_end=False):
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end, sc.frame_current = 1, 250, 1
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    before = set(o.name for o in bpy.data.objects)
    bpy.ops.mmd_tools.import_model(filepath=PMX, scale=SCALE, types={"MESH", "ARMATURE"},
                                   clean_model=True, rename_bones=True, log_level="ERROR")
    new = [bpy.data.objects[n] for n in set(o.name for o in bpy.data.objects) - before]
    root = next(o for o in new if getattr(o, "mmd_type", None) == "ROOT")
    arm = bpy.data.objects[root.name + "_arm"]
    bpy.ops.object.select_all(action="DESELECT")
    root.select_set(True)
    bpy.context.view_layer.objects.active = root
    bpy.ops.mmd_tools.import_vmd(filepath=path, scale=SCALE, bone_mapper="PMX",
                                 rename_bones=True, use_underscore=False,
                                 update_scene_settings=True)
    act = arm.animation_data.action if arm.animation_data else None
    print("   [measure] %s action=%s range=%s"
          % (path.split("/")[-1], act.name if act else None,
             tuple(act.frame_range) if act else None))
    out = {}

    def snap(f):
        sc.frame_set(f)
        return {n: (arm.matrix_world @ arm.pose.bones[n].matrix).translation.copy()
                for n in WATCH if n in arm.pose.bones}

    # mmd_tools 把 VMD 帧 f 导入到 Blender 帧 f+1
    out["a"] = snap(a_end + 1)
    out["b"] = snap(b_start + 1)
    if watch_end:
        out["b_end"] = snap(int(sc.frame_end))
    return out


plan = align_mod.AlignmentPlan.from_dict(json.load(open(PLAN, encoding="utf-8")))
print("t_world =", [round(v, 5) for v in plan.t],
      " t_vmd =", [round(v, 5) for v in plan.t_model])
print("PLAN mode=%s measure=%s inject=%s t=%s"
      % (plan.mode, plan.measure_bone, plan.inject_bone, plan.t))

rep = vmd_mod.concat([vmd_mod.load(plan.a_path), vmd_mod.load(plan.b_path)],
                     CONCAT, gap=GAP)
a_end = rep["spans"][0]["dst_range"][1]
b_start = rep["spans"][1]["dst_range"][0]
before = measure(CONCAT, a_end, b_start, watch_end=True)

motion = vmd_mod.load(CONCAT)
blob, info = align_mod.apply_to_concat(motion, plan, a_end, b_start, SCALE)
open(CONCAT2, "wb").write(blob)
print("APPLY", info)

after = measure(CONCAT2, a_end, b_start, watch_end=True)

print("原始采样对比（前 → 后）:")
for n in ("全ての親", "センター"):
    if n in before["a"] and n in after["a"]:
        print("  %-8s A末 %s → %s" % (n,
              tuple(round(v, 4) for v in before["a"][n]),
              tuple(round(v, 4) for v in after["a"][n])))
        print("  %-8s B首 %s → %s" % (n,
              tuple(round(v, 4) for v in before["b"][n]),
              tuple(round(v, 4) for v in after["b"][n])))

print("\n%-10s %-12s %-12s %-12s %s" % ("骨", "注入前(mm)", "注入后(mm)", "改善(mm)", "判定"))
ok1 = True
for n in WATCH:
    if n not in before["a"] or n not in after["a"]:
        continue
    d0 = (before["b"][n] - before["a"][n]).length * 1000
    d1 = (after["b"][n] - after["a"][n]).length * 1000
    flag = "✓" if d1 < 1.0 else ("改善" if d1 < d0 - 1 else "未改善")
    if n == plan.measure_bone and d1 >= 1.0:
        ok1 = False
    print("%-10s %-12.1f %-12.1f %-12.1f %s" % (n, d0, d1, d0 - d1, flag))

print("\n[验收2] B 段内部应整体平移 t，相对不变")
for n in ("センター", "下半身", "足首.L"):
    if n in before.get("b_end", {}) and n in after.get("b_end", {}):
        delta = after["b_end"][n] - before["b_end"][n]
        err = (delta - Vector(plan.t)).length * 1000
        print("  %-10s B末位移 %s  期望 t %s  误差 %.2f mm %s"
              % (n, tuple(round(v, 4) for v in delta),
                 tuple(round(v, 4) for v in plan.t), err, "OK" if err < 1 else "NG"))

print("\n[验收1] 测量骨 %s 注入后误差 < 1mm: %s" % (plan.measure_bone, "PASS" if ok1 else "FAIL"))
