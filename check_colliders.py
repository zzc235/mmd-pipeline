"""检查 mode0 无关节刚体到底有没有掉下去。"""
import bpy

sc = bpy.context.scene
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
rigids = [o for o in bpy.data.objects if getattr(o, "mmd_type", None) == "RIGID_BODY"]
names = ["下半身", "上半身", "首", "右腕", "左腕", "右ひじ"]
targets = []
for n in names:
    hit = next((o for o in rigids if n in o.name and o.name.startswith(("003", "001", "000", "011", "020"))), None)
    if hit is None:
        hit = next((o for o in rigids if n in o.name), None)
    if hit:
        targets.append(hit)

print("检查 %d 个刚体" % len(targets))
for o in targets:
    print("  %-16s mode=%s bone=%s" %
          (o.name, getattr(o.mmd_rigid, "mode", "?"), getattr(o.mmd_rigid, "bone", "?")))

rows = {}
for f in (1, 2, 3, 30, 60):
    sc.frame_set(f)
    for o in targets:
        rows.setdefault((o.name, f), tuple(round(v, 4) for v in o.matrix_world.translation))

for o in targets:
    a = rows[(o.name, 1)]
    b = rows[(o.name, 60)]
    drift = max(abs(a[i] - b[i]) for i in range(3))
    print("%-16s f1=%s f60=%s 漂移=%.4f" % (o.name, a, b, drift))

# 骨骼参考
pb = arm.pose.bones.get("下半身")
if pb:
    for f in (1, 60):
        sc.frame_set(f)
        w = arm.matrix_world @ pb.head
        print("bone 下半身 f%d head=%s" % (f, tuple(round(v, 4) for v in w)))
