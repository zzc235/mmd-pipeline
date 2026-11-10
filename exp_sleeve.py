"""袖子翻折对照实验：只改物理配置，量袖刚体逐帧转角突变。

用法：blender -b <scene.blend> -P exp_sleeve.py -- <mode>
  base    substeps 10 / iterations 20（现状）
  hi      substeps 20 / iterations 60（验证 1）
  nocoll  现状 + 袖刚体脱离组碰撞（验证 2）
"""
import sys
import math
import bpy

sys.path.insert(0, r"E:/dsh pr/woker2")
from mmdpipe import pmx as P, physics

MODE = (sys.argv[sys.argv.index("--") + 1:] or ["base"])[0]
PMX = r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309/星穹铁道—卡芙卡无外套/卡芙卡3.0.pmx"
FRAMES = 120

m = P.load(PMX)
rep = physics.classify(m)
units = [u for u in rep.units if len(u.bodies) == 25 and u.cycle_rank >= 20]
ids = sorted({b for u in units for b in u.bodies})
names = [m.rigids[i].name for i in ids]
print("MODE %s | 袖单元 %d 个 / 刚体 %d 个" % (MODE, len(units), len(ids)))
print("  示例刚体:", names[:5])

sc = bpy.context.scene
rbw = sc.rigidbody_world
rbw.substeps_per_frame = 10
rbw.solver_iterations = 20
if MODE in ("hi", "hi_damp"):
    rbw.substeps_per_frame = 20
    rbw.solver_iterations = 60
print("  物理: substeps=%d iterations=%d" % (rbw.substeps_per_frame, rbw.solver_iterations))

# mmd_tools 把刚体对象命名为 "<索引>_<刚体名>"，按索引前缀匹配最稳
objs = [o for o in bpy.data.objects if getattr(o, "mmd_type", None) == "RIGID_BODY"]
print("  场景刚体对象 %d 个，示例 %s" % (len(objs), [o.name for o in objs[:3]]))
by_prefix = {}
for o in objs:
    head = o.name.split("_", 1)[0]
    if head.isdigit():
        by_prefix[int(head)] = o
targets = [by_prefix[i] for i in ids if i in by_prefix]
print("  场景内找到袖刚体 %d 个" % len(targets))

if MODE in ("damp", "hi_damp"):
    for o in targets:
        rb = o.rigid_body
        if rb:
            rb.angular_damping = 0.75
            rb.linear_damping = 0.25
    print("  袖刚体已加阻尼（angular 0.75 / linear 0.25）")

if MODE == "nocoll":
    for o in targets:
        rb = o.rigid_body
        if rb:
            rb.collision_collections = [i == 19 for i in range(20)]
    print("  袖刚体已隔离到 20 号碰撞组")

# 重新烘焙 1..FRAMES
sc.frame_start, sc.frame_end = 1, FRAMES
bpy.ops.ptcache.free_bake_all()
sc.frame_set(1)
bpy.ops.ptcache.bake_all(bake=True)

# 采样
prev = {}
max_step = []
for f in range(1, FRAMES + 1):
    sc.frame_set(f)
    step = 0.0
    worst = None
    for o in targets:
        q = o.matrix_world.to_quaternion()
        p = prev.get(o.name)
        if p is not None:
            d = min((q - p).magnitude, (q + p).magnitude)
            ang = math.degrees(4 * math.asin(min(1.0, d / 2)))
            if ang > step:
                step, worst = ang, o.name
        prev[o.name] = q
    max_step.append((f, step, worst))

top = sorted(max_step, key=lambda x: -x[1])[:6]
print("  袖刚体逐帧最大转角突变（度）:")
for f, s, w in top:
    print("    f%-4d %6.1f°  %s" % (f, s, w))
flips = [t for t in max_step if t[1] > 45]
print("  >45°/帧 的帧数: %d   |  >90°/帧: %d" % (len(flips), len([t for t in max_step if t[1] > 90])))
print("  前 8 个突变帧:", [t[0] for t in sorted(flips, key=lambda x: -x[1])[:8]])
