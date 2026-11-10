"""参数 → Blender PropertyGroup，从 mmdpipe.params.PARAMS 生成。

面板和 CLI 共用一份声明（mmdpipe/params.py），结构上不可能再漂移。
"""
import bpy

from .mmdpipe import params as params_mod


def build_settings_class():
    props = params_mod.blender_properties(bpy)
    return type(
        "MMDPipelineSettings",
        (bpy.types.PropertyGroup,),
        {"__annotations__": props, "__doc__": "MMD 流水线参数（由 mmdpipe.params 生成）"},
    )


def register():
    cls = build_settings_class()
    bpy.utils.register_class(cls)
    bpy.types.Scene.mmdp = bpy.props.PointerProperty(
        type=cls, name="MMD Pipeline", description="MMD 流水线参数")
    return cls


def unregister():
    del bpy.types.Scene.mmdp
