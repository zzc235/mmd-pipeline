"""MMD 流水线内核（mmdpipe）。

只做一件事：把「PMX + VMD → 成片」稳定复现，并在能失败的地方设断言。
模块清单与三条边界见下方 MODULE MAP。
安全约定：源文件只读，改动落在副本，有哈希守卫。
"""

__version__ = "1.3.0"

# ============================================================ MODULE MAP
# 读代码先看这张图。分三圈：纯 Python → Blender 内 → 打包。
#
# 【纯 Python｜无 bpy，可单测】
#   pmx.py         PMX 解析 + 按字节偏移回写（不重新序列化）
#   vmd.py         VMD 解析（骨骼/表情/相机/灯光/阴影/IK 全轨道）+ concat/merge
#   match.py       VMD × PMX 覆盖率体检
#   physics.py     物理资格分类（结构判定，不看名字）
#   clearance.py   初始穿透检测与修复
#   report.py      StageResult / Issue 契约
#   preset.py      预设与默认值
#   archive plan 等纯逻辑
#   chainplan.py   拼接 dry-run（**算不出世界位移**，只给局部量与姿态差）
#   align.py       对齐 plan 结构 + 判定 + 注入（纯算术，测量在 Blender 侧）
#   layout.py      产物布局：work/（中间物）与 final/（成片，通过才落地）
#   statefile.py   pipeline_state 的兼容判定与迁移（读不懂就拒绝，不猜）
#   concatvmd.py / mergevmd.py  两个命令行入口
#
# 【Blender 内｜需要 bpy】
#   stage.py       各阶段：导入/建链/物理策略/动作/材质/道具/相机/渲染/验收
#   runner.py      编排：S0..S8，命令行入口
#   chain_nla.py   NLA 路线拼接：分层 → 测量对齐 → 淡化 → 烘焙 → 导出
#   measure_align.py  独立的世界空间对齐测量脚本
#
# 【打包】
#   build_addon.py  把 mmdpipe + presets 打进 Blender 扩展
#
# 三条必须记住的边界：
#   1. 世界位移只能在 Blender 里测（chainplan 没有骨架求值）
#   2. mmd_tools 的 import_vmd 以 scene.frame_current 为起点，导入前必须复位
#   3. 判"出框"只能看渲染像素，骨点和网格包围盒都会误报
# =============================================================
