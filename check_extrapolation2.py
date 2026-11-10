"""直接查 fcurve：找出只在一段里有关键帧的通道，看另一段是什么值。"""
import bpy
from collections import defaultdict

arm = max((o for o in bpy.data.objects if o.type == "ARMATURE"),
          key=lambda o: len(o.data.bones))
act = arm.animation_data.action
sc = bpy.context.scene

AFTER = 400.0      # 首键在 400 之后 → 只属于 B 段
BEFORE = 460.0     # 末键在 460 之前 → 只属于 A 段

b_only = defaultdict(list)
a_only = defaultdict(list)
normal = 0
for fc in act.fcurves:
    kfs = fc.keyframe_points
    if not len(kfs):
        continue
    lo = min(k.co[0] for k in kfs)
    hi = max(k.co[0] for k in kfs)
    bone = fc.data_path.split('"')[1] if '"' in fc.data_path else fc.data_path
    if lo > AFTER:
        b_only[bone].append((fc.data_path, fc.array_index, lo, hi, len(kfs)))
    elif hi < BEFORE:
        a_only[bone].append((fc.data_path, fc.array_index, lo, hi, len(kfs)))
    else:
        normal += 1

print("通道统计：常规 %d / 仅B段 %d 骨 / 仅A段 %d 骨" % (normal, len(b_only), len(a_only)))
print("\n仅 B 段的骨（前 5）：")
for b in list(b_only)[:5]:
    print("  %-16s %d 通道  首键 %.0f 末键 %.0f" % (b, len(b_only[b]),
                                              b_only[b][0][2], b_only[b][0][3]))

print("\n仅 A 段的骨（前 5）：")
for b in list(a_only)[:5]:
    print("  %-16s %d 通道  首键 %.0f 末键 %.0f" % (b, len(a_only[b]),
                                              a_only[b][0][2], a_only[b][0][3]))


def probe(bone, frames, label):
    pbs = arm.pose.bones.get(bone)
    if not pbs:
        print("  %s 不在骨架里" % bone)
        return
    vals = []
    for f in frames:
        sc.frame_set(f)
        vals.append((f, tuple(round(v, 4) for v in pbs.rotation_quaternion)))
    print("  %-16s %s" % (bone, "  ".join("f%d=%s" % v for v in vals)))


print("\n[仅B段骨 在 A 段的取值]  —— 若等于其首键值，说明是端点保持；若是 identity 则是 rest")
for b in list(b_only)[:3]:
    probe(b, (1, 100, 300, 445, 453), "B-only")
    for dp, ai, lo, hi, n in b_only[b][:1]:
        fc = next(f for f in act.fcurves if f.data_path == dp and f.array_index == ai)
        print("      首键值 %.4f @帧 %.0f" % (fc.keyframe_points[0].co[1],
                                            fc.keyframe_points[0].co[0]))

print("\n[仅A段骨 在 B 段的取值]  —— 若等于其末键值，说明是末值保持")
for b in list(a_only)[:3]:
    probe(b, (440, 453, 600, 800), "A-only")
    for dp, ai, lo, hi, n in a_only[b][:1]:
        fc = next(f for f in act.fcurves if f.data_path == dp and f.array_index == ai)
        print("      末键值 %.4f @帧 %.0f" % (fc.keyframe_points[-1].co[1],
                                            fc.keyframe_points[-1].co[0]))
