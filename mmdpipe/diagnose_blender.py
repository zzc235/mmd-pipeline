"""Blender 侧只读证据采集器（M03 · 归因判据）。

它只做一件事：把 `.blend` 里「判据需要、但 PMX 层看不到」的运行期状态采出来，
交给 `mmdpipe.diagnose` 的同一套判据函数。判定逻辑不在这里重复。

    & "E:\\code\\Blender\\blender-5.2.2-windows-x64\\blender.exe" -b ^
        -P "mmdpipe\\diagnose_blender.py" -- ^
        --blend "场景.blend" --out "diagnosis.json" --frames 60

可选 `--pmx` 把静态结构证据一并合进来（有了它 F3 才可能 confirmed）。

采集项
------
* mmd_root.is_built、骨骼上的 COPY_ROTATION / COPY_TRANSFORMS 计数
* 刚体数、rigid_body.collision_collections 分布（S8「掩码改到 Blender 不读的层」）
* rigidbody_world.substeps_per_frame / solver_iterations / point_cache 状态与范围
* 动态：从 f1 连续步进到 fN，逐帧记「目标骨相对父链的旋转增量」与「父链世界旋转增量」
  —— F3 要的正是这种「父链在动、目标不动」的对照

安全
----
* 打开后立刻算 SHA256，全程不 save；结束再算一次，变了就报警
* 不调用 read_factory_settings，不使用 ptcache.bake_all（312 刚体会段错误）
* 写完 JSON 后 os._exit，绕开既有的刚性体析构段错误（报告里会写明）

退出码
------
    0  报告已写盘（status=ok）
    3  .blend 打不开 / 参数错误
    4  报告已写盘，但 status=partial（没有 rigidbody_world、没有动态帧等）
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys

import bpy

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from mmdpipe import diagnose  # noqa: E402  （纯 Python，不 import bpy）

EXIT_OK = 0
EXIT_INPUT = 3
EXIT_PARTIAL = 4

_CONSTRAINT_TYPES = ("COPY_ROTATION", "COPY_TRANSFORMS")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_args(argv: list[str] | None = None) -> dict:
    argv = list(sys.argv if argv is None else argv)
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    opts = {"blend": None, "out": None, "frames": 60, "pmx": None,
            "watch_bones": None, "experiment_id": None, "config": None}
    i = 0
    while i < len(argv):
        key = argv[i].lstrip("-").replace("-", "_")
        if key in ("blend", "out", "pmx", "watch_bones", "experiment_id", "config"):
            if i + 1 >= len(argv):
                raise SystemExit("参数 %s 缺值" % argv[i])
            opts[key] = argv[i + 1]
            i += 2
        elif key == "frames":
            opts["frames"] = int(argv[i + 1])
            i += 2
        else:
            raise SystemExit("未知参数 %s" % argv[i])
    if not opts["blend"] or not opts["out"]:
        raise SystemExit("用法: diagnose_blender.py -- --blend 场景.blend --out 诊断.json "
                         "[--frames 60] [--pmx 模型.pmx]")
    return opts


def _find_root():
    """场景里可能同时有角色和道具（刀/枪）各带一个 ROOT。

    按「骨骼最多」挑主模型，而不是 `bpy.data.objects` 的第一个 ——
    否则会拿到 `刀_arm`（1 根骨）去判整个角色的物理。
    """
    roots = [o for o in bpy.data.objects if getattr(o, "mmd_type", None) == "ROOT"]
    if not roots:
        return None

    def bones_of(root):
        arm = bpy.data.objects.get(root.name + "_arm")
        if arm is not None and arm.type == "ARMATURE":
            return len(arm.data.bones)
        return 0

    return max(roots, key=lambda o: bones_of(o))


def _find_arm(root):
    if root is not None:
        cand = bpy.data.objects.get(root.name + "_arm")
        if cand is not None and cand.type == "ARMATURE":
            return cand
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    return max(arms, key=lambda o: len(o.data.bones)) if arms else None


def _constraint_hist(arm) -> tuple[dict, list]:
    hist: dict = {}
    bones = []
    for pbone in arm.pose.bones:
        for con in pbone.constraints:
            hist[con.type] = hist.get(con.type, 0) + 1
            if con.type in _CONSTRAINT_TYPES:
                bones.append({
                    "bone": pbone.name,
                    "type": con.type,
                    "mute": bool(con.mute),
                    "target": getattr(getattr(con, "target", None), "name", None),
                    "subtarget": getattr(con, "subtarget", None),
                })
    return hist, bones


def _collision_census(rigids: list) -> dict:
    """S8 证据：mmd_rigid.collision_group_mask 有没有落到 Blender 的碰撞集合。"""
    sets: dict = {}
    empty = 0
    for obj in rigids:
        rb = getattr(obj, "rigid_body", None)
        if rb is None:
            continue
        cols = tuple(i for i, on in enumerate(rb.collision_collections) if on)
        if not cols:
            empty += 1
        sets[cols] = sets.get(cols, 0) + 1
    return {
        "rigids": len(rigids),
        "distinct_collection_sets": len(sets),
        "top_sets": [{"collections": list(k), "count": v}
                     for k, v in sorted(sets.items(), key=lambda kv: -kv[1])[:5]],
        "rigids_with_no_collection": empty,
        "note": "全部 rigids 只有 (0,) 时，改 MMD 掩码不会改变 Blender 层碰撞",
    }


def _world_quat(arm_world, pb):
    if pb is None:
        return None
    return (arm_world @ pb.matrix).to_quaternion()


def _angle_deg(q1, q2) -> float:
    """两个四元数之间的最小旋转角（度）。

    `rotation_difference().angle` 受四元数双覆盖影响会落在 [0, 2π]，
    直接度化会把「几乎没动」报成 357°。超过 π 的取补角。
    """
    if q1 is None or q2 is None:
        return 0.0
    ang = q1.rotation_difference(q2).angle
    if ang > math.pi:
        ang = 2.0 * math.pi - ang
    return math.degrees(ang)


def _pmx_targets(pmx_path: str, opts: dict) -> dict:
    """用 PMX 静态结论决定要看哪些骨：冻结根的目标骨 + 宽限位单元的骨。"""
    config = diagnose.default_config()
    if opts.get("config"):
        diagnose.merge_evidence(config, diagnose.load_json(opts["config"]))
    evidence = diagnose.collect_pmx(pmx_path, config)
    roots = evidence["structure"]["frozen_roots"]
    target_bones = sorted({r["target_bone"] for r in roots if r["target_bone"]})

    import mmdpipe.physics as physics_mod
    import mmdpipe.pmx as pmx_mod
    model = pmx_mod.load(pmx_path)
    rep = physics_mod.classify(model)
    bodies_of_uid = {unit.uid: list(unit.bodies) for unit in rep.units}
    unit_bones: dict[int, list] = {}
    for unit in evidence["structure"]["wide_limit_units"]:
        uid = unit["uid"]
        names = []
        for body in bodies_of_uid.get(uid, []):
            if 0 <= body < len(model.rigids):
                bone_idx = model.rigids[body].bone
                if 0 <= bone_idx < len(model.bones):
                    names.append(model.bones[bone_idx].name)
        unit_bones[uid] = names
    return {
        "config": config,
        "evidence": evidence,
        "frozen_bones": target_bones,
        "unit_bones": unit_bones,
        "model": model,
    }


def _watch_names(arm, frozen_bones: list, unit_bones: dict, limit: int = 400) -> list:
    names = []
    seen = set()
    for n in frozen_bones:
        if n and n not in seen and arm.pose.bones.get(n):
            seen.add(n)
            names.append(n)
    for uid in sorted(unit_bones):
        for n in unit_bones[uid]:
            if n and n not in seen and arm.pose.bones.get(n):
                seen.add(n)
                names.append(n)
    if not names:
        hist, bones = _constraint_hist(arm)
        for entry in bones:
            if entry["bone"] not in seen:
                seen.add(entry["bone"])
                names.append(entry["bone"])
    return names[:limit]


def collect_dynamic(arm, frames: int, watch: list, frozen_bones: list,
                    unit_bones: dict, constrained: set | None = None) -> dict:
    """从 f1 连续步进；不跳帧。返回 F3/F4 需要的增量。"""
    scene = bpy.context.scene
    arm_world = arm.matrix_world
    if frames <= 1:
        return {"frames_sampled": 0, "evidence_mode": "stepped", "frozen_pairs": [],
                "unit_angles": [], "note": "frames<=1，未做动态采样"}

    f_start, f_end = 1, frames
    scene.frame_start, scene.frame_end = f_start, f_end

    first_local: dict = {}
    first_parent: dict = {}
    first_world: dict = {}
    max_angle: dict = {n: 0.0 for n in watch}

    scene.frame_set(f_start)          # 关键：从 f1 开始连续积分
    for name in watch:
        pb = arm.pose.bones.get(name)
        if pb is None:
            continue
        pw = _world_quat(arm_world, pb)
        first_world[name] = pw
        if pb.parent is not None:
            pq = _world_quat(arm_world, pb.parent)
            first_parent[name] = pq
            first_local[name] = pq.inverted() @ pw if pw is not None else None
        else:
            first_parent[name] = None
            first_local[name] = pw

    for f in range(f_start + 1, f_end + 1):
        scene.frame_set(f)
        for name in watch:
            pb = arm.pose.bones.get(name)
            if pb is None:
                continue
            pw = _world_quat(arm_world, pb)
            ang = _angle_deg(first_world.get(name), pw)
            if ang > max_angle.get(name, 0.0):
                max_angle[name] = ang

    scene.frame_set(f_end)
    pairs = []
    for name in watch:
        pb = arm.pose.bones.get(name)
        if pb is None:
            continue
        pw = _world_quat(arm_world, pb)
        if pb.parent is not None:
            pq = _world_quat(arm_world, pb.parent)
            local_f = pq.inverted() @ pw
            local_0 = first_local.get(name)
            rot_delta = _angle_deg(local_0, local_f)
            parent_name = pb.parent.name
        else:
            rot_delta = _angle_deg(first_world.get(name), pw)
            pq = None
            parent_name = None
        pairs.append({
            "bone": name,
            "parent": parent_name,
            "rot_delta_deg": round(rot_delta, 4),
            "parent_rot_delta_deg": round(_angle_deg(first_parent.get(name), pq), 4)
            if pb.parent is not None else 0.0,
            "max_angle_deg": round(max_angle.get(name, 0.0), 3),
            "is_frozen_candidate": name in frozen_bones,
            "has_physics_constraint": bool(constrained and name in constrained),
        })

    unit_angles = []
    for uid, names in sorted(unit_bones.items()):
        vals = [max_angle.get(n, 0.0) for n in names if n in max_angle]
        if not vals:
            continue
        unit_angles.append({
            "uid": uid,
            "anchor_bones": names[:3],
            "max_angle_deg": round(max(vals), 3),
            "bones_measured": len(vals),
            "definition": "采样区间内该单元骨相对 f1 的世界旋转最大变化",
        })

    return {
        "frames_sampled": f_end - f_start + 1,
        "frame_range": {"start": f_start, "end": f_end},
        "evidence_mode": "baked" if _is_baked() else "stepped",
        "frozen_pairs": pairs,
        "unit_angles": unit_angles,
        "max_rotation_delta_deg": round(max((p["max_angle_deg"] for p in pairs), default=0.0), 3),
    }


def _is_baked() -> bool:
    rbw = getattr(bpy.context.scene, "rigidbody_world", None)
    if rbw is None:
        return False
    try:
        return bool(rbw.point_cache.is_baked)
    except Exception:
        return False


def collect(opts: dict):
    """返回 (evidence, warnings, status, frame_range, sha_before, config)。"""
    blend = opts["blend"]
    if not os.path.isfile(blend):
        raise SystemExit("找不到 .blend：%s" % blend)
    sha_before = sha256_file(blend)
    try:
        bpy.ops.wm.open_mainfile(filepath=blend)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit("打开 .blend 失败：%s" % exc)

    warnings: list = []
    scene = bpy.context.scene
    root = _find_root()
    arm = _find_arm(root)
    if arm is None:
        raise SystemExit("场景里没有骨架对象，无法做物理归因")

    hist, con_bones = _constraint_hist(arm)
    rigids = [o for o in bpy.data.objects if getattr(o, "mmd_type", None) == "RIGID_BODY"]
    rbw = getattr(scene, "rigidbody_world", None)
    if rbw is None:
        warnings.append("场景没有 rigidbody_world：F2/F3 的动态证据不可得")
    cache = {}
    behaviour = {"fps": scene.render.fps / max(1e-9, scene.render.fps_base),
                 "frame_start": scene.frame_start, "frame_end": scene.frame_end}
    if rbw is not None:
        cache = {
            "is_baked": bool(rbw.point_cache.is_baked),
            "frame_start": int(rbw.point_cache.frame_start),
            "frame_end": int(rbw.point_cache.frame_end),
        }
        behaviour.update({
            "substeps_per_frame": int(rbw.substeps_per_frame),
            "solver_iterations": int(rbw.solver_iterations),
            "point_cache_info": str(rbw.point_cache.info),
        })

    is_built = None
    if root is not None:
        try:
            is_built = bool(root.mmd_root.is_built)
        except Exception:
            warnings.append("root.mmd_root 读取失败，is_built 缺失")

    masses = []
    for obj in rigids:
        rb = getattr(obj, "rigid_body", None)
        if rb is not None:
            masses.append(float(rb.mass))
    mass_max = max(masses) if masses else None

    pmx_ctx = None
    if opts.get("pmx"):
        try:
            pmx_ctx = _pmx_targets(opts["pmx"], opts)
        except Exception as exc:  # noqa: BLE001
            warnings.append("PMX 静态证据合并失败：%s" % exc)

    frozen_bones = pmx_ctx["frozen_bones"] if pmx_ctx else []
    unit_bones = pmx_ctx["unit_bones"] if pmx_ctx else {}
    watch = _watch_names(arm, frozen_bones, unit_bones)
    if opts.get("watch_bones"):
        try:
            watch = json.loads(opts["watch_bones"])
        except ValueError:
            warnings.append("--watch-bones 不是合法 JSON，忽略")

    dynamic = collect_dynamic(arm, int(opts.get("frames") or 0), watch,
                              set(frozen_bones), unit_bones,
                              {c["bone"] for c in con_bones})

    blender = {
        "mmd_root": {
            "name": root.name if root else None,
            "is_built": is_built,
        },
        "armature": {"name": arm.name, "bones": len(arm.data.bones)},
        "constraints": hist,
        "constraint_bones": con_bones[:400],
        "rigids": len(rigids),
        "collision_collections": _collision_census(rigids),
        "point_cache": cache,
        "behaviour": behaviour,
        "rigid_mass_max_kg": mass_max,
        "penetration": None,   # 穿透需要网格级测量，由 M04/phys_probe 提供
        "dynamic": dynamic,
        "frozen_pairs": dynamic.get("frozen_pairs") or [],
        "unit_angles": dynamic.get("unit_angles") or [],
        "watched_bones": len(watch),
    }
    if dynamic.get("note"):
        warnings.append(dynamic["note"])

    evidence = {"blender": blender, "cache": cache}
    if pmx_ctx:
        evidence = pmx_ctx["evidence"]
        evidence["blender"] = blender
        evidence["cache"] = cache
    else:
        evidence["model"] = {"name": root.name if root else None,
                             "bones": len(arm.data.bones),
                             "rigids": len(rigids),
                             "joints": None}

    sha_after = sha256_file(blend)
    if sha_after != sha_before:
        warnings.append("源 .blend SHA256 在采集期间发生变化（%s → %s）" % (sha_before[:12], sha_after[:12]))
        status = "partial"
    else:
        status = "ok" if rbw is not None and dynamic.get("frames_sampled") else "partial"

    evidence["source"] = {
        "type": "blend",
        "path": os.path.abspath(blend),
        "sha256_before": sha_before,
        "sha256_after": sha_after,
    }
    frame_range = {
        "start": dynamic.get("frame_range", {}).get("start"),
        "end": dynamic.get("frame_range", {}).get("end"),
        "fps": behaviour.get("fps"),
        "evidence_mode": dynamic.get("evidence_mode"),
    }
    config = pmx_ctx["config"] if pmx_ctx else diagnose.default_config()
    if opts.get("config") and not pmx_ctx:
        diagnose.merge_evidence(config, diagnose.load_json(opts["config"]))
    return evidence, warnings, status, frame_range, sha_before, config


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        opts = parse_args(argv)
    except SystemExit as exc:
        sys.stderr.write("%s\n" % exc)
        return EXIT_INPUT

    try:
        collected = collect(opts)
    except SystemExit as exc:
        sys.stderr.write("%s\n" % exc)
        return EXIT_INPUT
    evidence, warnings, status, frame_range, sha_before, config = collected

    report = diagnose.build_report(
        evidence,
        source_type="blend",
        input_path=opts["blend"],
        input_sha256=sha_before,
        config=config,
        frame_range=frame_range,
        experiment_id=opts.get("experiment_id"),
        status=status,
        warnings=warnings,
    )
    diagnose.write_json(opts["out"], report)
    sys.stdout.write(diagnose.summary_line(report) + "\n")
    sys.stdout.flush()
    # 刚性体析构会段错误（历史记录）：JSON 已 fsync，直接退出，报告里写明
    os._exit(EXIT_OK if status == "ok" else EXIT_PARTIAL)


if __name__ == "__main__":
    raise SystemExit(main())
