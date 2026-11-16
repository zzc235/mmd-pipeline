"""324 交付件的烘焙调用点（`D-207`）：**动作应用之后**才烘，烘完自带闸门与独立计数。

为什么不在 `stage_build` 里烘
------------------------------
`runner.py` 是 627 `stage_import` → 635 `stage_build` → 661 `stage_motion`，动作在 build **之后**
才应用。在 build 里烘 = 烘**静止姿态**；而探针比的是「烘进去的姿态」与「顺序重算的姿态」——
两个静止姿态必然一致 ⇒ `applied / not_outdated / probe_matched` 全绿。这是今天最像成功的
fail-open（`D-207`），所以本脚本**拒跑没有动作的件**（`BAKE_NO_ACTION`），不靠「看一眼是不是绿的」。

口径（全部回读，不假定）
------------------------
- `frame_start` = 1；
- `frame_end`   = `int(round(action.frame_range[1]))` —— 动作回读末端，**不是**导入后的场景值
  （D 臂 = 833，导入后场景值 250 是错的）；
- `fps`         = `scene.render.fps` 回读，并与预设 fps 对齐（不等 ⇒ `BAKE_FPS_MISMATCH`）；
- 判红（`stage.bake_gate_reason` 非空）⇒ **不出件**（不写 blend），报 `reason_code` 退出。

独立计数（总控 `D-206`/`D-207③`：`added=8298` 是掩码自己的账，不算「场景里到底有多少个约束对象」）
------------------------------------------------------------------------------------------
烘前/烘后各量一次 `type == 'RIGID_BODY_CONSTRAINT'` 的对象数，并按 `disable_collisions` 分开
（`True` = 掩码/`buildRigids` 挡碰撞的，`False` = 其它）。期望值写成 `expect`、实际值单列，
对不上就报 `reason`，不把两个来源拼成一句话。

用法
----
    blender -b --python m02_bake_delivery.py -- \
        --in-blend D.blend --out-blend out/delivery_baked.blend \
        --report out/bake_report.json --run-id run_x [--expect-fps 24] [--built-report r.json]
"""

import hashlib
import json
import os
import sys

import bpy

# GBK 控制台下中文/符号会让脚本崩在打印上（总控 18:18）：入口统一 UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_TREE = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
for _p in (_TREE, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from mmdpipe import stage  # noqa: E402

MMD_CANDIDATES = ("bl_ext.user_default.mmd_tools", "mmd_tools")

OK = 0
BAKE_NO_ACTION = 6
BAKE_FRAME_END_MISMATCH = 7
BAKE_GATE_RED = 8
BAKE_FPS_MISMATCH = 9
BAKE_PROBE_UNINFORMATIVE = 10

MIN_FCURVES = 100          # 与 3号 的 `A1_action_applied` 同一道门槛（725/700 都远大于它）


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def enable_mmd_tools():
    import addon_utils
    trace = []
    for name in MMD_CANDIDATES:
        try:
            addon_utils.enable(name, default_set=False, persistent=False)
            trace.append({"name": name, "error": None})
        except Exception as exc:  # noqa: BLE001
            trace.append({"name": name, "error": "%s: %s" % (type(exc).__name__, exc)})
    # `hasattr` 在没装上时也返回 True（3号 的 A0 实测），所以只认 `preferences.addons`
    enabled = [n for n in MMD_CANDIDATES
               if n in {a.module for a in bpy.context.preferences.addons}]
    return bool(enabled), {"trace": trace, "enabled": enabled}


def argv_after_dashes():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def opt(argv, name, default=None):
    if name in argv:
        idx = argv.index(name)
        if idx + 1 < len(argv):
            return argv[idx + 1]
    return default


def constraint_census():
    """场景里到底有多少个刚体约束对象 —— 独立数，不是掩码的账。"""
    total = 0
    disable_true = 0
    disable_false = 0
    types = {}
    for obj in bpy.data.objects:
        if obj.type != "RIGID_BODY_CONSTRAINT":
            continue
        total += 1
        rbc = getattr(obj, "rigid_body_constraint", None)
        kind = getattr(rbc, "type", None)
        types[kind] = types.get(kind, 0) + 1
        if rbc is not None and getattr(rbc, "disable_collisions", False):
            disable_true += 1
        else:
            disable_false += 1
    scene_scoped = sum(1 for obj in bpy.context.scene.objects
                       if obj.type == "RIGID_BODY_CONSTRAINT")
    return {"total": total, "in_scene": scene_scoped,
            "disable_collisions_true": disable_true,
            "disable_collisions_false": disable_false,
            "by_type": types}


def action_readback():
    """动作回读。动作在哪个骨架就报哪个骨架，不猜。"""
    found = None
    for obj in bpy.data.objects:
        if obj.type != "ARMATURE":
            continue
        ad = getattr(obj, "animation_data", None)
        act = getattr(ad, "action", None) if ad is not None else None
        if act is None:
            continue
        found = (obj, ad, act)
        break
    if found is None:
        return {"armature": None, "action": None}
    obj, ad, act = found
    rng = list(getattr(act, "frame_range", []) or [])
    return {
        "armature": obj.name,
        "action": {
            "name": act.name,
            "fcurves": len(getattr(act, "fcurves", []) or []),
            "frame_range": [None if v is None else round(float(v), 6) for v in rng],
            "users": int(getattr(act, "users", 0) or 0),
            "slots": len(getattr(act, "slots", []) or []) if hasattr(act, "slots") else None,
        },
        "nla_tracks": len(getattr(ad, "nla_tracks", []) or []),
    }


def cache_readback():
    scene = bpy.context.scene
    rbw = getattr(scene, "rigidbody_world", None)
    if rbw is None:
        return {"has_rigidbody_world": False}
    cache = rbw.point_cache
    return {"has_rigidbody_world": True,
            "is_baked": bool(getattr(cache, "is_baked", False)),
            "is_outdated": bool(getattr(cache, "is_outdated", True)),
            "frame_start": int(getattr(cache, "frame_start", 0)),
            "frame_end": int(getattr(cache, "frame_end", 0)),
            "use_disk_cache": bool(getattr(cache, "use_disk_cache", False))}


def reference_moved(frames):
    """采样帧之间刚体姿态有没有真的不同 —— 探针的**区分力**。

    静态件上 `matched=true / max_delta=0.0` 只证明「两次读到同一个值」，不证明缓存忠实
    （4号 18:56 在无动作件上实测撞到的形状）。4号 已把它做成 `bake_checks()` 的
    `probe_informative`；我这条是同一判据在**调用点**的独立复算，因为 `stage.py` 的那条
    还没并进我这棵树。两次都留，谁先并都红。
    """
    seen = {}
    for frame in frames:
        bpy.context.scene.frame_set(int(frame))
        snap = stage.pose_snapshot(stage.rigid_bodies())
        key = json.dumps({k: [round(float(v), 9) for v in vals]
                          for k, vals in sorted(snap.items())}, sort_keys=True)
        seen[key] = [frame]
    return {"frames": list(frames), "distinct": len(seen),
            "moved": len(seen) > 1}


def main():
    argv = argv_after_dashes()
    in_blend = opt(argv, "--in-blend")
    out_blend = opt(argv, "--out-blend")
    report_path = opt(argv, "--report")
    run_id = opt(argv, "--run-id")
    expect_fps = int(opt(argv, "--expect-fps", "24"))
    built_report = opt(argv, "--built-report")
    if not in_blend or not report_path:
        raise SystemExit("必给 --in-blend 与 --report")

    report = {
        "stage": "bake-delivery-v1",
        "run_id": run_id,
        "input": {"path": os.path.abspath(in_blend), "sha256": sha256_file(in_blend),
                  "bytes": os.path.getsize(in_blend)},
        "expect_fps": expect_fps,
        "baked_by": {"stage_py": sha256_file(stage.__file__),
                     "script_sha256": sha256_file(os.path.abspath(__file__))},
    }
    if built_report and os.path.exists(built_report):
        try:
            with open(built_report, encoding="utf-8") as fh:
                rep = json.load(fh)
            report["built_by"] = {
                "report": os.path.abspath(built_report),
                "report_sha256": sha256_file(built_report),
                "stage_py": (rep.get("provenance") or {}).get("stage_py")
                or (rep.get("provenance") or {}).get("stage_sha256"),
                "v3_script": (rep.get("provenance") or {}).get("v3_script"),
            }
        except Exception as exc:  # noqa: BLE001
            report["built_by"] = {"error": "%s: %s" % (type(exc).__name__, exc)}

    bpy.ops.wm.open_mainfile(filepath=os.path.abspath(in_blend))
    addon_ok, addon = enable_mmd_tools()
    report["addon"] = {"ok": addon_ok, **addon}

    scene = bpy.context.scene
    report["scene"] = {"fps": int(scene.render.fps), "fps_base": round(float(scene.render.fps_base), 6),
                       "frame_start": int(scene.frame_start), "frame_end": int(scene.frame_end)}
    report["rigids"] = {"all": len(stage.rigid_bodies()),
                        "scope": len(stage.collision_scope())}
    report["constraints_before"] = constraint_census()
    report["cache_before"] = cache_readback()

    act = action_readback()
    report["animation"] = act
    action = act.get("action")
    if not action:
        report["status"] = "REFUSED"
        report["reason_code"] = "BAKE_NO_ACTION"
        report["reason"] = ("件里没有 action：烘的是静止姿态，探针必绿（D-207）。"
                            "不烘、不出件。")
        return finish(report, report_path, BAKE_NO_ACTION)
    if action["fcurves"] < MIN_FCURVES:
        report["status"] = "REFUSED"
        report["reason_code"] = "BAKE_NO_ACTION"
        report["reason"] = ("action 只有 %d 条 fcurves（门槛 %d）—— 等于没有能动的姿态。"
                            % (action["fcurves"], MIN_FCURVES))
        return finish(report, report_path, BAKE_NO_ACTION)

    if int(scene.render.fps) != expect_fps:
        report["status"] = "REFUSED"
        report["reason_code"] = "BAKE_FPS_MISMATCH"
        report["reason"] = "scene fps=%d ≠ 预设 %d（跨 dt 的读数不可比，D-192）" % (
            int(scene.render.fps), expect_fps)
        return finish(report, report_path, BAKE_FPS_MISMATCH)

    fe = int(round(float(action["frame_range"][1])))
    report["bake_request"] = {"frame_start": 1, "frame_end": fe,
                              "fps": int(scene.render.fps),
                              "frame_end_source": "readback:action.frame_range[1]"}
    if int(scene.frame_end) != fe:
        report["status"] = "REFUSED"
        report["reason_code"] = "BAKE_FRAME_END_MISMATCH"
        report["reason"] = ("scene.frame_end=%d ≠ 动作回读末端 %d：场景窗口没跟动作对齐，"
                            "烘进去的会是另一段。" % (int(scene.frame_end), fe))
        return finish(report, report_path, BAKE_FRAME_END_MISMATCH)

    # 探针区分力：采样帧之间的刚体姿态必须真的不同，否则烘完的 `matched` 是空证据
    info = reference_moved([1, max(1, fe // 2), fe])
    report["probe_informative"] = info
    if not info["moved"]:
        report["status"] = "REFUSED"
        report["reason_code"] = "BAKE_PROBE_UNINFORMATIVE"
        report["reason"] = ("采样帧 1/%d/%d 上刚体姿态逐位相同 ⇒ 探针无区分力，"
                            "烘完的 matched 只证明「两次读到同一个值」。" % (fe // 2, fe))
        return finish(report, report_path, BAKE_PROBE_UNINFORMATIVE)

    record = stage.stage_bake(scene, report["bake_request"])
    report["bake"] = record
    report["constraints_after"] = constraint_census()
    report["cache_after"] = cache_readback()
    reason = stage.bake_gate_reason(record)
    report["bake_gate"] = {"reason": reason, "checks": stage.bake_checks(record),
                           "missing": stage.bake_missing(record)}
    if reason is not None:
        report["status"] = "BLOCKED"
        report["reason_code"] = "BAKE_GATE_RED"
        report["reason"] = reason
        return finish(report, report_path, BAKE_GATE_RED)     # 判红不出件

    if out_blend:
        os.makedirs(os.path.dirname(os.path.abspath(out_blend)), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(out_blend), copy=True)
        report["output"] = {"path": os.path.abspath(out_blend),
                            "bytes": os.path.getsize(out_blend),
                            "sha256": sha256_file(out_blend)}
        # 存完再回读一次缓存状态：读者不用打开就知这件烘没烘
        bpy.ops.wm.open_mainfile(filepath=os.path.abspath(out_blend))
        enable_mmd_tools()
        report["output"]["cache_readback"] = cache_readback()
        report["output"]["frame_end_readback"] = int(bpy.context.scene.frame_end)
    report["status"] = "BAKED"
    return finish(report, report_path, OK)


def finish(report, report_path, code):
    os.makedirs(os.path.dirname(os.path.abspath(report_path)), exist_ok=True)
    with open(report_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("BAKE status=%s rc=%d reason_code=%s action=%s frame_end=%s"
          % (report.get("status"), code, report.get("reason_code"),
             (report.get("animation") or {}).get("action", {}).get("name")
             if isinstance((report.get("animation") or {}).get("action"), dict) else None,
             ((report.get("bake") or {}).get("frame_end"))))
    sys.stdout.flush()
    os._exit(code)


if __name__ == "__main__":
    main()
