"""对比 fill=hold 与 fill=rest 在 B 段的实际效果（重点是 IK 腿骨）。"""
import bpy
import addon_utils

BASE = r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309/星穹铁道—卡芙卡无外套/卡芙卡3.0.pmx"
HOLD = r"E:/dsh pr/woker2/out/fill_hold.vmd"
REST = r"E:/dsh pr/woker2/out/fill_rest.vmd"
WATCH = ["足D.R", "ひざD.R", "足首D.R", "上半身", "頭"]
FRAMES = (100, 600)

addon_utils.enable("mmd_tools", default_set=True, persistent=True)
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

before = set(o.name for o in bpy.data.objects)
bpy.ops.mmd_tools.import_model(filepath=BASE, scale=0.08,
                               types={"MESH", "ARMATURE"}, clean_model=True,
                               rename_bones=True, log_level="ERROR")
new = [bpy.data.objects[n] for n in set(o.name for o in bpy.data.objects) - before]
root = next(o for o in new if getattr(o, "mmd_type", None) == "ROOT")
arm = bpy.data.objects[root.name + "_arm"]
sc = bpy.context.scene


def load_vmd(path):
    bpy.ops.object.select_all(action="DESELECT")
    root.select_set(True)
    bpy.context.view_layer.objects.active = root
    bpy.ops.mmd_tools.import_vmd(filepath=path, scale=0.08, bone_mapper="PMX",
                                 rename_bones=True, use_underscore=False,
                                 update_scene_settings=True)
    return arm.animation_data.action.name


def sample():
    out = {}
    for f in FRAMES:
        sc.frame_set(f)
        out[f] = {n: tuple(round(v, 4) for v in (arm.matrix_world @ arm.pose.bones[n].head))
                  for n in WATCH if n in arm.pose.bones}
    return out


a_hold = load_vmd(HOLD)
hold = sample()
print("HOLD action=%s" % a_hold)

a_rest = load_vmd(REST)
rest = sample()
print("REST action=%s" % a_rest)

print("\n%-10s %-6s %-30s %-30s %s" % ("骨", "帧", "hold", "rest", "差(m)"))
for n in WATCH:
    if n not in arm.pose.bones:
        continue
    for f in FRAMES:
        pa, pb = hold[f][n], rest[f][n]
        d = max(abs(pa[i] - pb[i]) for i in range(3))
        flag = "  <<<" if d > 0.01 else ""
        print("%-10s f%-5d %-30s %-30s %.4f%s" % (n, f, pa, pb, d, flag))
