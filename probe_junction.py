"""量多对动作在交接处的「世界空间」根链差，找能验证注入的样本。"""
import sys
import bpy
import addon_utils
from mathutils import Vector

sys.path.insert(0, r"E:/dsh pr/woker2")
from mmdpipe import vmd as V

MODEL = r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309/星穹铁道—卡芙卡无外套/卡芙卡3.0.pmx"
M = r"E:/blender模型"
PAIRS = [
    ("原神摇+活着dj",
     M + "/原神摇_by_ChildeDuck_c658aa3daba96482861d466e1f1868c7/原神摇/原神摇.vmd",
     M + "/活着dj_by_lucky破_923ad74feee8ea23a61ed34b5798a78e/活着dj/活着dj_VMD-TDA.vmd"),
    ("爱乐之城+和刻晴睡觉",
     M + "/爱乐之城_LaLa Land_by_小豆芽的日常_adf026480b2d1b2f38a4e4faa785560f/爱乐之城_LaLa Land/爱乐之城.vmd",
     M + "/躺姿/和刻晴睡觉.vmd"),
    ("爱乐之城+和胡桃睡觉",
     M + "/爱乐之城_LaLa Land_by_小豆芽的日常_adf026480b2d1b2f38a4e4faa785560f/爱乐之城_LaLa Land/爱乐之城.vmd",
     M + "/躺姿/和胡桃睡觉.vmd"),
    ("原神摇+爱乐之城",
     M + "/原神摇_by_ChildeDuck_c658aa3daba96482861d466e1f1868c7/原神摇/原神摇.vmd",
     M + "/爱乐之城_LaLa Land_by_小豆芽的日常_adf026480b2d1b2f38a4e4faa785560f/爱乐之城_LaLa Land/爱乐之城.vmd"),
]
GAP = 6
WATCH = ["全ての親", "センター", "グルーブ", "下半身", "足首.R", "足首.L"]

addon_utils.enable("mmd_tools", default_set=True, persistent=True)


def fresh_model():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    before = set(o.name for o in bpy.data.objects)
    bpy.ops.mmd_tools.import_model(filepath=MODEL, scale=0.08,
                                   types={"MESH", "ARMATURE"}, clean_model=True,
                                   rename_bones=True, log_level="ERROR")
    new = [bpy.data.objects[n] for n in set(o.name for o in bpy.data.objects) - before]
    root = next(o for o in new if getattr(o, "mmd_type", None) == "ROOT")
    arm = bpy.data.objects[root.name + "_arm"]
    return root, arm


def snapshot(arm, f):
    bpy.context.scene.frame_set(f)
    out = {}
    for n in WATCH:
        pb = arm.pose.bones.get(n)
        if pb:
            m = arm.matrix_world @ pb.matrix
            out[n] = (m.translation.copy(), m.to_quaternion())
    return out


print("%-22s %-8s %-10s %-10s %-10s %-10s" % ("样本", "髋跳(mm)", "脚R跳(mm)", "脚L跳(mm)", "センターZ°", "判读"))
for label, a, b in PAIRS:
    try:
        ma, mb = V.load(a), V.load(b)
        tmp = "E:/dsh pr/woker2/out/_probe_%s.vmd" % abs(hash(label))
        rep = V.concat([ma, mb], tmp, gap=GAP)
        spans = [(s["dst_range"][0], s["dst_range"][1]) for s in rep["spans"]]
        a_end, b_start = spans[0][1], spans[1][0]

        root, arm = fresh_model()
        bpy.ops.object.select_all(action="DESELECT")
        root.select_set(True)
        bpy.context.view_layer.objects.active = root
        bpy.ops.mmd_tools.import_vmd(filepath=tmp, scale=0.08, bone_mapper="PMX",
                                     rename_bones=True, use_underscore=False,
                                     update_scene_settings=True)
        sa, sb = snapshot(arm, a_end), snapshot(arm, b_start)

        def d(n):
            if n in sa and n in sb:
                return (sb[n][0] - sa[n][0]).length * 1000
            return float("nan")

        caz = 0.0
        if "センター" in sa and "センター" in sb:
            r = sb["センター"][1] @ sa["センター"][1].inverted()
            import math
            caz = math.degrees(r.to_euler().z)

        hip, fr, fl = d("下半身"), d("足首.R"), d("足首.L")
        verdict = "根链无差→no-op" if (hip < 10 and abs(caz) < 4) else "有差→可验证注入"
        print("%-22s %-8.1f %-10.1f %-10.1f %-10.1f %s"
              % (label, hip, fr, fl, caz, verdict))
    except Exception as exc:
        print("%-22s 失败：%s" % (label, exc))
