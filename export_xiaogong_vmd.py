"""把 .blend 里的动作用官方 export_vmd 导出成 VMD。"""
import bpy
import addon_utils

OUT = r"E:/dsh pr/woker2/out/xiaogong_dance.vmd"

addon_utils.enable("mmd_tools", default_set=True, persistent=True)

arm = bpy.data.objects.get("宵宫_arm")
assert arm is not None, "找不到骨架"
act = arm.animation_data.action if arm.animation_data else None
print("骨架 %s  action=%s range=%s" % (arm.name, act.name if act else None,
                                       tuple(act.frame_range) if act else None))

bpy.ops.object.select_all(action="DESELECT")
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.mmd_tools.export_vmd(filepath=OUT, scale=12.5, use_frame_range=True)
print("EXPORTED", OUT)
