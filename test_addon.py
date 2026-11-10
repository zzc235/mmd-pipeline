"""验证插件：启用扩展 → 通过 bpy.ops 跑一次完整流水线。"""
import bpy
import addon_utils

ok = addon_utils.enable("mmd_pipeline", default_set=True, persistent=True)
print("ENABLE ->", ok)
print("operator 存在:", hasattr(bpy.ops.mmd_pipeline, "render"))
print("面板注册:", hasattr(bpy.types, "MMD_PT_panel"))
print("场景属性:", hasattr(bpy.types.Scene, "mmdp_pmx") or
      "mmdp_pmx" in bpy.types.Scene.bl_rna.properties)

B = r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309"
res = bpy.ops.mmd_pipeline.render(
    pmx=B + "/星穹铁道—卡芙卡无外套/卡芙卡3.0.pmx",
    vmd="",
    motions=r"E:/blender模型/原神摇_by_ChildeDuck_c658aa3daba96482861d466e1f1868c7/原神摇/原神摇.vmd;E:/blender模型/活着dj_by_lucky破_923ad74feee8ea23a61ed34b5798a78e/活着dj/活着dj_VMD-TDA.vmd",
    out_dir=r"E:/dsh pr/woker2/addon_test_nla",
    frames=12,
    fps="30",
    physics_policy="strict",
    chain_mode="nla",
    chain_gap=20,
    chain_blend=20,
    clearance=False,
    camera_json=r"E:/dsh pr/woker2/presets/kafuka_v2_camera.json",
)
print("OPERATOR_RESULT", res)
