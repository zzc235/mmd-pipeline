"""验证 mmd_tools 的 VMD 往返保真度：导入 → 导出 → 逐轨对比。

如果往返够准，多动作拼接就不用碰二进制，改走「NLA 叠加 → 烘焙 → 导出」。
"""
import sys
import bpy
import addon_utils

sys.path.insert(0, r"E:/dsh pr/woker2")
from mmdpipe import vmd as V

PMX = r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309/星穹铁道—卡芙卡无外套/卡芙卡3.0.pmx"
SRC = r"E:/blender模型/原神摇_by_ChildeDuck_c658aa3daba96482861d466e1f1868c7/原神摇/原神摇.vmd"
OUT = r"E:/dsh pr/woker2/out/roundtrip.vmd"

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

bpy.ops.object.select_all(action="DESELECT")
root.select_set(True)
bpy.context.view_layer.objects.active = root
bpy.ops.mmd_tools.import_vmd(filepath=SRC, scale=0.08, bone_mapper="PMX",
                             rename_bones=True, use_underscore=False,
                             update_scene_settings=True)
arms = [o for o in new if o.type == "ARMATURE"]
arm = max(arms, key=lambda o: len(o.data.bones))
act = arm.animation_data.action if arm.animation_data else None
print("IMPORT action=%s range=%s" % (act.name if act else None,
                                    tuple(act.frame_range) if act else None))

# 导出
try:
    bpy.ops.mmd_tools.export_vmd(filepath=OUT)
    print("EXPORT ok ->", OUT)
except Exception as exc:
    print("EXPORT FAILED:", exc)
    raise SystemExit(1)

a = V.load(SRC)
b = V.load(OUT)
print("源  骨记录 %d 骨轨 %d 表情 %d 范围 %s" % (a.bone_count, len(a.bone_tracks), a.morph_count, a.frame_range))
print("回  骨记录 %d 骨轨 %d 表情 %d 范围 %s" % (b.bone_count, len(b.bone_tracks), b.morph_count, b.frame_range))
print("骨名集合差异:", len(set(a.bone_tracks) ^ set(b.bone_tracks)))


def table(m):
    d = m.raw
    out = {}
    for i in range(m.bone_count):
        s = m.bone_start + i * 111
        n = d[s:s + 15].split(b"\x00")[0].decode("cp932", "replace")
        f = int.from_bytes(d[s + 15:s + 19], "little")
        import struct
        out[(n, f)] = struct.unpack_from("<7f", d, s + 19)
    return out


ta, tb = table(a), table(b)
common = set(ta) & set(tb)
print("同 (骨,帧) 对: %d  仅在源: %d  仅在回: %d"
      % (len(common), len(set(ta) - set(tb)), len(set(tb) - set(ta))))
if common:
    worst = max(common, key=lambda k: max(abs(ta[k][j] - tb[k][j]) for j in range(7)))
    err = max(abs(ta[worst][j] - tb[worst][j]) for j in range(7))
    print("最大逐值误差 %.6f （骨 %s 帧 %d）" % (err, worst[0], worst[1]))
    import statistics
    errs = [max(abs(ta[k][j] - tb[k][j]) for j in range(7)) for k in common]
    print("误差中位 %.6f  p99 %.6f" % (statistics.median(errs), sorted(errs)[int(len(errs) * 0.99)]))
