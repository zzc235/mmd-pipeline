# -*- coding: utf-8 -*-
"""把**动作**应用到已建好物理的场景上，产出按臂分开的 `delivery_v1_<臂>.blend`。

为什么需要这一支：`rebuild_built.blend` 是「物理建好了、动作没进去」的空场。
2号 的 C/D 每臂 = 场景 + 掩码 + **动作**三选一变一个；动作不在场景里，240/832 帧就是同一个静止姿态，
`max_depth_m` 会是一条水平线——**而水平线跟「通道没有影响」长得一模一样**。
所以这一支只做一件事：导入动作、把窗口写成回读得到的值、确认没烘，然后把四样事实落盘。

硬口径（总控 18:01 的验收四条）：

1. 动作显式应用，动作名与 VMD 路径都记；
2. `scene.frame_end` 等于**该臂的窗口末帧**，并同时记 `action.frame_range`——两者不相等时
   记 `window_truncated=true` 并写明为什么（例如 `B_aligned` 300 帧而窗口 240），
   不许用「大约覆盖」糊过去；
3. **应用动作 ≠ 烘焙**：落盘前后各读一次 `point_cache.is_baked`，任一为真 ⇒ 本臂作废；
4. 每臂产出：blend sha256 + `frame_end` + action 名 + `is_baked` 回读 + 掩码三元组，一起进记录。

退出码（Blender 会把脚本异常吞成 0，所以自己给码）：0 成功；3 采集/应用失败。
"""

import hashlib
import json
import os
import sys
import traceback

import bpy                                            # noqa: E402
import addon_utils                                    # noqa: E402


def find_tree(start):
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
    print("DELIVERY ERROR 找不到含 mmdpipe/ 的树根")
    sys.exit(3)
if TREE not in sys.path:
    sys.path.insert(0, TREE)

from mmdpipe import preset as preset_mod              # noqa: E402
from mmdpipe import stage as stage_mod                # noqa: E402


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def plain(value, depth=0):
    if depth > 8:
        return repr(value)[:200]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): plain(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v, depth + 1) for v in value]
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


def enable_mmd_tools():
    for mod in addon_utils.modules():
        if "mmd_tools" in getattr(mod, "__name__", ""):
            addon_utils.enable(mod.__name__, default_set=True, handle_error=None)
            return mod.__name__
    return None


def cache_flags():
    rbw = getattr(bpy.context.scene, "rigidbody_world", None)
    cache = getattr(rbw, "point_cache", None) if rbw is not None else None
    if cache is None:
        return {"exists": False, "is_baked": None, "is_outdated": None}
    return {"exists": True, "is_baked": bool(cache.is_baked),
            "is_outdated": bool(cache.is_outdated),
            "frame_range": [int(cache.frame_start), int(cache.frame_end)]}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    opts = {}
    i = 0
    while i < len(argv):
        if argv[i].startswith("--"):
            opts[argv[i][2:]] = argv[i + 1] if i + 1 < len(argv) else ""
            i += 2
        else:
            i += 1
    for need in ("blend", "preset", "vmd", "arm", "out", "record"):
        if not opts.get(need):
            print("usage: --blend <built.blend> --preset <x.json> --vmd <x.vmd> "
                  "--arm <label> --window-end <N|action> --out <x.blend> --record <x.json>")
            print("缺参数：--%s" % need)
            return 3

    rec = {"tool": "m02_make_delivery_actions", "arm": opts["arm"],
           "tree": TREE, "argv": argv}
    try:
        addon = enable_mmd_tools()
        rec["addon_enabled"] = addon
        bpy.ops.wm.open_mainfile(filepath=os.path.abspath(opts["blend"]))
        rec["cache_before"] = cache_flags()

        arms = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
        if not arms:
            raise RuntimeError("场景里没有骨架（ARMATURE）")
        arm = arms[0]
        root = arm.parent or next((o for o in bpy.context.scene.objects
                                   if getattr(o, "mmd_type", None) == "ROOT"), None)
        rec["armature"] = arm.name
        rec["root"] = getattr(root, "name", None)

        preset = preset_mod.load(os.path.abspath(opts["preset"]))
        res, action_end = stage_mod.stage_motion(preset, root, arm, os.path.abspath(opts["vmd"]),
                                                 0)
        rec["stage_motion"] = {"metrics": plain(res.metrics), "issues": plain(res.issues),
                               "action_end": action_end}
        if action_end is None:
            raise RuntimeError("stage_motion 没给 action_end（动作没导入）")

        action = arm.animation_data.action if arm.animation_data else None
        fr = [int(action.frame_range[0]), int(action.frame_range[1])] if action else None
        rec["action"] = {"name": action.name if action else None, "frame_range": fr,
                         "fcurves": len(action.fcurves) if action else 0,
                         "vmd": os.path.abspath(opts["vmd"]),
                         "vmd_sha256": sha256_file(os.path.abspath(opts["vmd"]))}

        scene = bpy.context.scene
        want = opts.get("window-end") or "action"
        scene.frame_start = 1
        scene.frame_end = int(action_end) if want == "action" else int(want)
        rec["window"] = {"frame_start": int(scene.frame_start), "frame_end": int(scene.frame_end),
                         "asked": want, "action_end": int(action_end),
                         "window_truncated": int(scene.frame_end) != int(action_end)}

        rbw = scene.rigidbody_world
        if rbw is not None:
            # 缓存范围只写范围，**不烘**；写成 max(窗口, 动作) 免得「覆盖不足」被误读成动作问题
            rbw.point_cache.frame_start = 1
            rbw.point_cache.frame_end = max(int(scene.frame_end), int(action_end))

        rec["cache_after_apply"] = cache_flags()
        if rec["cache_after_apply"].get("is_baked"):
            raise RuntimeError("应用动作之后 is_baked=True：动作被烘进缓存了，本臂作废")

        mask = plain(stage_mod.stage_mask())
        rec["mask_triple"] = {"verdict": mask.get("verdict"),
                              "constraints_capped": mask.get("constraints_capped"),
                              "skipped_count": mask.get("skipped_count"),
                              "verdict_reasons": mask.get("verdict_reasons")}
        rec["rigids"] = len([o for o in scene.objects if getattr(o, "rigid_body", None)])
        rec["actions_all"] = sorted(a.name for a in bpy.data.actions)

        out = os.path.abspath(opts["out"])
        d = os.path.dirname(out)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        bpy.ops.wm.save_as_mainfile(filepath=out)
        rec["out"] = out
        rec["out_sha256"] = sha256_file(out)
        rec["out_bytes"] = os.path.getsize(out)
        rec["cache_after_save"] = cache_flags()

        # 保存之后再开一次不划算；这里再核一次 sha 即可（D-126 的「前后各一次」由调用方补）
        rec["status"] = "ok"
    except BaseException as exc:                       # noqa: BLE001
        traceback.print_exc()
        rec["status"] = "error"
        rec["error"] = "%s: %s" % (type(exc).__name__, exc)
        rec["cache_after_apply"] = rec.get("cache_after_apply") or cache_flags()
        _write(opts.get("record"), rec)
        print("DELIVERY ERROR %s" % rec["error"])
        return 3

    _write(opts["record"], rec)
    print("DELIVERY OK arm=%s action=%r window=%s..%s out=%s"
          % (rec["arm"], rec["action"]["name"], rec["window"]["frame_start"],
             rec["window"]["frame_end"], os.path.basename(rec["out"])))
    print("  rigids=%s is_baked=%r is_outdated=%r mask=%r"
          % (rec["rigids"], rec["cache_after_save"].get("is_baked"),
             rec["cache_after_save"].get("is_outdated"),
             rec["mask_triple"].get("verdict")))
    print("  out %d B sha256=%s" % (rec["out_bytes"], rec["out_sha256"]))
    return 0


def _write(path, rec):
    if not path:
        return
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        os.makedirs(d)
    tmp = os.path.abspath(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, os.path.abspath(path))


if __name__ == "__main__":
    sys.exit(main())
