"""M02 · P11：验证「解烘焙后保存」这条交付路是否真的救得回来。

    blender -b -P m02_s8_p11.py -- make  <src.blend> <dst.blend> <out.json>
    blender -b -P m02_s8_p11.py -- probe <dst.blend> <frame> <out.json>

`make` ：只读打开 src → `ptcache.free_bake_all()` → **另存到 dst**（这次必须存盘，与之前「从不保存」不同）
          → 记录 src 的 sha256 前后值（必须相同）与 dst 的缓存状态。
`probe`：**新进程**打开 dst → 记录打开时的缓存状态 → `frame_set(frame)` → 落 324 刚体世界坐标。

判定（离线）：probe 的坐标等于 `P0`（重算） ⇒ 不烘焙交付可行；等于 `A1`（回放） ⇒ 不可行。
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


def cache_state(rbw):
    if rbw is None:
        return None
    pc = rbw.point_cache
    return {"is_baked": bool(pc.is_baked), "is_outdated": bool(pc.is_outdated),
            "info": str(pc.info), "frame_start": pc.frame_start, "frame_end": pc.frame_end}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) < 4:
        raise SystemExit("usage: m02_s8_p11.py -- <make|probe> <in.blend> <arg> <out.json>")
    mode, src, arg, out_path = argv[0], argv[1], argv[2], argv[3]

    if mode == "make":
        dst = arg
        if os.path.abspath(src) == os.path.abspath(dst):
            raise SystemExit("拒绝覆盖入参工程")
        sha_src_before = sha256_file(src)
        bpy.ops.wm.open_mainfile(filepath=src)
        rbw = bpy.context.scene.rigidbody_world
        before = cache_state(rbw)
        bpy.ops.ptcache.free_bake_all()
        after_free = cache_state(rbw)
        bpy.ops.wm.save_as_mainfile(filepath=dst)
        out = {"mode": "make", "src": src, "dst": dst,
               "src_sha256_before": sha_src_before,
               "src_sha256_after": sha256_file(src),
               "src_untouched": sha_src_before == sha256_file(src),
               "dst_sha256": sha256_file(dst),
               "cache_before_free": before, "cache_after_free": after_free,
               "api": "bpy.ops.ptcache.free_bake_all()"}
        print("P11 make src_untouched=%s dst=%s baked_after_free=%s"
              % (out["src_untouched"], dst, after_free["is_baked"] if after_free else None))

    elif mode == "probe":
        frame = int(arg)
        sha_before = sha256_file(src)
        bpy.ops.wm.open_mainfile(filepath=src)
        sc = bpy.context.scene
        rbw = sc.rigidbody_world
        at_open = cache_state(rbw)
        rigids = sorted([o for o in bpy.data.objects
                         if getattr(o, "rigid_body", None) is not None], key=lambda o: o.name)
        sc.frame_set(frame)
        after = cache_state(rbw)
        out = {"mode": "probe", "blend": src, "frame": frame,
               "blend_sha256_before": sha_before,
               "blend_sha256_after": sha256_file(src),
               "source_untouched": sha_before == sha256_file(src),
               "cache_at_open": at_open, "cache_after_step": after,
               "never_saved_blend": True, "bodies": len(rigids),
               "pos": {o.name: [round(v, 6) for v in o.matrix_world.translation]
                       for o in rigids}}
        print("P11 probe frame=%d bodies=%d baked_at_open=%s outdated=%s"
              % (frame, len(rigids), at_open["is_baked"] if at_open else None,
                 at_open["is_outdated"] if at_open else None))
    else:
        raise SystemExit("unknown mode: %s" % mode)

    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    sys.stdout.flush()
    os._exit(0)


main()
