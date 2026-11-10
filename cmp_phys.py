"""对比两次管线跑出来的物理状态是否逐帧一致（只看刚体位置）。"""
import bpy

FILES = [
    ("A(非冻相机)", r"E:/dsh pr/woker2/repro360/scene.blend"),
    ("B(冻相机)", r"E:/dsh pr/woker2/repro_frozen/scene.blend"),
]
FRAMES = (1, 90, 144, 180, 240, 300, 360)
PROBE = ["003_下半身", "028_裙_0_0", "213_左長髮0", "053_袖_0_0"]

out = {}
for label, path in FILES:
    bpy.ops.wm.open_mainfile(filepath=path)
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 1, 360
    names = [n for n in PROBE if n in bpy.data.objects]
    if not names:
        rigids = [o for o in bpy.data.objects if getattr(o, "mmd_type", None) == "RIGID_BODY"]
        names = [o.name for o in rigids[:4]]
    acc = {}
    for f in range(1, 361):
        sc.frame_set(f)
        if f in FRAMES:
            acc[f] = {n: tuple(round(v, 6) for v in bpy.data.objects[n].matrix_world.translation)
                      for n in names}
    out[label] = acc
    print("DONE", label, names)

a, b = list(out.values())
keys = list(out.keys())
print("对比：%s  vs  %s" % (keys[0], keys[1]))
worst = 0.0
for f in FRAMES:
    for n in a[f]:
        pa, pb = a[f][n], b[f][n]
        d = max(abs(pa[i] - pb[i]) for i in range(3))
        worst = max(worst, d)
        if d > 1e-9:
            print("  f%-3d %-14s 差 %.9f   %s vs %s" % (f, n, d, pa, pb))
print("最大差值 %.9f m" % worst)
print("结论：%s" % ("两次跑完全一致（确定性成立）" if worst < 1e-9 else "存在差异"))
