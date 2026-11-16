"""`recomputed` 记录：在**冻结件**上证明「场景可确定性重建」（`D-218` 派工，硬边界四条）。

不烘、不存盘、不重出件 —— 只产一条记录。一个进程里两遍：

- **A 顺序重算**：先 `ptcache.free_bake_all()`（丢掉从别处带进来的缓存），再从 `frame_start`
  **逐帧**步进到最深目标帧，在目标帧上取刚体世界矩阵；
- **B 冷跳重读**：对同一批帧先跳回起点前再冷跳到目标帧，取同一批刚体。

判据是 A 对 B（`tol=1e-6`）。**B 不是「从缓存读」**（缓存已释放），它是「同一进程里第二次求值」，
所以 A 与 B 一致只能证明**本进程内**解算一致；跨会话的一致性靠**同一脚本跑两遍、比 A 的 pose sha**
来验（两遍是两个独立 Blender 会话）。两条结论分开写，不合并。

用法：
    blender -b <frozen.blend> --python m02_recompute_verify.py -- <out.json> [417,833]
"""

import hashlib
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


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pose_sha(snap):
    payload = json.dumps({k: [round(float(v), 9) for v in vals]
                          for k, vals in sorted(snap.items())}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compare(left, right, tol=TOL):
    names = sorted(set(left) | set(right))
    bad = []
    for name in names:
        if name not in left or name not in right:
            bad.append({"name": name, "error": "缺一侧"})
            continue
        worst = max(abs(a - b) for a, b in zip(left[name], right[name]))
        if worst > tol:
            bad.append({"name": name, "max_delta": round(worst, 9)})
    return {"bodies": len(names), "over_tol": len(bad), "tol": tol,
            "max_delta": max([b.get("max_delta", 0.0) for b in bad] or [0.0]),
            "sample": bad[:10]}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out_path = argv[0] if argv else "recomputed.json"
    targets = [int(x) for x in (argv[1].split(",") if len(argv) > 1 else ["417", "833"])]

    import addon_utils
    for name in ("bl_ext.user_default.mmd_tools", "mmd_tools"):
        try:
            addon_utils.enable(name, default_set=False, persistent=False)
        except Exception:  # noqa: BLE001
            pass
    scene = bpy.context.scene
    path = bpy.data.filepath
    bodies = stage.rigid_bodies()
    pc = scene.rigidbody_world.point_cache
    rec = {
        "stage": "recompute-verify-v1",
        "blend": {"path": os.path.abspath(path), "sha256": sha256_file(path),
                  "bytes": os.path.getsize(path)},
        "targets": targets,
        "bodies": len(bodies),
        "tol": TOL,
        "scene": {"frame_start": int(scene.frame_start), "frame_end": int(scene.frame_end),
                  "fps": int(scene.render.fps)},
        "cache_at_open": {"is_baked": bool(pc.is_baked), "is_outdated": bool(pc.is_outdated),
                          "use_disk_cache": bool(pc.use_disk_cache), "info": pc.info},
        "python": sys.version.split()[0],
        "blender": bpy.app.version_string,
    }
    if not bodies:
        rec["verdict"] = "REFUSED"
        rec["reason"] = "件里没有刚体"
        return finish(rec, out_path, 4)

    # ① 丢掉带进来的缓存：否则「顺序重算」读到的可能是别人的轨迹
    bpy.ops.ptcache.free_bake_all()
    rec["cache_after_free"] = {"is_baked": bool(pc.is_baked), "info": pc.info}

    # ② A：从 frame_start 逐帧顺序步进，在目标帧取姿态（**不许冷跳上来**）
    first = int(pc.frame_start)
    deepest = max(targets)
    seq = {}
    for frame in range(first, deepest + 1):
        scene.frame_set(frame)
        if frame in targets:
            seq[frame] = stage.pose_snapshot(bodies)
    rec["pass_a_sequential"] = {str(f): pose_sha(s) for f, s in seq.items()}

    # ③ B：同一批帧冷跳重读（先离开，再跳回）
    cold = {}
    for frame in targets:
        scene.frame_set(max(0, first - 1))
        scene.frame_set(frame)
        cold[frame] = stage.pose_snapshot(bodies)
    rec["pass_b_cold_reread"] = {str(f): pose_sha(s) for f, s in cold.items()}

    per_frame = {}
    worst = 0.0
    over = 0
    for frame in targets:
        cmp = compare(seq.get(frame, {}), cold.get(frame, {}))
        per_frame[str(frame)] = cmp
        worst = max(worst, cmp["max_delta"])
        over += cmp["over_tol"]
    rec["compare"] = {"per_frame": per_frame, "max_delta": worst, "over_tol_total": over,
                      "bodies": len(bodies), "tol": TOL}
    consistent = over == 0
    rec["first_eval_after_open"] = False
    # `D-223` ①：任何「开件后立刻读姿态」的读数都要带这个标注。本脚本两条腿都**不是**首读：
    # A 从 `frame_start` 顺序步进，B 在 A 之后冷跳。`matrix_world` 类读数只有在热身之后才可复现
    # —— 实测首读与热身后 323/323 不同、最大差 1.9923 m（`digest_warmup.json`）。
    rec["verdict"] = "RECOMPUTE_CONSISTENT" if consistent else "RECOMPUTE_INCONSISTENT"
    rec["scope"] = ("A 与 B 都是本进程内的求值（B 是在缓存已释放后的第二次求值）："
                    "这一致性只证明**本进程内**解算稳定，不证明跨会话一致、也不证明交付件自带可回放缓存。"
                    "跨会话是否一致要同一脚本跑两遍、比 pass_a_sequential 的 pose sha。")
    return finish(rec, out_path, 0 if consistent else 5)


def finish(rec, out_path, code):
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("RECOMPUTE verdict=%s rc=%d over_tol=%r max_delta=%r bodies=%r"
          % (rec.get("verdict"), code, (rec.get("compare") or {}).get("over_tol_total"),
             (rec.get("compare") or {}).get("max_delta"), rec.get("bodies")))
    sys.stdout.flush()
    os._exit(code)


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:                       # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("RECOMPUTE ERROR %s: %s" % (type(exc).__name__, exc))
        sys.stdout.flush()
        os._exit(9)
