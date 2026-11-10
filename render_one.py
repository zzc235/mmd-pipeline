"""只渲染一帧（含从第 1 帧预热），用于测复现下限。

    blender -b scene.blend -P render_one.py -- --frame 180 --out x.png
"""
import sys

import bpy


def arg(name, default=None):
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


frame = int(arg("--frame", "180"))
out = arg("--out", "frame.png")
cam_loc = arg("--cam-loc")
cam_rot = arg("--cam-rot")

sc = bpy.context.scene
if cam_loc and cam_rot:
    cam = sc.camera
    cam.location = tuple(float(v) for v in cam_loc.split(","))
    cam.rotation_euler = tuple(float(v) for v in cam_rot.split(","))
    print("CAM_OVERRIDE", tuple(round(v, 4) for v in cam.location),
          tuple(round(v, 4) for v in cam.rotation_euler))
sc.frame_start, sc.frame_end = 1, frame
sc.render.resolution_x, sc.render.resolution_y = 720, 576
sc.render.resolution_percentage = 100
sc.render.image_settings.file_format = "PNG"
sc.eevee.taa_render_samples = 10

for f in range(1, frame + 1):
    sc.frame_set(f)

sc.render.filepath = out
bpy.ops.render.render(write_still=True)
print("RENDERED", out)
