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
BAKE_EXCEPTION = 11
BAKE_RIGIDS_MISMATCH = 12
BAKE_MASK_MISMATCH = 13

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
    """场景里到底有多少个**刚体约束** —— 独立数，不是掩码的账。

    实测踩到的坑：`obj.type == 'RIGID_BODY_CONSTRAINT'` 在 Blender 5.2 里**永远数到 0**，
    因为对象类型枚举里没有这一项（约束是挂在 Empty 上的 `obj.rigid_body_constraint`）。
    按类型名数会得到「0 个约束」这种假装量过的读数，所以这里两条口径都量：
    ①属性口径：`rigid_body_constraint is not None`；②世界口径：`rigidbody_world.constraints`。
    """
    total = 0
    disable_true = 0
    disable_false = 0
    types = {}
    for obj in bpy.data.objects:
        rbc = getattr(obj, "rigid_body_constraint", None)
        if rbc is None:
            continue
        total += 1
        kind = getattr(rbc, "type", None)
        types[kind] = types.get(kind, 0) + 1
        if getattr(rbc, "disable_collisions", False):
            disable_true += 1
        else:
            disable_false += 1
    scene = bpy.context.scene
    rbw = getattr(scene, "rigidbody_world", None)
    world, world_err = None, None
    if rbw is not None:
        try:
            world = len(list(getattr(rbw, "constraints", [])))
        except Exception as exc:  # noqa: BLE001  实测 `RigidBodyWorld.constraints` 不是可 len 的序列
            world_err = "%s: %s" % (type(exc).__name__, exc)
    scoped = sum(1 for obj in scene.objects
                 if getattr(obj, "rigid_body_constraint", None) is not None)
    return {"total": total, "in_scene": scoped, "rigidbody_world_constraints": world,
            "rigidbody_world_constraints_error": world_err,
            "disable_collisions_true": disable_true,
            "disable_collisions_false": disable_false,
            "by_type": types,
            "type_enum_hit": sum(1 for o in bpy.data.objects
                                 if o.type == "RIGID_BODY_CONSTRAINT")}


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


def main():
    argv = argv_after_dashes()
    in_blend = opt(argv, "--in-blend")
    out_blend = opt(argv, "--out-blend")
    report_path = opt(argv, "--report")
    run_id = opt(argv, "--run-id")
    expect_fps = int(opt(argv, "--expect-fps", "24"))
    built_report = opt(argv, "--built-report")
    expect_readback = opt(argv, "--expect-readback")
    build_identity = opt(argv, "--build-identity")
    disk_cache = "--disk-cache" in argv
    if not in_blend or not report_path:
        raise SystemExit("必给 --in-blend 与 --report")
    if not expect_readback:
        raise SystemExit("必给 --expect-readback：烘前五项里的刚体数/掩码四条要跟冻结回读对账，"
                         "期望值不写死（总控 18:59）")

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
                # `rebuild_report.json` 里**没有** `provenance` 键（`v3` 只写了 `addon_trace` 等），
                # 所以建件的 `stage.py` 只能从 identity 件拿 —— 19:14 那次 `stage_py=null` 就是这么来的。
                "stage_py": (rep.get("provenance") or {}).get("stage_py")
                or (rep.get("provenance") or {}).get("stage_sha256"),
                "v3_script": (rep.get("provenance") or {}).get("v3_script"),
            }
            if not report["built_by"]["stage_py"]:
                report["built_by"]["stage_py_source"] = ("rebuild_report 无 provenance；"
                                                         "请用 --build-identity 指 identity 件")
        except Exception as exc:  # noqa: BLE001
            report["built_by"] = {"error": "%s: %s" % (type(exc).__name__, exc)}
    if build_identity and os.path.exists(build_identity):
        try:
            with open(build_identity, encoding="utf-8") as fh:
                ident = json.load(fh)
            # identity 件的实际形状（`build_identity_20261116_184302.json`）：`stage_sha256`
            # 在**顶层**、没有 `provenance` 键；两种都认，别再猜一种。
            stage_py = ((ident.get("provenance") or {}).get("stage_py")
                        or ident.get("stage_sha256") or ident.get("stage_py"))
            report.setdefault("built_by", {})
            report["built_by"].update({
                "identity": os.path.abspath(build_identity),
                "identity_sha256": sha256_file(build_identity),
                "stage_py": stage_py or report["built_by"].get("stage_py"),
                "stage_py_source": "identity.provenance.stage_py",
            })
        except Exception as exc:  # noqa: BLE001
            report.setdefault("built_by", {})
            report["built_by"]["identity_error"] = "%s: %s" % (type(exc).__name__, exc)
        except Exception as exc:  # noqa: BLE001
            report["built_by"] = {"error": "%s: %s" % (type(exc).__name__, exc)}

    bpy.ops.wm.open_mainfile(filepath=os.path.abspath(in_blend))
    addon_ok, addon = enable_mmd_tools()
    report["addon"] = {"ok": addon_ok, **addon}

    scene = bpy.context.scene
    report["scene"] = {"fps": int(scene.render.fps), "fps_base": round(float(scene.render.fps_base), 6),
                       "frame_start": int(scene.frame_start), "frame_end": int(scene.frame_end)}
    report["rigids"] = {
        # `stage.rigid_bodies()` = `mmd_type == 'RIGID_BODY'`（= U323）；`collision_scope()`
        # 返回的是 **(inside, outside) 二元组**，直接 len 会数成 2 —— 实测踩过。
        "u323": len(stage.rigid_bodies()),
        "u324": sum(1 for o in bpy.data.objects if getattr(o, "rigid_body", None) is not None),
        "scope_inside": len(stage.collision_scope()[0]),
        "scope_outside": [o.name for o in stage.collision_scope()[1]],
    }
    report["constraints_before"] = constraint_census()
    report["cache_before"] = cache_readback()

    # 总控 18:59 的烘前五项之 4/5：刚体数、掩码四条 —— 期望值**从冻结回读读**，不写死
    # （833 都不许写死，323/324/8298 同理）。冻结件是只读的，读它跟读 D 臂等价，
    # 而且这条链上每一步都有 sha。
    if expect_readback and os.path.exists(expect_readback):
        with open(expect_readback, encoding="utf-8") as fh:
            exp = json.load(fh)
        triple = exp.get("mask_triple") or {}
        expect = {"u323": exp.get("rigids_u323_rigid_bodies"),
                  "u324": exp.get("rigids_u324_rigid_body_attr"),
                  "mask_verdict": triple.get("verdict"),
                  "constraints_needed": triple.get("constraints_needed"),
                  "constraints_added": triple.get("constraints_added"),
                  "capped": triple.get("constraints_capped"),
                  "skipped": triple.get("skipped_count"),
                  "readback_mismatch": triple.get("readback_mismatch")}
        report["expect_from"] = {"path": os.path.abspath(expect_readback),
                                 "sha256": sha256_file(expect_readback), **expect}
        got = {"u323": report["rigids"]["u323"], "u324": report["rigids"]["u324"]}
        report["rigids_check"] = {"expect": {"u323": expect["u323"], "u324": expect["u324"]},
                                  "got": got,
                                  "ok": got["u323"] == expect["u323"] and got["u324"] == expect["u324"]}
        # 掩码装上的约束还在不在：`disable_collisions=True` 的对象数必须覆盖掩码的 `constraints_added`
        con = report["constraints_before"]
        report["mask_check"] = {
            "frozen_verdict": expect["mask_verdict"],
            "frozen_identity": (None if None in (expect["constraints_needed"], expect["constraints_added"])
                                else expect["constraints_added"] + con.get("disable_collisions_true", 0)),
            "frozen_constraints_added": expect["constraints_added"],
            "scene_disable_collisions_true": con["disable_collisions_true"],
            "covered": (expect["constraints_added"] is not None
                        and con["disable_collisions_true"] >= expect["constraints_added"]),
            "frozen_capped": expect["capped"], "frozen_skipped": expect["skipped"],
            "frozen_readback_mismatch": expect["readback_mismatch"],
        }
        if not report["rigids_check"]["ok"]:
            report["status"] = "REFUSED"
            report["reason_code"] = "BAKE_RIGIDS_MISMATCH"
            report["reason"] = ("D 臂刚体数与冻结回读不一致：期望 u323=%s/u324=%s，实测 %s/%s"
                                "（动作那一步增删了刚体？）"
                                % (expect["u323"], expect["u324"], got["u323"], got["u324"]))
            return finish(report, report_path, BAKE_RIGIDS_MISMATCH)
        if expect["mask_verdict"] != "WIRED" or not report["mask_check"]["covered"]:
            report["status"] = "REFUSED"
            report["reason_code"] = "BAKE_MASK_MISMATCH"
            report["reason"] = ("掩码在 D 臂上不成立：冻结判词 %s、掩码装上 %s 条，"
                                "场景里 `disable_collisions=True` 只有 %d 个（动作那一步弄坏了掩码？）"
                                % (expect["mask_verdict"], expect["constraints_added"],
                                   report["constraints_before"]["disable_collisions_true"]))
            return finish(report, report_path, BAKE_MASK_MISMATCH)
    else:
        report["expect_from"] = None
        report["rigids_check"] = {"ok": None, "reason": "没给 --expect-readback：刚体/掩码两项无从对账"}

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
    # `stage.bake_request()` 只认三个键（实测：多给一个 `frame_end_source` 就 ValueError），
    # 所以来源说明放在请求**外面**，请求本身保持最小形状。
    report["bake_request"] = {"frame_start": 1, "frame_end": fe,
                              "fps": int(scene.render.fps)}
    report["bake_request_note"] = {
        "frame_end": "readback:action.frame_range[1]（不是导入后的场景值）",
        "fps": "readback:scene.render.fps",
    }
    if int(scene.frame_end) != fe:
        report["status"] = "REFUSED"
        report["reason_code"] = "BAKE_FRAME_END_MISMATCH"
        report["reason"] = ("scene.frame_end=%d ≠ 动作回读末端 %d：场景窗口没跟动作对齐，"
                            "烘进去的会是另一段。" % (int(scene.frame_end), fe))
        return finish(report, report_path, BAKE_FRAME_END_MISMATCH)

    # 探针区分力现在由 `stage.bake_checks()` 的 `probe_informative` 判（main `f1e6047` 已并入）：
    # 同一判据只留一份实现（`D-186`），我那份本地复算在 19:02 那次烘之后就删了。
    if "probe_informative" not in stage.bake_checks({}):
        report["probe_informative_source"] = "stage.bake_checks() 里没有这条判据"
    if disk_cache:
        # 内存缓存**不随 .blend 落盘**（19:02 那次实测：存完重开 `is_baked=true / is_outdated=true`，
        # `use_disk_cache=false`）。要交一件「烘过的件」，缓存必须写盘、并在件里指向它。
        cache_dir = os.path.join(os.path.dirname(os.path.abspath(out_blend or report_path)),
                                 "blendcache")
        os.makedirs(cache_dir, exist_ok=True)
        pc = scene.rigidbody_world.point_cache
        pc.use_disk_cache = True
        pc.directory = cache_dir
        report["disk_cache"] = {"requested": True, "directory_abs": cache_dir,
                                "directory_in_blend": "//blendcache"}

    record = stage.stage_bake(scene, report["bake_request"])
    report["bake"] = record
    report["constraints_after"] = constraint_census()
    report["cache_after"] = cache_readback()
    # 烘不许增删约束对象：前后不一致说明这不是「同一条边界条件下的烘」
    before = report["constraints_before"]
    after = report["constraints_after"]
    report["constraints_stable"] = {
        "total": (before["total"], after["total"]),
        "disable_collisions_true": (before["disable_collisions_true"],
                                    after["disable_collisions_true"]),
        "ok": before["total"] == after["total"]
        and before["disable_collisions_true"] == after["disable_collisions_true"],
    }
    reason = stage.bake_gate_reason(record)
    report["bake_gate"] = {"reason": reason, "checks": stage.bake_checks(record),
                           "missing": stage.bake_missing(record)}
    if reason is not None:
        report["status"] = "BLOCKED"
        report["reason_code"] = "BAKE_GATE_RED"
        report["reason"] = reason
        return finish(report, report_path, BAKE_GATE_RED)     # 判红不出件
    if not report["constraints_stable"]["ok"]:
        report["status"] = "BLOCKED"
        report["reason_code"] = "BAKE_CONSTRAINTS_CHANGED"
        report["reason"] = ("烘前/烘后约束对象数不一致：total %s→%s，disable_collisions %s→%s"
                            % (before["total"], after["total"],
                               before["disable_collisions_true"],
                               after["disable_collisions_true"]))
        return finish(report, report_path, BAKE_GATE_RED)

    if out_blend:
        os.makedirs(os.path.dirname(os.path.abspath(out_blend)), exist_ok=True)
        if disk_cache:
            # 存件前把路径改成相对（`//blendcache`）：绝对路径换个盘就失效，
            # 而 `//` 在**读取时**才解析，落盘时刻不会往别人目录里写。
            scene.rigidbody_world.point_cache.directory = "//blendcache"
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
    try:
        main()
    except SystemExit:
        raise
    except BaseException as exc:                       # noqa: BLE001
        # Blender 5.2.2 把 `-P` 脚本的异常吞掉照样 exit 0（D-135，实测过多次）：
        # 所以这里自己收尾，落一份 ERROR 报告并给非零退出码，别让「崩了」和「跑完了」长得一样。
        import traceback
        traceback.print_exc()
        _rep = opt(argv_after_dashes(), "--report")
        if _rep:
            try:
                os.makedirs(os.path.dirname(os.path.abspath(_rep)), exist_ok=True)
                with open(_rep, "w", encoding="utf-8", newline="\n") as fh:
                    json.dump({"stage": "bake-delivery-v1", "status": "ERROR",
                               "reason_code": "BAKE_EXCEPTION",
                               "error": "%s: %s" % (type(exc).__name__, exc)},
                              fh, ensure_ascii=False, indent=1, sort_keys=True)
                    fh.write("\n")
            except Exception:                          # noqa: BLE001
                pass
        sys.stdout.flush()
        os._exit(BAKE_EXCEPTION)
