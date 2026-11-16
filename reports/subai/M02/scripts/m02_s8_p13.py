"""M02 · P13：一次受控的 `bpy.ops.ptcache.bake_all()` 实测（D0 临时豁免 10 §6 一次）。

目的：A 路（解烘焙交付 + 顺序求值契约）对交付方没问题，对**打开文件的人**是陷阱——
谁拖时间轴谁看到另一条动画。这次实验回答：烘焙能不能给出「冷跳到任意帧也正确」的产物。

    blender -b -P m02_s8_p13.py -- bake  <src.blend> <dst.blend> <out.json>
    blender -b -P m02_s8_p13.py -- probe <dst.blend> <frame> <out.json>

规矩（D0 13:27:36 给定）：
- 只在副本上：`src` 由外部先拷成工作副本，本脚本**不写**入参；
- **单次，不重试**。段错误就把退出码与发生时点当结果上报；
- 记 `use_disk_cache`，它可能决定成败；
- 成功也要验：新进程冷跳 `frame` == `P0[frame]`，不等则结论同样是「不可用」。

时间线以 JSONL 逐行追加并 flush——C 侧崩溃时也能留下「崩在哪一步」。
"""
import hashlib
import json
import os
import sys
import time

import bpy

T0 = time.time()


def secs():
    return round(time.time() - T0, 3)


class Trail:
    def __init__(self, path):
        self.path = path
        self.fh = open(path, "a", encoding="utf-8", newline="\n")

    def log(self, step, **kw):
        rec = {"t": secs(), "step": step}
        rec.update(kw)
        self.fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
        self.fh.flush()
        os.fsync(self.fh.fileno())
        print("P13 %7.3fs %s %s" % (rec["t"], step, json.dumps(kw, ensure_ascii=False)))
        sys.stdout.flush()

    def close(self):
        self.fh.close()


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
    except AttributeError as exc:
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
        raise SystemExit("usage: m02_s8_p13.py -- <bake|probe> <in.blend> <arg> <out.json>")
    mode, src, arg, out_path = argv[0], argv[1], argv[2], argv[3]
    trail = Trail(os.path.splitext(out_path)[0] + ".timeline.jsonl")

    if mode == "bake":
        dst = arg
        if os.path.abspath(src) == os.path.abspath(dst):
            raise SystemExit("拒绝覆盖入参工程")
        sha_before = sha256_file(src)
        trail.log("start", src=src, dst=dst, src_sha256=sha_before)
        bpy.ops.wm.open_mainfile(filepath=src)
        sc = bpy.context.scene
        rbw = sc.rigidbody_world
        before = cache_state(rbw)
        objs = rigid_objs()
        trail.log("opened", cache_before=before, bodies=len(objs),
                  frame_start=int(sc.frame_start), frame_end=int(sc.frame_end))

        err = None
        trail.log("bake_begin", api="bpy.ops.ptcache.bake_all(bake=True)")
        try:
            bpy.ops.ptcache.bake_all(bake=True)
        except Exception as exc:  # 操作符报错也是结果，别吞
            err = "%s: %s" % (type(exc).__name__, exc)
            trail.log("bake_error", error=err)
        after_bake = cache_state(rbw)
        trail.log("bake_done", error=err, cache_after_bake=after_bake)

        save_err, dst_sha = None, None
        try:
            bpy.ops.wm.save_as_mainfile(filepath=dst)
            dst_sha = sha256_file(dst) if os.path.exists(dst) else None
        except Exception as exc:
            save_err = "%s: %s" % (type(exc).__name__, exc)
        trail.log("saved", save_error=save_err, dst_sha256=dst_sha)

        out = {"mode": "bake", "src": src, "dst": dst,
               "src_sha256_before": sha_before,
               "src_sha256_after": sha256_file(src),
               "src_untouched": sha_before == sha256_file(src),
               "dst_sha256": dst_sha, "save_error": save_err,
               "cache_before": before, "cache_after_bake": after_bake,
               "bake_error": err, "bodies": len(objs),
               "api": "bpy.ops.ptcache.bake_all(bake=True)",
               "single_attempt": True, "elapsed_s": secs()}

    elif mode == "probe":
        frame = int(arg)
        sha_before = sha256_file(src)
        trail.log("probe_start", blend=src, frame=frame)
        bpy.ops.wm.open_mainfile(filepath=src)
        sc = bpy.context.scene
        rbw = sc.rigidbody_world
        at_open = cache_state(rbw)
        objs = rigid_objs()
        trail.log("probe_opened", cache_at_open=at_open, bodies=len(objs))
        sc.frame_set(frame)
        after = cache_state(rbw)
        out = {"mode": "probe", "blend": src, "frame": frame,
               "blend_sha256_before": sha_before,
               "blend_sha256_after": sha256_file(src),
               "source_untouched": sha_before == sha256_file(src),
               "cache_at_open": at_open, "cache_after_step": after,
               "cold_jump": True, "bodies": len(objs),
               "pos": snapshot(objs)}
        trail.log("probe_done", cache_after_step=after)
    else:
        raise SystemExit("unknown mode: %s" % mode)

    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    trail.log("written", out=out_path)
    trail.close()
    sys.stdout.flush()
    os._exit(0)


main()
