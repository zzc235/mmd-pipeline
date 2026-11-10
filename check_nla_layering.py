"""可行性：两条 VMD 用 NLA 分层导入（use_nla），叠加后再烘焙导出。

这是社区路线（mmd_tools 自带的 use_nla + Blender NLA 烘焙），不碰二进制。
"""
import sys
import bpy
import addon_utils

sys.path.insert(0, r"E:/dsh pr/woker2")
from mmdpipe import vmd as V

PMX = r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309/星穹铁道—卡芙卡无外套/卡芙卡3.0.pmx"
M = r"E:/blender模型"
A = M + "/原神摇_by_ChildeDuck_c658aa3daba96482861d466e1f1868c7/原神摇/原神摇.vmd"
B = M + "/活着dj_by_lucky破_923ad74feee8ea23a61ed34b5798a78e/活着dj/活着dj_VMD-TDA.vmd"
GAP = 6

addon_utils.enable("mmd_tools", default_set=True, persistent=True)
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

a_end_src = V.load(A).frame_range[1]
print("A 源末帧 %d" % a_end_src)


def imp(path, at):
    sc.frame_current = at
    bpy.ops.object.select_all(action="DESELECT")
    root.select_set(True)
    bpy.context.view_layer.objects.active = root
    bpy.ops.mmd_tools.import_vmd(filepath=path, scale=0.08, bone_mapper="PMX",
                                 rename_bones=True, use_underscore=False,
                                 use_nla=True, update_scene_settings=False)
    act = arm.animation_data.action if arm.animation_data else None
    print("  导入@f%-4d action=%s tracks=%d"
          % (at, act.name if act else None,
             len(arm.animation_data.nla_tracks) if arm.animation_data else 0))


imp(A, 1)
first_end = a_end_src + 1          # VMD 0..N → Blender 1..N+1
imp(B, first_end + GAP)

print("\nNLA 轨道：")
for t in arm.animation_data.nla_tracks:
    for s in t.strips:
        print("  track=%-24s strip=%-24s range=(%.0f, %.0f) blend=%s"
              % (t.name, s.name, s.frame_start, s.frame_end, s.blend_type))

# 采样：A 段与 B 段各取几帧，看是否同时生效
def probe(f, names=("センター", "下半身", "頭")):
    sc.frame_set(f)
    return {n: tuple(round(v, 4) for v in (arm.matrix_world @ arm.pose.bones[n].matrix).translation)
            for n in names if n in arm.pose.bones}


print("\n分层后的姿态（若两张轨同时生效，B 段应有别于纯 A 的外推）：")
for f in (1, 100, int(first_end), int(first_end + GAP + 50), int(first_end + GAP + 200)):
    print("  f%-4d %s" % (f, probe(f)))
