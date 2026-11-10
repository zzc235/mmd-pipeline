"""在独立进程里测量全片包围盒。

用法：
    blender -b scene.blend -P measure_cam.py -- --frames 360
"""
import sys

import bpy
from mathutils import Vector


def arg(name, default=None):
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


N = int(arg("--frames", "360"))
sc = bpy.context.scene
rbw = sc.rigidbody_world
rigids = [o for o in bpy.data.objects if getattr(o, "mmd_type", None) == "RIGID_BODY"]

print("LOADED", bpy.data.filepath)
print("  frame_current=%d start=%d end=%d" % (sc.frame_current, sc.frame_start, sc.frame_end))
print("  cache=%d..%d baked=%s" % (rbw.point_cache.frame_start, rbw.point_cache.frame_end,
                                   rbw.point_cache.is_baked))
print("  rigids=%d" % len(rigids))

sc.frame_start, sc.frame_end = 1, N
sc.frame_set(1)

pts = []
for f in range(1, N + 1):
    sc.frame_set(f)
    if f % 20 == 0 or f == N:
        for o in rigids:
            pts.append(o.matrix_world.translation.copy())

mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
c = (mn + mx) / 2
sz = mx - mn
print("BBOX size=%s center=%s" % (tuple(round(v, 4) for v in sz), tuple(round(v, 4) for v in c)))

TAN_H = (36.0 / 2.0) / 50.0
TAN_V = ((36.0 / (720.0 / 576.0)) / 2.0) / 50.0
dist = max(sz.x / 2 * 1.25 / TAN_H, sz.z / 2 * 1.25 / TAN_V, sz.y / 2 + 1.0)
print("CAM dist=%.4f loc=%s" % (dist, tuple(round(c[i] + dist * d, 4) for i, d in
                                            enumerate((0.42, -0.88, 0.22)))))
