"""M02 · 读一批 .blend 的 rigidbody point_cache 状态（只读打开，绝不保存）。

    blender -b -P m02_cache_state.py -- out.json blend1 [blend2 ...]

用途：S8 正控 C 暴露出 `E_base.blend` 的 `point_cache.is_baked = True` —— 逐帧 `frame_set()`
可能只是在回放烘焙缓存。这个脚本把仓库里所有被测量过的 .blend 的缓存状态一次列清，
用来圈定「哪些已交付的数字可能是缓存回放」。
"""
import json
import os
import sys

import bpy


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) < 2:
        raise SystemExit("usage: m02_cache_state.py -- out.json blend [...]")
    out_path, blends = argv[0], argv[1:]
    out = {}
    for path in blends:
        rec = {"exists": os.path.exists(path)}
        if not rec["exists"]:
            out[path] = rec
            continue
        bpy.ops.wm.open_mainfile(filepath=path)
        sc = bpy.context.scene
        rbw = sc.rigidbody_world
        rec["scene_frames"] = [sc.frame_start, sc.frame_end]
        rec["rigid_bodies"] = len([o for o in bpy.data.objects
                                   if getattr(o, "rigid_body", None) is not None])
        rec["constraints"] = len([o for o in bpy.data.objects
                                  if getattr(o, "rigid_body_constraint", None) is not None])
        if rbw:
            pc = rbw.point_cache
            rec["point_cache"] = {"is_baked": bool(pc.is_baked), "info": str(pc.info),
                                  "frame_start": pc.frame_start, "frame_end": pc.frame_end,
                                  "use_disk_cache": bool(pc.use_disk_cache)}
            rec["substeps"] = rbw.substeps_per_frame
            rec["iterations"] = rbw.solver_iterations
            rec["gravity"] = round(rbw.effector_weights.gravity, 6)
        else:
            rec["point_cache"] = None
        out[path] = rec

    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    for p, r in out.items():
        pc = r.get("point_cache") or {}
        print("CACHE %-60s baked=%s frames=%s" % (os.path.basename(p), pc.get("is_baked"),
                                                  (pc.get("frame_start"), pc.get("frame_end"))))
    sys.stdout.flush()
    os._exit(0)


main()
