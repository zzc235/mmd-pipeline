"""MMD Pipeline —— 一键把 PMX + VMD 渲成带物理的成片（供 agent 直接调用）。

结构照着成熟插件的分法（参考本机 mmd_tools）：
    properties.py  参数声明 → PropertyGroup（与 CLI 同源）
    operators.py   执行（子进程 + modal，UI 不卡、可取消）
    panels.py      UI
    mmdpipe/       纯逻辑库（不依赖 UI，可单测）

不重复实现任何东西：物理/材质/渲染/门禁都在 mmdpipe 里，
多段混合走 mmd_tools 官方 use_nla + Blender NLA 烘焙 + 官方 export_vmd。
"""

bl_info = {
    "name": "MMD Pipeline",
    "author": "furina",
    "version": (1, 2, 0),
    "blender": (4, 2, 0),
    "location": "3D 视图 > 侧栏 > MMD Pipeline",
    "description": "PMX + VMD 一键成片：物理资格判断、净空修复、多段拼接、门禁自检",
    "category": "Animation",
}

from . import operators, panels, properties


def register():
    properties.register()
    operators.register()
    panels.register()


def unregister():
    panels.unregister()
    operators.unregister()
    properties.unregister()


if __name__ == "__main__":
    register()
