"""交付件「缓存到底能不能用」的行为探针（`D-214` ②，一个进程里做完）。

重开烘过的件后 `is_baked=true / is_outdated=true` **不能定性** —— 回读那边写得很清楚：
真烘焙件重开也是这两个值，要定性必须比姿态。所以这里做对照：

1. **冷跳**（缓存还在）：`frame_set(0)` → `frame_set(N)` → 取刚体世界矩阵（= `cache_replay`）；
2. **顺序重算**（缓存已释放）：`ptcache.free_bake_all()` → 从 `frame_start` 逐帧步进到 N → 同一批刚体再取一次（= `fresh_solve`）；
3. 逐值比。

两者逐值相等 ⇒ 存进 `.blend` 的缓存钉的就是这条轨迹（可交付）；
不等 ⇒ 文件里的缓存不可用（回读看到的 `is_baked=true` 只是标志位）。

用法：
    blender -b <baked.blend> --python m02_baked_cache_probe.py -- <out.json> [frame]
"""

import json
import os
import sys

import bpy

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_TREE = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
for _p in (_TREE, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from mmdpipe import stage  # noqa: E402

TOL = 1e-6


def enable_mmd_tools():
    import addon_utils
    for name in ("bl_ext.user_default.mmd_tools", "mmd_tools"):
        try:
            addon_utils.enable(name, default_set=False, persistent=False)
        except Exception:  # noqa: BLE001
            pass
    return [n for n in ("bl_ext.user_default.mmd_tools", "mmd_tools")
            if n in {a.module for a in bpy.context.preferences.addons}]


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out_path = argv[0] if argv else "baked_cache_probe.json"
    frame = int(argv[1]) if len(argv) > 1 else 417

    addon = enable_mmd_tools()
    scene = bpy.context.scene
    pc = scene.rigidbody_world.point_cache
    bodies = stage.rigid_bodies()
    rec = {
        "blend": os.path.abspath(bpy.data.filepath),
        "frame": frame,
        "addons": addon,
        "bodies": len(bodies),
        "cache_before": {"is_baked": bool(pc.is_baked), "is_outdated": bool(pc.is_outdated),
                         "use_disk_cache": bool(pc.use_disk_cache), "info": pc.info,
                         "frame_start": int(pc.frame_start), "frame_end": int(pc.frame_end)},
        "scene": {"frame_start": int(scene.frame_start), "frame_end": int(scene.frame_end),
                  "fps": int(scene.render.fps)},
    }
    if not bodies or not rec["cache_before"]["is_baked"]:
        rec["status"] = "REFUSED"
        rec["reason"] = "件里没有可用的缓存标志（is_baked=false）或没有刚体，无法做这个对照"
        return finish(rec, out_path, 4)

    # ① 冷跳（走缓存）
    scene.frame_set(max(0, int(pc.frame_start) - 1))
    scene.frame_set(frame)
    cached = stage.pose_snapshot(bodies)
    rec["cached_pose_sha"] = _pose_sha(cached)

    # ② 顺序重算（先释放缓存，再逐帧步进）
    bpy.ops.ptcache.free_bake_all()
    rec["cache_after_free"] = {"is_baked": bool(pc.is_baked), "info": pc.info}
    for f in range(int(pc.frame_start), frame + 1):
        scene.frame_set(f)
    fresh = stage.pose_snapshot(bodies)
    rec["fresh_pose_sha"] = _pose_sha(fresh)

    deltas = []
    names = sorted(set(cached) | set(fresh))
    for name in names:
        if name not in cached or name not in fresh:
            deltas.append({"name": name, "error": "缺一侧"})
            continue
        worst = max(abs(a - b) for a, b in zip(cached[name], fresh[name]))
        if worst > TOL:
            deltas.append({"name": name, "max_delta": round(worst, 9)})
    rec["compare"] = {"bodies": len(names), "over_tol": len(deltas),
                      "tol": TOL, "sample": deltas[:10],
                      "max_delta": max([d.get("max_delta", 0.0) for d in deltas] or [0.0])}
    rec["status"] = "CACHE_USABLE" if not deltas else "CACHE_NOT_USABLE"
    return finish(rec, out_path, 0 if not deltas else 5)


def _pose_sha(snap):
    import hashlib
    payload = json.dumps({k: [round(float(v), 9) for v in vals]
                          for k, vals in sorted(snap.items())}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def finish(rec, out_path, code):
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("CACHEPROBE status=%s rc=%d over_tol=%r max_delta=%r"
          % (rec.get("status"), code,
             (rec.get("compare") or {}).get("over_tol"),
             (rec.get("compare") or {}).get("max_delta")))
    sys.stdout.flush()
    os._exit(code)


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:                       # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("CACHEPROBE ERROR %s: %s" % (type(exc).__name__, exc))
        sys.stdout.flush()
        os._exit(9)
