import bpy, json, sys
for path in sys.argv[sys.argv.index("--")+1:]:
    bpy.ops.wm.open_mainfile(filepath=path)
    sc = bpy.context.scene
    c = sc.camera
    print("VER %-28s cam=%s loc=%s rot=%s lens=%.1f res=%dx%d taa=%s frames=%d..%d fps=%d" % (
        path.split("kafuka_combined")[-1].replace(".blend","") or "v1",
        c.name if c else None,
        [round(v,5) for v in c.location] if c else None,
        [round(v,6) for v in c.rotation_euler] if c else None,
        c.data.lens if c else 0,
        sc.render.resolution_x, sc.render.resolution_y,
        getattr(sc.eevee,"taa_render_samples",None),
        sc.frame_start, sc.frame_end, sc.render.fps))
