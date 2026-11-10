"""验证道具是否一直跟着手（跨帧测距离）。带 flush，便于定位。"""
import sys
import bpy

sc = bpy.context.scene
arm = max((o for o in bpy.data.objects if o.type == "ARMATURE"),
          key=lambda o: len(o.data.bones))
prop = next(o for o in bpy.data.objects if getattr(o, "mmd_type", None) == "ROOT")
prop_arm = bpy.data.objects.get(prop.name + "_arm")
mesh = bpy.data.objects.get(prop.name + "_mesh")
bone = prop.parent_bone
print("道具 %s 父级骨 %s 类型 %s arm=%s mesh=%s"
      % (prop.name, bone, prop.parent_type,
         prop_arm.name if prop_arm else None, mesh.name if mesh else None), flush=True)

pb = arm.pose.bones[bone]
prop_bone = prop_arm.pose.bones[0]
sc.frame_start, sc.frame_end = 1, 360
print("范围 %d..%d" % (sc.frame_start, sc.frame_end), flush=True)

for f in (1, 60, 200, 360):
    try:
        sc.frame_set(f)
        hand = arm.matrix_world @ pb.head
        pw = prop_arm.matrix_world @ prop_bone.head
        print("f%-3d 手 %s 道具骨 %s 距离 %.4f m"
              % (f, tuple(round(v, 3) for v in hand),
                 tuple(round(v, 3) for v in pw), (pw - hand).length), flush=True)
    except Exception as exc:
        print("f%d 失败 %s" % (f, exc), flush=True)
        raise
print("DONE", flush=True)
