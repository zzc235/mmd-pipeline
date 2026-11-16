"""M02 · P7：未修改地加载工程，直接 `frame_set(109)`，看默认消费路径吃的是哪条轨迹。

    blender -b -P m02_s8_p7.py -- <in.blend> <frame> <out.json>

只读：不解烘焙、不改任何属性、不存盘。输出该帧全部刚体的世界坐标 + 打开时的缓存状态。
"""
import hashlib
import json
import os
import sys

import bpy


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) < 3:
        raise SystemExit("usage: m02_s8_p7.py -- in.blend frame out.json")
    src, frame, out_path = argv[0], int(argv[1]), argv[2]

    src_sha_before = sha256_file(src)
    bpy.ops.wm.open_mainfile(filepath=src)
    sc = bpy.context.scene
    rbw = sc.rigidbody_world
    pc = rbw.point_cache
    cache = {"is_baked": bool(pc.is_baked), "info": str(pc.info),
             "is_outdated": bool(pc.is_outdated),
             "frame_start": pc.frame_start, "frame_end": pc.frame_end}

    rigids = [o for o in bpy.data.objects if getattr(o, "rigid_body", None) is not None]
    rigids.sort(key=lambda o: o.name)

    # 单次跳帧：不先走 1..frame-1，模拟"别人打开工程直接跳到这一帧"
    sc.frame_set(frame)
    pos = {o.name: [round(v, 6) for v in o.matrix_world.translation] for o in rigids}
    cache_after = {"is_baked": bool(pc.is_baked), "info": str(pc.info),
                   "is_outdated": bool(pc.is_outdated)}

    out = {"stage": "P7", "in_blend": src, "frame": frame,
           "in_blend_sha256_before": src_sha_before,
           "in_blend_sha256_after": sha256_file(src),
           "source_untouched": src_sha_before == sha256_file(src),
           "point_cache_at_open": cache, "point_cache_after_jump": cache_after,
           "never_saved_blend": True, "bodies": len(rigids), "pos": pos}
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("P7 frame=%d bodies=%d baked=%s outdated=%s out=%s"
          % (frame, len(rigids), cache["is_baked"], cache["is_outdated"], out_path))
    sys.stdout.flush()
    os._exit(0)


main()
