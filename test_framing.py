"""在已渲完的场景上单独跑取景检查，看能否复现"构图漂移"。"""
import sys
sys.path.insert(0, r"E:/dsh pr/woker2")
import bpy
from mmdpipe import stage

cam = bpy.context.scene.camera
print("相机:", cam.name if cam else None,
      "lens", cam.data.lens if cam else None,
      "loc", tuple(round(v, 3) for v in cam.location) if cam else None)
scene = bpy.context.scene
print("帧范围", scene.frame_start, scene.frame_end)

m, issues = stage.check_framing(cam, range(scene.frame_start, scene.frame_end + 1, 10))
print("METRICS", m)
for code, level, msg, detail in issues:
    print("ISSUE", code, level, msg, "|", detail)
