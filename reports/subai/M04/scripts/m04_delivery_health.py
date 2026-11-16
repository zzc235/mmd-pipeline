# -*- coding: utf-8 -*-
"""C/D 发车前对 `delivery_v1` 的只读体检（M04）。

要回答的问题，一个脚本一次回答（省得每个问题各开一次 Blender）：

1. 场景里**有没有动作**（`bpy.data.actions` / 骨架 `animation_data` / NLA）——C/D 要跑 240 与 832 帧，
   没有动作就没有「换场景 / 换振幅」可言，`max_depth_m` 会是一条常数；
2. `scene.frame_start/frame_end`（窗口是**回读**的，不是声明的）；
3. 刚体数（`mmd_type` u323，先 enable 扩展再读）与 ROI 骨是否解析得出；
4. `is_baked` / `is_outdated` / `point_cache.evaluate()`（A1：跑前必须 false）；
5. 掩码三元组：`WIRED` / `constraints_capped` / `skipped_count` —— 在**这个场景**上回读（`D-162`）。

跑法：
    blender -b --python m04_delivery_health.py -- --blend <path> --out <json> [--roi 18]
"""
import argparse
import json
import os
import sys

import bpy
from addon_utils import enable


def _plain(value):
    """把 Blender 的 `IDPropertyArray` / 各类 RNA 值压成纯 Python（1号 在
    `tests_bpy/m08_accept_probe.py` 上踩过同一个坑：`TypeError: IDPropertyArray is not
    JSON serializable`）。**压不动就把它记成字符串**，不许让字段静默消失。"""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    try:
        return _plain(list(value))          # IDPropertyArray / bpy_prop_collection 之类
    except Exception:                        # noqa: BLE001
        return repr(value)


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--blend", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--roi-label", default="18_skirt_rigid")
    return ap.parse_args(argv)


def main():
    a = _args()
    bpy.ops.wm.open_mainfile(filepath=a.blend)
    sc = bpy.context.scene

    addon = "bl_ext.user_default.mmd_tools"
    try:
        enable(addon, default_set=True)
        addon_state = "enabled"
    except Exception as exc:                      # noqa: BLE001
        addon_state = "FAILED: %s" % exc

    out = {
        "spec": "m04_delivery_health/1",
        "blend": a.blend,
        "addon": addon_state,
        "scene": {"name": sc.name, "frame_start": int(sc.frame_start), "frame_end": int(sc.frame_end),
                  "fps": sc.render.fps},
        "objects": {},
    }

    arms = [o for o in sc.objects if o.type == "ARMATURE"]
    out["armatures"] = [o.name for o in arms]
    arm = arms[0] if arms else None
    if arm is not None:
        ad = arm.animation_data
        out["armature_action"] = {
            "action": (ad.action.name if (ad and ad.action) else None),
            "frame_range": (list(ad.action.frame_range) if (ad and ad.action) else None),
            "nla_tracks": [{"name": t.name, "strips": [{"action": s.action.name if s.action else None,
                                                        "frame_start": s.frame_start,
                                                        "frame_end": s.frame_end,
                                                        "repeat": s.repeat}
                                                       for s in t.strips]}
                           for t in (ad.nla_tracks if ad else [])],
            "drivers": len(ad.drivers) if ad else 0,
        }
    out["actions_all"] = [{"name": ac.name, "frame_range": list(ac.frame_range),
                           "users": ac.users} for ac in bpy.data.actions][:20]

    # 刚体：`mmd_type` 只在扩展 enable 之后才存在（1号 2026-11-16 自己踩过）
    rigids = [o for o in sc.objects if getattr(o, "mmd_type", None) == "RIGID_BODY"]
    out["rigids"] = {"count": len(rigids),
                     "sample": [o.name for o in rigids[:8]],
                     "placeholders": [o.name for o in rigids if o.name.startswith("$")][:20]}

    # 缓存状态 + 行为探针的第一半（这里只读状态；冷跳/顺序重算的比较归 4号 的探针）
    world = None
    for o in sc.objects:
        if getattr(o, "rigidbody_world", None) is not None:
            world = o.rigidbody_world
            break
    if world is None:
        rbw = getattr(sc, "rigidbody_world", None)
        world = rbw
    if world is not None:
        pc = world.point_cache
        ev = None
        try:
            ev = world.point_cache.evaluate() if hasattr(world.point_cache, "evaluate") else None
        except Exception as exc:                  # noqa: BLE001
            ev = "evaluate() raised: %s" % exc
        out["cache"] = {"is_baked": bool(pc.is_baked), "is_outdated": bool(pc.is_outdated),
                        "frame_start": int(pc.frame_start), "frame_end": int(pc.frame_end),
                        "use_disk_cache": bool(pc.use_disk_cache), "evaluate": ev}
    else:
        out["cache"] = {"error": "没有 rigidbody_world"}

    # 掩码三元组：从**这个场景**回读记录（`D-162`）
    out["mask_wired"] = _plain(dict((sc.get("mask_wired") or {})))
    out["mask_wired_keys"] = sorted((sc.get("mask_wired") or {}).keys())

    # ROI 骨：`下擺_*` 与 18 根胶囊骨是否解析得出
    if arm is not None:
        names = [b.name for b in arm.data.bones]
        skirt = [n for n in names if "下擺" in n or "下摆" in n]
        out["roi"] = {"bones_total": len(names), "skirt_bones": skirt[:30],
                      "skirt_count": len(skirt), "label": a.roi_label}

    out = _plain(out)

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    print("[health] written %s" % a.out)
    print(json.dumps({k: out[k] for k in ("scene", "armature_action", "rigids", "cache") if k in out},
                     ensure_ascii=False)[:1200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
