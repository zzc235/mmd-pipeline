"""实测：交接处真正的世界位移，以及它由哪根根骨贡献。"""
import bpy
from mathutils import Vector

sc = bpy.context.scene
arm = max((o for o in bpy.data.objects if o.type == "ARMATURE"),
          key=lambda o: len(o.data.bones))
WATCH = ["下半身", "センター", "グルーブ", "全ての親", "操作中心", "腰", "足D.R", "足首.R"]
A_END, B_START = 446, 453

def snap(f):
    sc.frame_set(f)
    return {n: (arm.matrix_world @ arm.pose.bones[n].matrix).translation.copy()
            for n in WATCH if n in arm.pose.bones}

a = snap(A_END)
b = snap(B_START)

print("=== 世界位置（f%d → f%d）===" % (A_END, B_START))
for n in WATCH:
    if n not in a:
        continue
    d = (b[n] - a[n]).length
    print("  %-8s A %s  B %s  世界差 %7.1f mm"
          % (n, tuple(round(v, 4) for v in a[n]), tuple(round(v, 4) for v in b[n]), d * 1000))

# 髋部是可见位移的代表
if "下半身" in a:
    hip_jump = (b["下半身"] - a["下半身"]).length
    print("\n髋部跳变量（真实观感位移）= %.1f mm" % (hip_jump * 1000))

# 拆分：逐根看 全ての親 / 操作中心 / グルーブ 的**局部**位置键
print("\n=== 根链骨的局部位置键 ===")
for name in ("全ての親", "操作中心", "グルーブ", "センター"):
    pb = arm.pose.bones.get(name)
    if not pb:
        continue
    sc.frame_set(A_END)
    la = pb.location.copy()
    sc.frame_set(B_START)
    lb = pb.location.copy()
    print("  %-8s A末 local %s   B首 local %s   差 %.1f mm"
          % (name, tuple(round(v, 4) for v in la), tuple(round(v, 4) for v in lb),
             (lb - la).length * 1000))

# 朝向：竖直轴（Y）上的朝向差
print("\n=== 竖直轴朝向差 ===")
for name in ("下半身", "センター", "グルーブ", "全ての親"):
    pb = arm.pose.bones.get(name)
    if not pb:
        continue
    sc.frame_set(A_END)
    aq = (arm.matrix_world @ pb.matrix).to_quaternion()
    sc.frame_set(B_START)
    bq = (arm.matrix_world @ pb.matrix).to_quaternion()
    r = bq @ aq.inverted()
    e = r.to_euler()
    print("  %-8s 相对旋转 X %.1f° Y %.1f° Z %.1f°"
          % (name, *[__import__("math").degrees(v) for v in e]))

# B 段自身是否带走位：B 段内部髋部活动范围
print("\n=== B 段内部髋部活动范围 ===")
if "下半身" in b:
    pts = []
    for f in range(B_START, 834, 20):
        sc.frame_set(f)
        pts.append((arm.matrix_world @ arm.pose.bones["下半身"].matrix).translation.copy())
    span = (Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))),
            Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))))
    size = span[1] - span[0]
    print("  B 段髋部移动范围 %s  m" % (tuple(round(v, 3) for v in size),))
