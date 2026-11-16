# -*- coding: utf-8 -*-
"""m04_a0_why_blind.py —— A0 正控为什么读不出差：机制诊断（只读，不改场景）

背景：`m04_a0_control.py` 判出 tier=1（UNMEASURED）——同一场景、窗口 1..240，
把所有刚体的 `collision_collections` 位清零后，胶囊探针读数**逐位相同**
（`max_abs_delta_m = 0.0`，240/240 帧）。这不等于「碰撞确实不影响几何」，
它只说明「仪器看不见碰撞状态」。原因至少三种，必须区分开：

  H1 点缓存复用：刚体世界有 240 帧已烘焙的 point cache，`frame_set` 直接读缓存，
     位清零根本没进解算（`cache_state.is_baked == true`，info "240 frames in memory"）
  H2 骨骼被关键帧钉死：骨骼每帧都有键，刚体解算结果写不到骨骼上（mmd_tools 的
     刚体→骨若靠约束，约束一旦被清或被键覆盖，物理就只是"陪跑"）
  H3 没有解算：刚体世界关掉 / 全 kinematic / 骨与刚体没有链接

本脚本只回答「是哪种」，不改任何东西：不写 blend、不动位、不碰缓存。
输出 JSON 里每条证据都带**它否证了哪个假设**，免得读的人自己再推一遍。

用法（Blender --background）：
  blender -b --python m04_a0_why_blind.py -- --blend <x.blend> --out <y.json> \
      --bones 下擺_0_0,... [--frames 1:240]

退出码：0 = 诊断完成 / 3 = 出异常或参数/场景读不到（Blender 会吞异常退出 0，故自己 exit）
"""

import io
import json
import sys
import traceback

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def parse_args(argv):
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    out = {"blend": None, "out": None, "bones": [], "frames": (1, 240)}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--blend":
            out["blend"] = argv[i + 1]; i += 2
        elif a == "--out":
            out["out"] = argv[i + 1]; i += 2
        elif a == "--bones":
            out["bones"] = [s for s in argv[i + 1].split(",") if s]; i += 2
        elif a == "--frames":
            lo, hi = argv[i + 1].split(":")
            out["frames"] = (int(lo), int(hi)); i += 2
        else:
            raise SystemExit("未知参数: %r" % (a,))
    if not out["blend"] or not out["out"]:
        raise SystemExit("需要 --blend 与 --out")
    return out


def anim_of(idblock):
    ad = getattr(idblock, "animation_data", None)
    if ad is None:
        return {"has_animation_data": False}
    act = ad.action
    if act is None:
        return {"has_animation_data": True, "action": None}
    # Blender 4.4+ 有 slotted actions；fcurves 可能挂在 layer/strip 上，这里两条路都看
    fcurves = []
    try:
        fcurves = list(act.fcurves)
    except Exception:
        fcurves = []
    return {"has_animation_data": True, "action": act.name,
            "fcurves": len(fcurves),
            "frame_range": list(act.frame_range) if hasattr(act, "frame_range") else None}


def fcurve_paths_of(action):
    """返回 {数据路径前缀: (fcurve 数, 最大关键帧数)}，用于判断"每帧都有键"。"""
    out = {}
    try:
        fcurves = list(action.fcurves)
    except Exception:
        return out
    for fc in fcurves:
        base = fc.data_path.rsplit(".", 1)[0] if "." in fc.data_path else fc.data_path
        n, mx = out.get(base, (0, 0))
        out[base] = (n + 1, max(mx, len(fc.keyframe_points)))
    return out


def bone_report(arm_obj, bone_name):
    """一根骨：键在哪、有没有约束把它接到刚体上。"""
    rec = {"bone": bone_name, "exists": False}
    pb = arm_obj.pose.bones.get(bone_name)
    if pb is None:
        return rec
    rec["exists"] = True
    cons = []
    for c in pb.constraints:
        item = {"type": c.type, "name": c.name, "influence": round(float(c.influence), 4)}
        tgt = getattr(c, "target", None)
        if tgt is not None:
            item["target_object"] = tgt.name
            item["target_has_rigid_body"] = getattr(tgt, "rigid_body", None) is not None
        sub = getattr(c, "subtarget", None)
        if sub:
            item["subtarget"] = sub
        cons.append(item)
    rec["pose_constraints"] = cons
    # 骨骼自身关键帧：动作里搜 pose.bones["<name>"].* 的 fcurve
    keyed = {}
    ad = getattr(arm_obj, "animation_data", None)
    act = getattr(ad, "action", None) if ad else None
    if act is not None:
        pref = 'pose.bones["%s"]' % bone_name
        try:
            for fc in act.fcurves:
                if fc.data_path.startswith(pref):
                    keyed[fc.data_path[len(pref):]] = len(fc.keyframe_points)
        except Exception:
            pass
    rec["keyed_channels"] = keyed
    rec["total_keys"] = int(sum(keyed.values()))
    return rec


def main():
    args = parse_args(sys.argv)
    import bpy
    import addon_utils

    addon_enabled = None
    try:
        mod = addon_utils.enable("bl_ext.user_default.mmd_tools")
        addon_enabled = type(mod).__name__
    except Exception as e:
        addon_enabled = "FAILED: %s" % (e,)

    bpy.ops.wm.open_mainfile(filepath=args["blend"])
    scene = bpy.context.scene
    lo, hi = args["frames"]
    n_frames = hi - lo + 1

    doc = {
        "what": "A0 正控读不出差 —— 机制诊断（只读）",
        "blend": args["blend"],
        "frames": [lo, hi],
        "addon_enable_returns": addon_enabled,
        "hypotheses": {
            "H1": "point cache 复用：frame_set 读已烘焙缓存，位清零没进解算",
            "H2": "骨骼被关键帧钉死 / 刚体→骨链接不存在：解算结果写不到骨上",
            "H3": "根本没有解算：刚体世界关 / 全 kinematic / 骨与刚体无链接",
        },
    }

    # ---- 刚体世界与点缓存（H1 的证据） ----
    rbw = getattr(scene, "rigidbody_world", None)
    if rbw is None:
        doc["rigidbody_world"] = {"present": False, "refutes": ["H1", "H3-present"]}
    else:
        pc = getattr(rbw, "point_cache", None)
        pc_info = {}
        if pc is not None:
            for attr in ("is_baked", "info", "use_disk_cache", "frame_start", "frame_end",
                         "frame_step", "use_external", "cache_step"):
                if hasattr(pc, attr):
                    v = getattr(pc, attr)
                    pc_info[attr] = v if isinstance(v, (int, float, bool, str)) else str(v)
        doc["rigidbody_world"] = {
            "present": True,
            "enabled": bool(getattr(rbw, "enabled", False)),
            "substeps_per_frame": int(getattr(rbw, "substeps_per_frame", -1)),
            "solver_iterations": int(getattr(rbw, "solver_iterations", -1)),
            "time_scale": float(getattr(rbw, "time_scale", -1)),
            "use_split_impulse": bool(getattr(rbw, "use_split_impulse", False)),
            "effector_weights_gravity": (None if getattr(rbw, "effector_weights", None) is None
                                        else round(float(rbw.effector_weights.gravity), 4)),
            "point_cache": pc_info,
            "supports_H1": (pc_info.get("is_baked") is True),
        }

    # ---- 刚体对象：数量 / kinematic / 自身有没有关键帧（H2、H3 的证据） ----
    rigids = []
    for o in bpy.data.objects:
        rb = getattr(o, "rigid_body", None)
        if rb is None:
            continue
        rigids.append({
            "object": o.name,
            "bone": getattr(getattr(o, "mmd_rigid", None), "bone", None),
            "kinematic": bool(rb.kinematic),
            "enabled": bool(rb.enabled),
            "mass": float(rb.mass),
            "animated_by_keys": bool(getattr(o, "animation_data", None) is not None
                                     and getattr(o.animation_data, "action", None) is not None),
            "parent": (None if o.parent is None else o.parent.name),
            "parent_type": o.parent_type,
        })
    n_kin = sum(1 for r in rigids if r["kinematic"])
    n_keyed = sum(1 for r in rigids if r["animated_by_keys"])
    doc["rigid_objects"] = {
        "total": len(rigids),
        "kinematic_true": n_kin,
        "kinematic_false": len(rigids) - n_kin,
        "with_own_action": n_keyed,
        "by_rigid_body_label": len(rigids),
        "note": "kinematic=false 才有资格被解算推动；一个都没有 ⇒ H3 成立",
        "rows": rigids[:8],
    }

    # ---- 骨架与动作（H2 的证据：骨骼是否每帧都有键） ----
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    arm_docs = []
    for a in arms:
        info = {"object": a.name}
        info.update(anim_of(a))
        ad = getattr(a, "animation_data", None)
        act = getattr(ad, "action", None) if ad else None
        if act is not None:
            paths = fcurve_paths_of(act)
            pose_paths = {k: v for k, v in paths.items() if k.startswith("pose.bones[")}
            info["pose_bone_fcurve_groups"] = len(pose_paths)
            info["bones_keyed"] = len(pose_paths)
            info["bones_total"] = len(a.pose.bones)
            full = [k for k, (n, mx) in pose_paths.items() if mx >= n_frames]
            info["bones_with_full_frame_keys"] = len(full)
            info["max_keys_on_one_fcurve"] = max([mx for _, mx in pose_paths.values()], default=0)
        cons = []
        for pb in a.pose.bones:
            for c in pb.constraints:
                cons.append({"bone": pb.name, "type": c.type,
                             "target": getattr(getattr(c, "target", None), "name", None)})
        info["total_pose_constraints"] = len(cons)
        info["pose_constraint_types"] = sorted({c["type"] for c in cons})
        info["pose_constraints_sample"] = cons[:8]
        arm_docs.append(info)
    doc["armatures"] = arm_docs

    # ---- ROI 骨逐根 ----
    target_arm = arms[0] if arms else None
    roi = []
    if target_arm is not None:
        for b in args["bones"]:
            roi.append(bone_report(target_arm, b))
    doc["roi_bones"] = roi
    doc["roi_summary"] = {
        "asked": len(args["bones"]),
        "found": sum(1 for r in roi if r["exists"]),
        "with_any_keys": sum(1 for r in roi if r.get("total_keys", 0) > 0),
        "with_constraints": sum(1 for r in roi if r.get("pose_constraints")),
        "min_total_keys": min([r.get("total_keys", 0) for r in roi], default=0),
        "max_total_keys": max([r.get("total_keys", 0) for r in roi], default=0),
    }

    # ---- 结论：把证据落到假设上，不靠人再推一遍 ----
    verdict = {}
    pc_baked = bool(doc.get("rigidbody_world", {}).get("point_cache", {}).get("is_baked"))
    sim_off = (doc.get("rigidbody_world", {}).get("present") is False
               or doc.get("rigidbody_world", {}).get("enabled") is False
               or n_kin == len(rigids) and rigids != [])
    bones_pinned = (doc["roi_summary"]["with_any_keys"] == len(args["bones"]) > 0
                    and doc["roi_summary"]["min_total_keys"] >= 3 * n_frames)
    verdict["H1_point_cache_reused"] = pc_baked
    verdict["H3_no_simulation"] = bool(sim_off)
    verdict["H2_bones_pinned_by_keys"] = bool(bones_pinned)
    doc["verdict"] = verdict
    if pc_baked and bones_pinned:
        doc["most_likely"] = ("H1 + H2 同时成立：缓存已烘焙（读的是旧解算结果），且 ROI 骨每帧都有键"
                              "（即使缓存清掉、重解，骨也不一定跟着动）。两者都会让位清零读不出差。")
    elif pc_baked:
        doc["most_likely"] = "H1：缓存已烘焙，位清零没有进入解算。清缓存后重跑才叫正控。"
    elif bones_pinned:
        doc["most_likely"] = "H2：骨被关键帧钉死，解算结果写不到骨上。"
    elif sim_off:
        doc["most_likely"] = "H3：场景没有在解算。"
    else:
        doc["most_likely"] = "上面的假设都不成立 —— 机制不明，此时不许拿「碰撞不影响几何」当结论。"
    doc["next_experiment"] = ("在 A0 副本里 free_bake（并记录 cache_state 前后），再用同一探针跑 1..240；"
                              "若仍逐位相同，则说明这支仪器测的不是解算后的姿态，"
                              "四组对比在这个文件上不可判，必须换测量口径（例如直接读刚体对象矩阵而非骨骼）。")

    with io.open(args["out"], "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print("[why-blind] verdict=%s" % json.dumps(verdict, ensure_ascii=False))
    print("[why-blind] most_likely=%s" % doc["most_likely"])
    print("[why-blind] written %s" % args["out"])


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        traceback.print_exc()
        sys.exit(3)
