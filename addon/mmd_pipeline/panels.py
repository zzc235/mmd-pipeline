"""四区面板：资产 / 物理 / 渲染 / 报告。

字段归属由 `mmdpipe.params.ZONE_OF` **唯一决定**（那里缺一项就 import 失败），
面板不再自己列字段——v1.2.0 就吃过"折叠后找不到旋钮"的亏。

报告区只读 `<out>/pipeline_state.json`（经 `status.py`），不 import 调度层、
不启动子进程；两个工具按钮（诊断 / 门禁）走 `run_tool.py` 子进程，点不动时
明确写"为什么不可用"，而不是点下去 Traceback。
"""
import os

import bpy

from .mmdpipe import params as params_mod
from . import status as status_mod

HERE = os.path.dirname(os.path.abspath(__file__))
ZONE_TITLE = {
    "asset": ("资产", "FILE_FOLDER"),
    "physics": ("物理", "PHYSICS"),
    "render": ("渲染", "RENDER_ANIMATION"),
}


def bundled(name: str) -> bool:
    """扩展包里有没有这个 CLI 模块（diagnose / physics_gate / gate_report）。"""
    return os.path.isfile(os.path.join(HERE, "mmdpipe", name + ".py"))


def _prop_rows(layout, settings, zone):
    primary = [p for p in params_mod.by_zone(zone) if not p.advanced]
    advanced = [p for p in params_mod.by_zone(zone) if p.advanced]
    for p in primary:
        layout.prop(settings, p.name)
    if advanced:
        box = layout.box()
        box.label(text="高级", icon="PREFERENCES")
        col = box.column(align=True)
        for p in advanced:
            col.prop(settings, p.name)


class MMDP_PT_main(bpy.types.Panel):
    bl_label = "MMD Pipeline"
    bl_idname = "MMDP_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MMD Pipeline"

    def draw(self, context):
        w = self.layout
        s = context.scene.mmdp

        for zone in ("asset", "physics", "render"):
            title, icon = ZONE_TITLE[zone]
            box = w.box()
            box.label(text=title, icon=icon)
            col = box.column(align=True)
            _prop_rows(col, s, zone)
            if zone == "physics":
                row = box.row(align=True)
                diag = row.row(align=True)
                diag.enabled = bundled("diagnose")
                diag.operator("mmd_pipeline.diagnose", icon="VIEWZOOM")
                gate = row.row(align=True)
                gate.enabled = bundled("physics_gate")
                gate.operator("mmd_pipeline.gate", icon="CHECKMARK")
                if not bundled("diagnose"):
                    box.label(text="诊断不可用：包内没有 diagnose 模块", icon="ERROR")
            if zone == "render":
                row = box.row(align=True)
                row.operator("mmd_pipeline.run", icon="RENDER_ANIMATION")
                row.operator("mmd_pipeline.open_dir", icon="FILE_FOLDER")

        box = w.box()
        box.label(text="报告", icon="TEXT")
        col = box.column(align=True)
        info = status_mod.summary(s.out) if s.out else {}
        for line in status_mod.report_lines(s.out, info or None):
            col.label(text=line)
        if info.get("log"):
            box.label(text="日志 %s" % info["log"])
        if info.get("state"):
            box.label(text="state %s" % info["state"])
        if info.get("final"):
            box.label(text="成片 %s" % info["final"])
        if not bundled("physics_gate"):
            box.label(text="门禁不可用：包内没有 physics_gate 模块", icon="ERROR")


CLASSES = (MMDP_PT_main,)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
