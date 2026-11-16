"""M02 · P12：解烘焙 → 顺序步进 1..240 → 存盘 → 新进程冷跳 f109，是否等于 P0[109]。

    blender -b -P m02_s8_p12.py -- make  <src.blend> <dst.blend> <out.json>
    blender -b -P m02_s8_p12.py -- probe <dst.blend> <frame> <out.json>

`make` ：只读打开 src（由外部先拷成副本，绝不打开交付物本体）
          → 记录缓存状态 → `ptcache.free_bake_all()`
          → **从 scene.frame_start 顺序 frame_set 到 frame_end**（不做 bake_all，不触 §6）
          → 记录 `is_outdated` 是否变 false、磁盘缓存标志
          → `save_as_mainfile(dst)`
`probe`：**新进程**打开 dst → 记录打开时缓存状态 → **直接 `frame_set(frame)`**（冷跳）
          → 落 324 刚体世界坐标。

判定（离线 m02_s8_p12_cmp.py）：
  probe@109 == P0[109]  ⇒ 修法定案（顺序跑一遍再存盘即可，无需 bake_all）
  不等                   ⇒ 不烘焙交付不可行，才轮到 §6 讨论
同时落 `seq` 里顺序跑到 109 / 240 的坐标，用来区分「存盘没保住」还是「冷跳本身不同」。
"""
import hashlib
import json
import os
import sys

import bpy

CHECK_FRAMES = (1, 109, 240)


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
    out = {"is_baked": bool(pc.is_baked), "is_outdated": bool(pc.is_outdated),
           "info": str(pc.info), "frame_start": pc.frame_start, "frame_end": pc.frame_end}
    try:
        out["use_disk_cache"] = bool(pc.use_disk_cache)
        out["cache_filepath"] = str(pc.cache_filepath)
    except AttributeError as exc:  # 记下来，不要猜
        out["use_disk_cache_error"] = str(exc)
    return out


def rigid_objs():
    return sorted([o for o in bpy.data.objects
                   if getattr(o, "rigid_body", None) is not None], key=lambda o: o.name)


def snapshot(objs):
    return {o.name: [round(v, 6) for v in o.matrix_world.translation] for o in objs}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) < 4:
        raise SystemExit("usage: m02_s8_p12.py -- <make|probe> <in.blend> <arg> <out.json>")
    mode, src, arg, out_path = argv[0], argv[1], argv[2], argv[3]

    if mode == "make":
        dst = arg
        if os.path.abspath(src) == os.path.abspath(dst):
            raise SystemExit("拒绝覆盖入参工程")
        sha_before = sha256_file(src)
        bpy.ops.wm.open_mainfile(filepath=src)
        sc = bpy.context.scene
        rbw = sc.rigidbody_world
        at_open = cache_state(rbw)
        bpy.ops.ptcache.free_bake_all()
        after_free = cache_state(rbw)

        f0, f1 = int(sc.frame_start), int(sc.frame_end)
        objs = rigid_objs()
        steps = []
        snaps = {}
        for f in range(f0, f1 + 1):
            sc.frame_set(f)
            steps.append(f)
            if f in CHECK_FRAMES:
                snaps[f] = snapshot(objs)
        after_walk = cache_state(rbw)

        bpy.ops.wm.save_as_mainfile(filepath=dst)
        out = {"mode": "make", "src": src, "dst": dst,
               "src_sha256_before": sha_before,
               "src_sha256_after": sha256_file(src),
               "src_untouched": sha_before == sha256_file(src),
               "dst_sha256": sha256_file(dst),
               "cache_at_open": at_open, "cache_after_free": after_free,
               "cache_after_walk": after_walk,
               "walk": {"from": f0, "to": f1, "frames": len(steps),
                        "sequential": steps == list(range(f0, f1 + 1)),
                        "api": "scene.frame_set(f) for f in range(frame_start, frame_end+1)"},
               "bodies": len(objs),
               "seq_pos": {str(f): v for f, v in snaps.items()},
               "saved": True}
        print("P12 make src_untouched=%s frames=%d baked_after_walk=%s outdated_after_walk=%s"
              % (out["src_untouched"], len(steps),
                 after_walk["is_baked"] if after_walk else None,
                 after_walk["is_outdated"] if after_walk else None))

    elif mode == "probe":
        frame = int(arg)
        sha_before = sha256_file(src)
        bpy.ops.wm.open_mainfile(filepath=src)
        sc = bpy.context.scene
        rbw = sc.rigidbody_world
        at_open = cache_state(rbw)
        objs = rigid_objs()
        sc.frame_set(frame)
        after = cache_state(rbw)
        out = {"mode": "probe", "blend": src, "frame": frame,
               "blend_sha256_before": sha_before,
               "blend_sha256_after": sha256_file(src),
               "source_untouched": sha_before == sha256_file(src),
               "cache_at_open": at_open, "cache_after_step": after,
               "cold_jump": True, "bodies": len(objs),
               "pos": snapshot(objs)}
        print("P12 probe frame=%d bodies=%d baked_at_open=%s outdated_at_open=%s"
              % (frame, len(objs), at_open["is_baked"] if at_open else None,
                 at_open["is_outdated"] if at_open else None))
    else:
        raise SystemExit("unknown mode: %s" % mode)

    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    sys.stdout.flush()
    os._exit(0)


main()
