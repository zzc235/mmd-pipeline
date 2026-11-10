"""面板：主参数直接平铺，逃生参数收进"高级"折叠区。

字段由 mmdpipe.params.PARAMS 的 advanced 标记决定，不在这里手写列表。
"""
import bpy

from .mmdpipe import params as params_mod

ADVANCED = tuple(p.name for p in params_mod.PARAMS if p.advanced)
PRIMARY = tuple(p.name for p in params_mod.PARAMS if not p.advanced)


class MMDP_PT_main(bpy.types.Panel):
    bl_label = "MMD Pipeline"
    bl_idname = "MMDP_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MMD Pipeline"

    def draw(self, context):
        w = self.layout
        s = context.scene.mmdp
        for name in PRIMARY:
            w.prop(s, name)
        w.separator()
        box = w.box()
        box.label(text="高级", icon="PREFERENCES")
        col = box.column(align=True)
        for name in ADVANCED:
            col.prop(s, name)
        w.separator()
        w.operator("mmd_pipeline.run", icon="RENDER_ANIMATION")


CLASSES = (MMDP_PT_main,)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
