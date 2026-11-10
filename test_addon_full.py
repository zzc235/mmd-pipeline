"""用插件本体渲完整成片：物理 + 净空 + 道具 + NLA 拼接。"""
import bpy
import addon_utils

addon_utils.enable("mmd_pipeline", default_set=True, persistent=True)

B = r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309"
M = r"E:/blender模型"

res = bpy.ops.mmd_pipeline.render(
    pmx=B + "/星穹铁道—卡芙卡无外套/卡芙卡3.0.pmx",
    vmd="",
    motions=";".join([
        M + "/原神摇_by_ChildeDuck_c658aa3daba96482861d466e1f1868c7/原神摇/原神摇.vmd",
        M + "/活着dj_by_lucky破_923ad74feee8ea23a61ed34b5798a78e/活着dj/活着dj_VMD-TDA.vmd",
    ]),
    out_dir=r"E:/dsh pr/woker2/addon_full",
    frames=833,
    fps="30",
    physics_policy="strict",
    chain_mode="nla",
    chain_gap=6,
    chain_blend=6,
    clearance=True,
    camera_json=r"E:/dsh pr/woker2/presets/kafuka_v2_camera.json",
)
print("OPERATOR_RESULT", res)
