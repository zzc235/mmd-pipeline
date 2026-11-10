"""在两个工程里各跑一遍全片包围盒，看物理轨迹是否在某一帧开始分叉。"""
import bpy
from mathutils import Vector

OLD = r"E:/code/Blender/feiying_short/04_anim/feiying_combined.blend"
NEW = r"E:/dsh pr/woker2/repro360/scene.blend"
PROBE = ["003_下半身", "028_裙_0_0", "213_左長髮0", "203_左耳3"]


def walk(path, label):
    bpy.ops.wm.open_mainfile(filepath=path)
    sc = bpy.context.scene
    rigids = [o for o in bpy.data.objects if getattr(o, "mmd_type", None) == "RIGID_BODY"]
    print("=== %s === rigids=%d current_frame=%d cache=%d..%d"
          % (label, len(rigids), sc.frame_current,
             sc.rigidbody_world.point_cache.frame_start,
             sc.rigidbody_world.point_cache.frame_end))
    sc.frame_start, sc.frame_end = 1, 360
    pts = []
    marks = {}
    for f in range(1, 361):
        sc.frame_set(f)
        if f % 20 == 0 or f == 360:
            for o in rigids:
                pts.append(o.matrix_world.translation.copy())
        if f in (1, 120, 240, 360):
            marks[f] = {n: tuple(round(v, 5) for v in bpy.data.objects[n].matrix_world.translation)
                        for n in PROBE if n in bpy.data.objects}
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    c = (mn + mx) / 2
    sz = mx - mn
    print("  BBOX size=%s center=%s" % (tuple(round(v, 3) for v in sz), tuple(round(v, 3) for v in c)))
    for f in sorted(marks):
        print("  f%-3d %s" % (f, marks[f]))
    print()


walk(OLD, "OLD")
walk(NEW, "NEW")
