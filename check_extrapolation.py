"""验证：拼接后，某骨在某段没有关键帧时，Blender 里到底是什么值。"""
import bpy
from mathutils import Quaternion

sc = bpy.context.scene
arm = max((o for o in bpy.data.objects if o.type == "ARMATURE"),
          key=lambda o: len(o.data.bones))
act = arm.animation_data.action
print("ACTION %s 范围 %s" % (act.name, tuple(act.frame_range)))

# A 独有骨（原神摇有、活着dj没有）与 B 独有骨
A_ONLY = ["上半身3", "右足D", "右ひざD", "右足首D"]
B_ONLY = ["HairA1_JNT", "HairA2_JNT", "_dummy_右目"]

def show(bone, frames):
    pb = arm.pose.bones.get(bone)
    if not pb:
        print("  %-14s 不存在" % bone)
        return
    row = []
    for f in frames:
        sc.frame_set(f)
        q = pb.rotation_quaternion
        row.append("f%d=%s" % (f, tuple(round(v, 3) for v in q)))
    print("  %-14s %s" % (bone, "  ".join(row)))

print("\n[A 独有骨：B 段(453+)没有它们的键，看是否冻结]")
for b in A_ONLY:
    show(b, (1, 300, 446, 600, 832))

print("\n[B 独有骨：A 段(0..446)没有它们的键，看到底是 rest 还是 B 首帧值]")
for b in B_ONLY:
    show(b, (1, 100, 300, 446, 453, 500))

# 对照：取 B 独有骨在 453 处的值，与 100 处比较
print("\n[对照：B 独有骨 f100 与 f453 是否相同 = 是否端点保持]")
for b in B_ONLY:
    pb = arm.pose.bones.get(b)
    if not pb:
        continue
    sc.frame_set(100)
    q100 = tuple(round(v, 6) for v in pb.rotation_quaternion)
    sc.frame_set(453)
    q453 = tuple(round(v, 6) for v in pb.rotation_quaternion)
    print("  %-14s 相同=%s  %s / %s" % (b, q100 == q453, q100, q453))
