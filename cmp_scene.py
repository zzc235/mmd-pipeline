"""对比旧工程与新工程的相机 + 刚体位置。"""
import bpy

OLD = r"E:/code/Blender/feiying_short/04_anim/feiying_combined.blend"
NEW = r"E:/dsh pr/woker2/repro360/scene.blend"

PROBE_RIGIDS = ["003_下半身", "028_裙_0_0", "213_左長髮0", "000_上半身"]


def snapshot(path, label):
    bpy.ops.wm.open_mainfile(filepath=path)
    sc = bpy.context.scene
    print("=== %s ===" % label)
    print("  file", path)
    cam = sc.camera
    if cam:
        print("  camera %s loc=%s rot=%s lens=%.2f"
              % (cam.name,
                 tuple(round(v, 4) for v in cam.location),
                 tuple(round(v, 4) for v in cam.rotation_euler),
                 cam.data.lens))
    else:
        print("  camera None")
    print("  frame_current", sc.frame_current, "start", sc.frame_start, "end", sc.frame_end,
          "fps", sc.render.fps)
    print("  res", sc.render.resolution_x, sc.render.resolution_y,
          "taa", getattr(sc.eevee, "taa_render_samples", None))
    rbw = sc.rigidbody_world
    if rbw:
        print("  rbw enabled=%s substeps=%s iters=%s cache=%d..%d baked=%s"
              % (rbw.enabled, rbw.substeps_per_frame, rbw.solver_iterations,
                 rbw.point_cache.frame_start, rbw.point_cache.frame_end,
                 rbw.point_cache.is_baked))
    sc.frame_set(1)
    for name in PROBE_RIGIDS:
        o = bpy.data.objects.get(name)
        if o:
            print("  rb %-12s %s" % (name, tuple(round(v, 5) for v in o.matrix_world.translation)))
        else:
            print("  rb %-12s 缺失" % name)
    mesh = bpy.data.objects.get(sc.objects[0].name) if False else None
    # 统计网格与骨骼
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    print("  meshes", [(o.name, len(o.data.vertices)) for o in meshes[:2]])
    print("  armatures", [(o.name, len(o.data.bones)) for o in arms[:2]])
    if arms:
        arm = arms[0]
        act = arm.animation_data.action if arm.animation_data else None
        print("  action", act.name if act else None,
              "fcurves", len(act.fcurves) if act else 0)
    print()


snapshot(OLD, "OLD (原工程)")
snapshot(NEW, "NEW (复现)")
