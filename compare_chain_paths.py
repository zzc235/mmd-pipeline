"""对比两条路在交接处的姿态连续性：字节拼接 vs NLA 烘焙。"""
import sys
import bpy
import addon_utils
from mathutils import Vector

sys.path.insert(0, r"E:/dsh pr/woker2")

PMX = r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309/星穹铁道—卡芙卡无外套/卡芙卡3.0.pmx"
CASES = [("字节拼接", r"E:/dsh pr/woker2/out/fill_none.vmd"),
         ("NLA烘焙", r"E:/dsh pr/woker2/out/nla_chain.vmd")]
WATCH = ["センター", "下半身", "足首.L", "足首.R", "頭", "左手首"]
FRAMES = [440, 445, 446, 447, 448, 450, 452, 453, 454, 455, 460]

addon_utils.enable("mmd_tools", default_set=True, persistent=True)


def sample(path):
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end, sc.frame_current = 1, 250, 1
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    before = set(o.name for o in bpy.data.objects)
    bpy.ops.mmd_tools.import_model(filepath=PMX, scale=0.08, types={"MESH", "ARMATURE"},
                                   clean_model=True, rename_bones=True, log_level="ERROR")
    new = [bpy.data.objects[n] for n in set(o.name for o in bpy.data.objects) - before]
    root = next(o for o in new if getattr(o, "mmd_type", None) == "ROOT")
    arm = max([o for o in new if o.type == "ARMATURE"], key=lambda o: len(o.data.bones))
    bpy.ops.object.select_all(action="DESELECT")
    root.select_set(True)
    bpy.context.view_layer.objects.active = root
    bpy.ops.mmd_tools.import_vmd(filepath=path, scale=0.08, bone_mapper="PMX",
                                 rename_bones=True, use_underscore=False,
                                 update_scene_settings=True)
    out = {}
    for f in FRAMES:
        sc.frame_set(f + 1)   # VMD f → Blender f+1
        out[f] = {n: (arm.matrix_world @ arm.pose.bones[n].matrix).translation.copy()
                  for n in WATCH if n in arm.pose.bones}
    return out


data = {}
for tag, path in CASES:
    data[tag] = sample(path)
    print("采样完成 %s" % tag)

print("\n%-6s %-28s %-28s %s" % ("帧", "字节拼接 下半身", "NLA烘焙 下半身", "差异(mm)"))
for f in FRAMES:
    a = data["字节拼接"][f].get("下半身")
    b = data["NLA烘焙"][f].get("下半身")
    if a and b:
        print("%-6d %-28s %-28s %.1f"
              % (f, tuple(round(v, 4) for v in a), tuple(round(v, 4) for v in b),
                 (a - b).length * 1000))

print("\n逐帧步进（相邻帧位移，看哪里在跳）：")
for tag in ("字节拼接", "NLA烘焙"):
    print("  [%s]" % tag)
    prev = None
    for f in FRAMES:
        p = data[tag][f].get("下半身")
        if p is None:
            continue
        if prev is not None:
            print("    f%-4d → f%-4d  步进 %6.1f mm" % (prev[0], f, (p - prev[1]).length * 1000))
        prev = (f, p)
