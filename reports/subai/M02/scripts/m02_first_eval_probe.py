"""三读数定机制：同一份件上「开件后首读」与「free 之后」的差，到底来自标志位还是来自未初始化状态。

背景（19:14 vs 19:20 两个探针在同一份件上给出 1.8565 m 与 0.0）：两次「冷跳」的前置状态不同 ——
一支是**开件后一次模拟都没跑**就冷跳，一支是走完全程之后再冷跳。这里把两种前置状态放进同一个进程、
按顺序各取一次，用同一批刚体、同一帧、同一 tol 比：

    P0  开件后立刻冷跳 0→N                （= 19:14 那支的「冷跳」，`is_baked=true` 陈旧标志在位）
    P1  `ptcache.free_bake_all()` 之后再冷跳 0→N（标志位已被清掉，帧数据仍要现算）
    P2  从 frame_start 顺序步进到 N        （= 顺序重算，判据本身）

判读：
    P0 ≠ P2 且 P1 == P2 ⇒ 差异来自**开件后的首读**（陈旧标志 / 未初始化），与本件内容无关；
    P0 ≠ P2 且 P1 ≠ P2 ⇒ 冷跳与顺序重算本身不同（解算依赖遍历方式），两次都算「同一件事」；
    P0 == P1 == P2      ⇒ 19:14 那次读数是别的原因，要重查那支探针。

不存盘、不烘。用法：
    blender -b <frozen.blend> --python m02_first_eval_probe.py -- <out.json> [N]
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
            "max_delta": round(max([b.get("max_delta", 0.0) for b in bad] or [0.0]), 9),
            "sample": bad[:5]}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out_path = argv[0] if argv else "first_eval.json"
    free_first = "--free-first" in argv
    nums = [a for a in argv[1:] if not a.startswith("--")]
    frame = int(nums[0]) if nums else 417

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
        "stage": "first-eval-probe-v1",
        "blend": {"path": os.path.abspath(path), "sha256": sha256_file(path),
                  "bytes": os.path.getsize(path)},
        "frame": frame, "bodies": len(bodies), "tol": TOL,
        "cache_at_open": {"is_baked": bool(pc.is_baked), "is_outdated": bool(pc.is_outdated),
                          "use_disk_cache": bool(pc.use_disk_cache), "info": pc.info},
        "frame_start": int(pc.frame_start),
    }

    # `--free-first`：**先**清掉标志位，再做开件后的第一次求值（总控 19:34 要求的那个设计）。
    # 不加这个开关时 P0 才是「开件后第一次求值」（此时 `is_baked` 仍是文件里的陈旧值）。
    if free_first:
        bpy.ops.ptcache.free_bake_all()
        rec["freed_before_first_eval"] = True
        rec["cache_after_free_pre_eval"] = {"is_baked": bool(pc.is_baked), "info": pc.info}

    # P0：开件后立刻冷跳（第一次求值）
    scene.frame_set(max(0, int(pc.frame_start) - 1))
    scene.frame_set(frame)
    p0 = stage.pose_snapshot(bodies)
    rec["p0_first_eval_sha"] = pose_sha(p0)
    if free_first:
        # 已经清过标志位，P1 与 P0 是同一件事，跳过以免多一次求值污染读数
        rec["p1_cold_after_free_sha"] = None
        p1 = None
    else:
        # P1：清掉标志位/缓存后再冷跳（**注意**：此时 P0 已经求值过一次，所以这不是「开件后首读」）
        bpy.ops.ptcache.free_bake_all()
        rec["cache_after_free"] = {"is_baked": bool(pc.is_baked), "info": pc.info}
        scene.frame_set(max(0, int(pc.frame_start) - 1))
        scene.frame_set(frame)
        p1 = stage.pose_snapshot(bodies)
        rec["p1_cold_after_free_sha"] = pose_sha(p1)

    # P2：顺序步进到该帧
    for f in range(int(pc.frame_start), frame + 1):
        scene.frame_set(f)
    p2 = stage.pose_snapshot(bodies)
    rec["p2_sequential_sha"] = pose_sha(p2)

    rec["compare"] = {
        "p0_vs_p2": compare(p0, p2),
        "p1_vs_p2": compare(p1, p2) if p1 is not None else None,
        "p0_vs_p1": compare(p0, p1) if p1 is not None else None,
    }
    c = rec["compare"]
    if c["p0_vs_p2"]["over_tol"] == 0:
        rec["reading"] = "FIRST_EVAL_MATCHES"             # 清过标志位之后首读与顺序一致
    elif c["p1_vs_p2"] is not None and c["p1_vs_p2"]["over_tol"] == 0:
        rec["reading"] = "FIRST_EVAL_ONLY"               # 只有开件后首读不同
    else:
        rec["reading"] = "COLD_VS_SEQUENTIAL"            # 冷跳与顺序本身不同（含 free-first 情形）
    return finish(rec, out_path)


def finish(rec, out_path):
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    c = rec["compare"]
    print("FIRSTEVAL reading=%s p0_vs_p2=%r/%r p1_vs_p2=%r p0_vs_p1=%r"
          % (rec["reading"],
             c["p0_vs_p2"]["over_tol"], c["p0_vs_p2"]["max_delta"],
             (c["p1_vs_p2"] or {}).get("max_delta"),
             (c["p0_vs_p1"] or {}).get("max_delta")))
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:                       # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("FIRSTEVAL ERROR %s: %s" % (type(exc).__name__, exc))
        sys.stdout.flush()
        os._exit(9)
