# -*- coding: utf-8 -*-
"""真 Blender：把 `stage.stage_bake()` 跑一次（契约 B 的探针，T3 口径）。

    blender -b --factory-startup --python-exit-code 3 --python real_bake_probe.py -- \
        --blend <冻结的 324 件.blend> --frames 24 --out <产物.json>

做四件事，全程**只读**（不存盘、不写全局 prefs）：

1. 打开冻结件、`stage.ensure_addons(("mmd_tools",))` 并断言可用（`mmd_rigid` 是插件注册的属性组）；
2. 记打开时与烘焙前的缓存状态（`is_baked` / `is_outdated` / `frame_start` / `frame_end` / `fps`）；
3. `stage.stage_bake(scene, {"frame_start": 1, "frame_end": N})` —— 真调 `bpy.ops.ptcache.bake_all`；
4. 落盘 `bake` 记录（`requested/applied/frame_start/frame_end/fps/pose_source/is_baked/
   is_outdated/probe`）+ `bake_checks()` 五条 + `bake_gate_reason()`。

窗口要小（默认 24 帧）：这一步只证「算子能跑、探针能判」，不是出交付件。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))))         # .../out/subai/M00/scripts -> worktree
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bpy                                  # noqa: E402
from mmdpipe import stage                   # noqa: E402


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cache_state(scene) -> dict:
    rbw = getattr(scene, "rigidbody_world", None)
    if rbw is None:
        return {"has_world": False}
    cache = rbw.point_cache
    return {"has_world": True, "is_baked": bool(cache.is_baked),
            "is_outdated": bool(cache.is_outdated),
            "frame_start": int(cache.frame_start), "frame_end": int(cache.frame_end),
            "use_disk_cache": bool(getattr(cache, "use_disk_cache", False))}


def run(blend: str, frames: int) -> dict:
    res = {"blend": os.path.abspath(blend), "frames": frames,
           "blender": bpy.app.version_string, "truth_tier": "T3", "tree": HERE}
    res["blend_sha256_before"] = _sha256(blend)
    bpy.ops.wm.open_mainfile(filepath=blend)
    scene = bpy.context.scene
    res["scene"] = scene.name
    res["fps"] = int(getattr(scene.render, "fps", 0) or 0)
    res["actions"] = [a.name for a in bpy.data.actions]
    res["addons"] = dict(stage.ensure_addons(names=("mmd_tools",)))
    if not res["addons"].get("mmd_tools"):
        res["failed"] = ["mmd_tools_not_ready"]
        res["ok"] = False
        return res
    # **必须启用之后再数**：`mmd_rigid` 是插件注册的属性组，之前数恒为 0
    # （第一版就这么落了个假的 `rigids_u323=0`，而实际烘的是 323 个刚体）。
    res["rigids_u323"] = len(stage.rigid_bodies())
    res["cache_before"] = cache_state(scene)

    req = {"frame_start": 1, "frame_end": int(frames)}
    try:
        record = stage.stage_bake(scene, req)
    except Exception:
        res["failed"] = ["stage_bake_raised"]
        res["traceback"] = traceback.format_exc()
        res["ok"] = False
        return res

    res["bake"] = record
    res["cache_after"] = cache_state(scene)
    res["checks"] = stage.bake_checks(record)
    res["gate_reason"] = stage.bake_gate_reason(record)
    res["probe"] = record.get("probe")
    # 期望：真烘之后 applied/is_baked 为真、探针 matched，闸门无理由
    res["expectations"] = {
        "applied_true": record.get("applied") is True,
        "is_baked_true": record.get("is_baked") is True,
        "probe_matched": bool((record.get("probe") or {}).get("matched")),
        "gate_reason_none": stage.bake_gate_reason(record) is None,
    }
    res["failed"] = [k for k, v in res["expectations"].items() if not v]
    res["ok"] = not res["failed"]
    res["blend_sha256_after"] = _sha256(blend)      # 不许被这次跑改到
    res["blend_untouched"] = res["blend_sha256_before"] == res["blend_sha256_after"]
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--blend", required=True)
    ap.add_argument("--frames", type=int, default=24)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv if argv is not None else sys.argv[sys.argv.index("--") + 1:])
    payload = {"ok": False}
    code = 0
    try:
        payload = run(args.blend, args.frames)
        code = 0 if payload.get("ok") else 3
    except Exception:
        payload = {"ok": False, "failed": ["exception"], "traceback": traceback.format_exc()}
        code = 3
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
