# -*- coding: utf-8 -*-
"""M08 交付重建后的**读回采集器**（在 Blender 里跑，只读不判）。

为什么另写一支：4号 的 `tests_bpy/m08_accept_probe.py` 在真场景上报
`TypeError: Object of type IDPropertyArray is not JSON serializable`——`scene["mask_wired"]`
里存的是 IDProperty 容器，`json.dump` 直接吐不出来。那是采集器的缺陷（已单独报），
本脚本只补一件事：**把读回来的东西强制变成可序列化的普通 Python 值**，别让「读得出来」
变成「存不下来」。

采集四样（总控 17:49 要求交给 2号 的正是这四样）：
1. 产物路径 + sha256；
2. `stage_mask()` 的三元组（verdict / constraints_capped / skipped_count）与完整报告；
3. `point_cache` 的 `is_baked` / `is_outdated` 回读 + `cache_state.evaluate()` 判词；
4. 刚体计数两个宇宙（`stage.rigid_bodies()` 与 `rigid_body is not None`）。

退出码（`D-135`：Blender 会把脚本异常吞成 0，所以自己给非零码）：
    0  采集完成；3  采集过程出错。
"""

import hashlib
import json
import os
import sys
import traceback

# GBK 控制台下中文/符号会让脚本崩在打印上（总控 18:18）：入口统一 UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass


def find_tree(start):
    """往上找到含 `mmdpipe/` 的那一层——脚本住在 reports/subai/M02/scripts/ 下，
    树根不是 dirname(dirname(__file__))。找不到就报错，别让 import 撞运气。"""
    cur = os.path.abspath(start)
    for _ in range(8):
        if os.path.isdir(os.path.join(cur, "mmdpipe")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


TREE = find_tree(os.path.dirname(os.path.abspath(__file__)))
if not TREE:
    print("READBACK ERROR 找不到含 mmdpipe/ 的树根")
    sys.exit(3)
if TREE not in sys.path:
    sys.path.insert(0, TREE)

import bpy                                            # noqa: E402
import addon_utils                                    # noqa: E402
from mmdpipe import cache_state as cache_mod          # noqa: E402
from mmdpipe import stage                             # noqa: E402

# 逐刚体字段的读取只许一份实现（`m02_patch_bpy.digest_body`），这里复用，不另写一套
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import m02_patch_bpy as pb                            # noqa: E402


def enable_mmd_tools():
    """扩展注册的 RNA 属性（`mmd_type` / `mmd_rigid`）**只有在 enable 之后才存在**。

    不先 enable 的话，`getattr(o, "mmd_type", None)` 对所有对象都是 None，
    `stage.rigid_bodies()` 会诚实地返回 0 个——那是「读不到」，不是「没有」。
    本地第一次跑就踩了这个坑：u323=0 / u324=312。
    """
    for mod in addon_utils.modules():
        if "mmd_tools" in getattr(mod, "__name__", ""):
            addon_utils.enable(mod.__name__, default_set=True, handle_error=None)
            return mod.__name__
    return None


def plain(value, depth=0):
    """把 IDPropertyArray / IDPropertyGroup / bpy 值压成 JSON 可序列化的普通值。"""
    if depth > 8:
        return repr(value)[:200]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): plain(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v, depth + 1) for v in value]
    # IDPropertyArray / IDPropertyGroup / IDPropertyArray 的兄弟
    try:
        if hasattr(value, "to_list"):
            return [plain(v, depth + 1) for v in value.to_list()]
    except Exception:                                  # noqa: BLE001
        pass
    try:
        return {str(k): plain(value[k], depth + 1) for k in value.keys()}
    except Exception:                                  # noqa: BLE001
        pass
    try:
        return [plain(v, depth + 1) for v in value]
    except Exception:                                  # noqa: BLE001
        return repr(value)[:200]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def module_provenance():
    out = {"blender": bpy.app.version_string}
    for name in ("mmdpipe.stage", "mmdpipe.mask", "mmdpipe.cache_state"):
        path = getattr(sys.modules.get(name), "__file__", None)
        out[name] = {"file": path,
                     "sha256": sha256_file(path) if path and os.path.exists(path) else None}
    return out


def collect(blend_path):
    scene = bpy.context.scene
    addon = enable_mmd_tools()
    rbw = getattr(scene, "rigidbody_world", None)
    cache = getattr(rbw, "point_cache", None) if rbw is not None else None

    rigids_u324 = [o for o in scene.objects if getattr(o, "rigid_body", None) is not None]
    try:
        rigids_u323 = stage.rigid_bodies()
    except Exception as exc:                           # noqa: BLE001
        rigids_u323 = None
        print("WARN stage.rigid_bodies() 失败：%s" % exc)

    mask = plain(stage.stage_mask())
    stored = plain(scene.get("mask_wired"))

    cache_rec = {
        "exists": cache is not None,
        "has_physics": rbw is not None,
        "is_baked": bool(cache.is_baked) if cache is not None else None,
        "is_outdated": bool(cache.is_outdated) if cache is not None else None,
        "info": getattr(cache, "info", None) if cache is not None else None,
        "frame_range": [int(cache.frame_start), int(cache.frame_end)] if cache is not None else None,
    }
    cache_rec["verdict"] = cache_mod.evaluate(dict(cache_rec))

    # 逐刚体（`content_digest_v1` 强摘要的原料）：以前只回读掩码与缓存，强摘要因此算不出来。
    # 任何一个刚体读失败都抛，不用空列表冒充「0 个刚体」。
    bodies, body_errors = [], []
    for o in sorted(rigids_u324, key=lambda x: x.name):
        try:
            bodies.append(pb.digest_body(o))
        except Exception as exc:                       # noqa: BLE001
            body_errors.append({"name": o.name, "error": "%s: %s" % (type(exc).__name__, exc)})

    return {
        "blend": os.path.abspath(blend_path),
        "blend_sha256": sha256_file(blend_path),
        "addon_enabled": addon,
        "rigids_u323_rigid_bodies": len(rigids_u323) if rigids_u323 is not None else None,
        "rigids_u324_rigid_body_attr": len(rigids_u324),
        "bodies": bodies,
        "body_read_errors": body_errors,
        "mask_triple": {
            "verdict": mask.get("verdict"),
            "constraints_capped": mask.get("constraints_capped"),
            "skipped_count": mask.get("skipped_count"),
            "constraints_needed": mask.get("constraints_needed"),
            "constraints_added": mask.get("constraints_added"),
            "constraints_already_blocked": mask.get("constraints_already_blocked"),
            "verdict_reasons": mask.get("verdict_reasons"),
        },
        "mask_report": mask,
        "mask_wired_record": stored,
        "cache": cache_rec,
        "scene_now": {"fps": int(scene.render.fps),
                      "fps_base": round(float(scene.render.fps_base), 6),
                      "frame_start": int(scene.frame_start),
                      "frame_end": int(scene.frame_end)},
        "provenance": module_provenance(),
    }


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out_path = argv[0] if argv else "readback.json"
    blend = bpy.data.filepath
    try:
        rec = collect(blend)
    except BaseException:                              # noqa: BLE001
        traceback.print_exc()
        print("READBACK ERROR")
        return 3
    d = os.path.dirname(os.path.abspath(out_path))
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    t = rec["mask_triple"]
    print("READBACK %s" % out_path)
    print("  rigids u323=%s u324=%s" % (rec["rigids_u323_rigid_bodies"],
                                        rec["rigids_u324_rigid_body_attr"]))
    print("  mask verdict=%r capped=%r skipped=%r needed=%r added=%r already=%r"
          % (t["verdict"], t["constraints_capped"], t["skipped_count"],
             t["constraints_needed"], t["constraints_added"], t["constraints_already_blocked"]))
    print("  verdict_reasons=%r" % (t["verdict_reasons"],))
    print("  cache is_baked=%r is_outdated=%r verdict=%r"
          % (rec["cache"]["is_baked"], rec["cache"]["is_outdated"],
             rec["cache"].get("verdict")))
    print("  blend sha256=%s" % rec["blend_sha256"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
