"""查导入后的骨架：根链骨上有没有约束（付与/IK/限制），以及 全ての親 的实际作用。"""
import sys
import bpy
import addon_utils

sys.path.insert(0, r"E:/dsh pr/woker2")
from mmdpipe import vmd as V

PMX = r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309/星穹铁道—卡芙卡无外套/卡芙卡3.0.pmx"

addon_utils.enable("mmd_tools", default_set=True, persistent=True)
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
before = set(o.name for o in bpy.data.objects)
bpy.ops.mmd_tools.import_model(filepath=PMX, scale=0.08, types={"MESH", "ARMATURE"},
                               clean_model=True, rename_bones=True, log_level="ERROR")
new = [bpy.data.objects[n] for n in set(o.name for o in bpy.data.objects) - before]
root = next(o for o in new if getattr(o, "mmd_type", None) == "ROOT")
arm = bpy.data.objects[root.name + "_arm"]

print("骨架 object matrix_world:")
mw = arm.matrix_world
for r in range(4):
    print("   %8.4f %8.4f %8.4f %8.4f" % tuple(mw[r]))

print("\n根链骨的约束：")
for n in ("操作中心", "全ての親", "センター", "グルーブ", "腰", "下半身",
          "左足", "右足", "左ひざ", "右ひざ", "足首.L", "足首.R"):
    pb = arm.pose.bones.get(n)
    if not pb:
        print("  %-8s 不存在" % n)
        continue
    cons = [(c.type, c.name) for c in pb.constraints]
    lock = tuple(pb.lock_location)
    print("  %-8s 约束 %-40s lock_location %s" % (n, cons if cons else "-", lock))

print("\nbone.matrix_local（静置）的 3x3：")
for n in ("全ての親", "センター"):
    b = arm.data.bones.get(n)
    if b:
        m = b.matrix_local.to_3x3()
        print("  %s" % n)
        for r in range(3):
            print("     %8.4f %8.4f %8.4f" % (m[r][0], m[r][1], m[r][2]))

print("\n全ての親 的 mmd 属性：")
pb = arm.pose.bones.get("全ての親")
if pb:
    for attr in ("mmd_bone", ):
        if hasattr(pb, attr):
            mb = getattr(pb, attr)
            for f in ("is_visible", "is_controllable", "has_additional_rotate",
                      "additional_transform_bone", "is_tip", "transform_order"):
                if hasattr(mb, f):
                    print("   %-28s %s" % (f, getattr(mb, f)))
