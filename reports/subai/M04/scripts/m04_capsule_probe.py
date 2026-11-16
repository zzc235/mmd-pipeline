"""M04 穿透探针 · 胶囊口径（D-042 批准的第二来源）

口径：PMX 刚体的球/胶囊距离（`mmdpipe.clearance.penetration`），**不是网格穿入**。
所以它只能说「刚体胶囊无重叠」，**不得写成「模型无穿入」**——刚体没覆盖的骨在这里等于不存在。

自检（写在跑场景之前，不过就不出数）：
  1. 已知轴间距：两个半径已知的球，轴距 = r1+r2+d → 报 clearance ≈ d（±5%）；
  2. 人为重叠 5 cm：轴距 = r1+r2−0.05 → 报 penetration ≈ +0.05 m（±5%）。
两条都不依赖 Blender 场景，纯几何构造——方法错了在这里就会露。

单位：读的是 Blender 世界坐标（米），因此深度直接是米；**不要再乘 0.08**（那是 PMX 单位换算，
只在读 PMX 原始字节时需要）。

用法：
  blender --background --factory-startup --python m04_capsule_probe.py -- \
      --blend <path> --targets <s2_targets.json> --out <jsonl> --meta <json>
      [--frames 1:240] [--roi-label 18_skirt_capsule]

顺序求值（v5，P12 的结论，不是偏好）
------------------------------------
`point_cache` 落盘时不带帧数据（重开后 `is_baked=false` / `is_outdated=true`，`info` 仍写
「240 frames in memory」）。在这种输入上**冷跳**到中段是第三条轨迹：`cold@109` 与重算
`P0[109]` 的 `D_max = 1.922861 m`，而「从 `scene.frame_start` 逐帧步进」的 `seq@109` /
`seq@240` 对 `P0` 逐位相等（`D_all = 0.000000`）。所以本探针只走连续升序：
预热段（`frame_start → 首个被测帧`）只步进物理不取数，基线取帧也在这条路径上。
计划由 `mmdpipe.measure.plan_sequential_eval` 给，回退/冷跳在计划阶段就被拒（退出 3）。
"""
import argparse
import hashlib
import os
import json
import sys
import time
from types import SimpleNamespace

import addon_utils
import bpy

sys.path.insert(0, r"E:\dsh pr\woker2")
sys.path.insert(0, r"E:\code\mmdpipe-ai\A2")
from mmdpipe import clearance as C  # noqa: E402
from mmdpipe.measure import SequentialEvalError, plan_sequential_eval  # noqa: E402

SHAPE_OF = {"SPHERE": 0, "BOX": 1, "CAPSULE": 2}


def _args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--blend", required=True)
    p.add_argument("--targets", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--meta", required=True)
    p.add_argument("--frames", default="1:240")
    p.add_argument("--roi-label", default="18_skirt_capsule")
    p.add_argument("--bones", default="", help="逗号分隔骨名；给了就覆盖 --targets 的 ROI")
    p.add_argument("--pattern", default="", help="按子串从骨架里取骨名（如 下擺_11_）")
    p.add_argument("--baseline", default="", help="已版本化基线 JSON（D-056：判定用增量，不用绝对深度）")
    p.add_argument("--baseline-write", default="", help="把本次基线写到这个 JSON（含哈希，供下一笔引用）")
    p.add_argument("--baseline-frame", type=int, default=0,
                   help="基线取哪一帧（0 = frames 区间的第一帧）")
    p.add_argument("--keep-static", dest="exclude_static", action="store_false", default=True,
                   help="保留 kinematic=True 的静态占位刚体（默认排除：它们是管线补的占位体，"
                        "不是作者建的物理刚体，拿它们测重叠没有物理含义）")
    p.add_argument("--selftest-tol", type=float, default=0.05)
    return p.parse_args(argv)


def rb(shape, size, position, rotation=(0.0, 0.0, 0.0)):
    return SimpleNamespace(shape=shape, size=list(size), position=tuple(position),
                           rotation=tuple(rotation))


def selftest(tol):
    """两条构造自检：已知轴间距 / 人为重叠 5 cm。"""
    r1, r2 = 0.10, 0.06
    d = 0.25
    a = rb(0, (r1, r1, 0.0), (0.0, 0.0, 0.0))
    b = rb(0, (r2, r2, 0.0), (r1 + r2 + d, 0.0, 0.0))
    pen, _ = C.penetration(a, b)
    clearance_gap = -pen
    ok1 = abs(clearance_gap - d) <= tol * d

    overlap = 0.05
    b2 = rb(0, (r2, r2, 0.0), (r1 + r2 - overlap, 0.0, 0.0))
    pen2, _ = C.penetration(a, b2)
    ok2 = abs(pen2 - overlap) <= tol * overlap

    # 胶囊也要测：沿局部 Y 的胶囊，端点位移要与球一致
    cap_a = rb(2, (0.05, 0.20, 0.0), (0.0, 0.0, 0.0))
    cap_b = rb(2, (0.05, 0.20, 0.0), (0.0, 0.0, 0.0))
    cap_b.position = (0.0, 0.30, 0.0)
    pen3, _ = C.penetration(cap_a, cap_b)
    # 两根同轴等长胶囊沿轴向错开 0.30：半长各 0.10，轴段重叠 → 最近端点距 0.10，半径和 0.10 → 深度≈0
    ok3 = abs(pen3 - 0.0) <= 0.01
    return {
        "known_gap": {"expected_clearance_m": d, "reported_clearance_m": round(clearance_gap, 6),
                      "rel_err": round(abs(clearance_gap - d) / d, 6), "pass": ok1},
        "forced_overlap_5cm": {"expected_penetration_m": overlap,
                               "reported_penetration_m": round(pen2, 6),
                               "rel_err": round(abs(pen2 - overlap) / overlap, 6), "pass": ok2},
        "capsule_axis": {"expected_penetration_m": 0.0, "reported_m": round(pen3, 6),
                         "pass": ok3},
        "tolerance": tol,
        "pass": bool(ok1 and ok2 and ok3),
    }


def roi_bones(path):
    d = json.load(open(path, encoding="utf-8"))
    names = []
    for t in d.get("targets", []):
        n = t.get("joint_name") or (t.get("rigid_b") or {}).get("bone")
        if n:
            names.append(n)
    return sorted(set(names))


def rigid_objs():
    """刚体对象 = 带 Blender 原生 `rigid_body` 的对象。

    刻意**不依赖 mmd_tools 的扩展属性**：扩展在 `--background` 里未必注册
    （实测 `hasattr(o, "mmd_rigid")` 全 False，于是第一次跑出 0 个刚体、NOT_MEASURED）。
    原生属性 + 约束 subtarget + bound_box 就够还原形状/尺寸/绑定骨，可复现性更好。
    """
    return [o for o in bpy.data.objects if getattr(o, "rigid_body", None) is not None]


def pair_key(a, b):
    return a + "|" + b


def load_baseline(path):
    if not path:
        return None, None
    d = json.load(open(path, encoding="utf-8"))
    digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
    return d, digest


def bone_of(ob):
    """刚体 → 绑定骨。**两个来源都要读**：

    1. `CHILD_OF` 约束的 `subtarget`（mmd_tools 对「有骨」的刚体会建这条约束）；
    2. 自定义属性 `ob["bone"]`（mmd_tools `_set_bone` 的兜底存储）。

    实测只读第 1 条时，324 个刚体只覆盖 **35 根骨**（裙摆只有 `下擺_11_*` 11 根），
    于是 ROI（`s2_targets.json` 的 18 根 `下擺_0_*`）一个都匹配不上、误判「ROI 无刚体」。
    """
    try:
        b = ob.mmd_rigid.bone
        if b:
            return str(b)
    except Exception:  # noqa: BLE001
        pass
    for c in ob.constraints:
        if c.type == "CHILD_OF":
            tgt = getattr(c, "subtarget", "")
            if tgt:
                return tgt
    # 第三条来源：mmd_tools 对「跟骨」模式的刚体会把对象 parent_type 设为 BONE 并写 parent_bone
    if getattr(ob, "parent_type", "") == "BONE" and getattr(ob, "parent_bone", ""):
        return str(ob.parent_bone)
    return str(ob.get("bone", "") or "")


def size_of(ob, shape_name):
    """与 mmd_tools FnRigidBody.get_rigid_body_size 同口径（bound_box 推导）。"""
    (x0, y0, z0), (x1, y1, z1) = ob.bound_box[0], ob.bound_box[6]
    if not (x1 >= x0 and y1 >= y0 and z1 >= z0):
        return (1.0, 1.0, 1.0)
    if shape_name == "SPHERE":
        return ((z1 - z0) / 2.0, 0.0, 0.0)
    if shape_name == "BOX":
        return ((x1 - x0) / 2.0, (y1 - y0) / 2.0, (z1 - z0) / 2.0)
    if shape_name == "CAPSULE":
        diameter = x1 - x0
        return (diameter / 2.0, abs((z1 - z0) - diameter), 0.0)
    return (0.0, 0.0, 0.0)


def as_clearance(ob):
    shape_name = (ob.rigid_body.collision_shape or "SPHERE").upper()
    shape = SHAPE_OF.get(shape_name, 0)
    size = size_of(ob, shape_name)
    mw = ob.matrix_world
    return rb(shape, size, tuple(mw.translation), tuple(mw.to_euler()))


def main():
    a = _args()
    t0 = time.time()
    # 必须先启用 mmd_tools：刚体→骨的绑定存在扩展的 PropertyGroup 里，
    # `--background` 不加载扩展时 `o.mmd_rigid` 根本不存在（实测 324 个刚体全 False，
    # 只靠 CHILD_OF 只能认出 59 个、35 根骨，于是把「有刚体的 18 根下擺_0_*」误判成无刚体）。
    for mod in ("bl_ext.user_default.mmd_tools", "mmd_tools"):
        try:
            addon_utils.enable(mod, default_set=False, handle_error=None)
            print("[capsule] addon enabled: " + mod, flush=True)
            break
        except Exception:  # noqa: BLE001
            continue

    chk = selftest(a.selftest_tol)
    print("[capsule] selftest " + json.dumps(chk, ensure_ascii=True), flush=True)
    if not chk["pass"]:
        json.dump({"status": "NOT_MEASURED", "basis": "capsule",
                   "reason": "胶囊口径自检未过，拒绝出数", "selftest": chk},
                  open(a.meta, "w", encoding="utf-8", newline="\n"),
                  ensure_ascii=False, indent=2)
        print("[capsule] ABORT selftest failed")
        sys.exit(3)

    bpy.ops.wm.open_mainfile(filepath=a.blend)
    sc = bpy.context.scene
    # 缓存状态：P12 证明 `info` 会谎报「240 frames in memory」而帧数据不在文件里；
    # 1号 的 B 路实测又证明**两个布尔也判不出好坏**（健康烘焙件重开后同样是
    # is_baked=true && is_outdated=true）。所以这三个字段一律只当线索记下来，
    # 真正的证据是下面「从 frame_start 顺序步进」——这条路对两类输入都成立。
    cache_state = {"not_evidence": "info 会谎报「N frames in memory」；is_baked/is_outdated 也"
                                   "判不出好坏（健康烘焙件重开后同为 true/true）。只当线索记，"
                                   "证据是顺序求值本身"}
    pc = sc.rigidbody_world.point_cache if sc.rigidbody_world else None
    if pc is not None:
        cache_state.update({
            "is_baked": bool(pc.is_baked),
            "is_outdated": bool(pc.is_outdated),
            "use_disk_cache": bool(getattr(pc, "use_disk_cache", False)),
            "info": getattr(pc, "info", None),
        })
    names = roi_bones(a.targets)
    if a.bones:
        names = [x.strip() for x in a.bones.split(",") if x.strip()]
    elif a.pattern:
        arm0 = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
        if arm0 is not None:
            names = [b.name for b in arm0.data.bones if a.pattern in b.name]
    objs = rigid_objs()
    named = {}
    for ob in objs:
        bn = bone_of(ob)
        named.setdefault(bn, []).append(ob)
    roi_objs = [ob for n in names for ob in named.get(n, [])]
    if not roi_objs:
        json.dump({"status": "NOT_MEASURED", "basis": "capsule",
                   "reason": "ROI 骨没有对应刚体（无刚体的骨在胶囊口径里等于不存在）",
                   "roi_bones": names, "rigids_total": len(objs),
                   "rigid_bones_distinct": len(named),
                   "rigid_bones_sample": sorted(named)[:20], "selftest": chk},
                  open(a.meta, "w", encoding="utf-8", newline="\n"),
                  ensure_ascii=False, indent=2)
        print("[capsule] NOT_MEASURED no rigids for ROI")
        sys.exit(3)

    excluded_static = []
    if a.exclude_static:
        kept = []
        for o in roi_objs:
            if getattr(o.rigid_body, "kinematic", False):
                excluded_static.append(bone_of(o) or o.name)
            else:
                kept.append(o)
        roi_objs = kept
    # 骨 → 骨架，用于判「这一对是否同链相邻」（相邻骨的关节区本来就重叠，属预期）
    arm = None
    for cand in (o for o in bpy.data.objects if o.type == "ARMATURE"):
        names_here = {b.name for b in cand.data.bones}
        if any(n in names_here for n in names if n.startswith("\u4e0b\u64fa")):
            arm = cand
            break

    def related(a_bone, b_bone):
        """a 与 b 是否父子相邻（任一方是另一方的直接父/子）。"""
        if arm is None or not a_bone or not b_bone:
            return None
        bones = arm.data.bones
        for x, y in ((a_bone, b_bone), (b_bone, a_bone)):
            if x in bones and bones[x].parent is not None and bones[x].parent.name == y:
                return True
        return False

    roi_set = set(id(o) for o in roi_objs)
    others = [o for o in objs if id(o) not in roi_set]
    f0, f1 = [int(x) for x in a.frames.split(":")]
    f0, f1 = max(f0, sc.frame_start), min(f1, sc.frame_end)

    # ---- 顺序求值计划（P12）：缓存不进 .blend，冷跳到中段是第三条轨迹 ----
    # `seq@109`/`seq@240` 对 `P0` 逐位相等只在「从 scene.frame_start 逐帧步进」时成立；
    # 冷跳 `frame_set(109)` 的 D_max 是 1.922861 m。所以采样器不再有「跳帧取一行」这条路。
    base_doc, base_sha = load_baseline(a.baseline)
    baseline = {}
    baseline_source = "loaded" if base_doc else "computed"
    need_baseline = not base_doc
    bf = (a.baseline_frame or f0) if need_baseline else None
    try:
        plan = plan_sequential_eval(int(sc.frame_start), f0, f1, baseline_frame=bf)
    except SequentialEvalError as exc:
        json.dump({"status": "NOT_MEASURED", "basis": "capsule",
                   "reason": "顺序求值计划不可满足，拒绝出数：%s" % exc,
                   "frames": [f0, f1], "baseline_frame": bf,
                   "frame_start": int(sc.frame_start), "selftest": chk},
                  open(a.meta, "w", encoding="utf-8", newline="\n"),
                  ensure_ascii=False, indent=2)
        print("[capsule] NOT_MEASURED eval plan rejected: %s" % exc, flush=True)
        sys.exit(3)
    if base_doc:
        baseline = {k: float(v) for k, v in base_doc.get("baseline_m", {}).items()}
    print("[capsule] eval policy=%s warmup=%d visited=%d"
          % (plan["policy"], plan["warmup_frames"], len(plan["visited_frames"])), flush=True)

    rows, per_frame = [], []
    baseline_done = False
    for f in plan["visited_frames"]:
        sc.frame_set(f)
        if need_baseline and f == bf and not baseline_done:
            # 基线取帧同样走顺序求值（walk 到 bf 再取，不冷跳）
            roi_rbs_b = [(o, as_clearance(o)) for o in roi_objs]
            other_rbs_b = [(o, as_clearance(o)) for o in others]
            for o, rb_a in roi_rbs_b:
                ba = bone_of(o) or o.name
                for o2, rb_b in other_rbs_b:
                    pen, _ = C.penetration(rb_a, rb_b)
                    baseline[pair_key(ba, bone_of(o2) or o2.name)] = max(0.0, float(pen))
            baseline_done = True
            print("[capsule] baseline computed at frame %d: %d pairs" % (bf, len(baseline)),
                  flush=True)
            if a.baseline_write:
                doc = {
                    "spec": "penetration_baseline/1",
                    "basis": "capsule",
                    "scene": os.path.basename(a.blend),
                    "roi": a.roi_label,
                    "baseline_frame": bf,
                    "note": "按刚体对记录的重叠量；判定用 max(0, depth-baseline) > epsilon。"
                            "该基线只对这一份交付物成立（第 11 行占位刚体只存在于 Nov-7 交付物里）",
                    "pairs": len(baseline),
                    "baseline_m": {k: round(v, 6) for k, v in sorted(baseline.items()) if v > 0.0},
                }
                os.makedirs(os.path.dirname(a.baseline_write), exist_ok=True)
                with open(a.baseline_write, "w", encoding="utf-8", newline="\n") as fh:
                    json.dump(doc, fh, ensure_ascii=False, indent=2, sort_keys=True)
                    fh.write("\n")
                base_sha = hashlib.sha256(open(a.baseline_write, "rb").read()).hexdigest()
                print("[capsule] baseline written: %s  sha256=%s"
                      % (a.baseline_write, base_sha), flush=True)
        if not (f0 <= f <= f1):
            continue  # 预热段：只步进物理，不取数
        roi_rbs = [(o, as_clearance(o)) for o in roi_objs]
        other_rbs = [(o, as_clearance(o)) for o in others]
        worst, worst_bone, n_hit = 0.0, None, 0
        worst_other = None
        worst_raw = 0.0
        n_adjacent = n_other_pairs = n_no_baseline = 0
        for o, rb_a in roi_rbs:
            ba = bone_of(o) or o.name
            for o2, rb_b in other_rbs:
                pen, _ = C.penetration(rb_a, rb_b)
                if pen <= 0.0:
                    continue
                n_hit += 1
                bb = bone_of(o2) or o2.name
                if related(ba, bb):
                    n_adjacent += 1
                else:
                    n_other_pairs += 1
                key = pair_key(ba, bb)
                if key not in baseline and baseline_source == "loaded":
                    # 没有基线的对不许默认 0：记成 UNKNOWN，不参与判定
                    n_no_baseline += 1
                    continue
                delta = max(0.0, float(pen) - baseline.get(key, 0.0))
                if delta > worst:
                    worst = delta
                    worst_raw = float(pen)
                    worst_bone = ba
                    worst_other = bb
        depth = -round(worst, 6)          # 负值=重叠，与门禁符号约定一致
        rows.append({"frame": f, "roi": a.roi_label, "max_depth_m": depth, "bone": worst_bone})
        per_frame.append({"frame": f, "overlapping_pairs": n_hit, "max_depth_m": depth,
                          "bone": worst_bone, "bone_other": worst_other,
                          "baseline_m": round(-(worst_raw - worst), 6) if worst_bone else None,
                          "raw_depth_m": round(-worst_raw, 6) if worst_bone else None,
                          "pairs_without_baseline": n_no_baseline,
                          "adjacent_pairs": n_adjacent, "other_pairs": n_other_pairs})
        if f % 20 == 0:
            print("[capsule] frame %d  %.1fs" % (f, time.time() - t0), flush=True)

    with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    deepest = min(rows, key=lambda r: r["max_depth_m"]) if rows else None
    meta = {
        "status": "MEASURED_UNVALIDATED",
        "basis": "capsule",
        "method": "MMD 刚体球/胶囊距离（mmdpipe.clearance.penetration），读 Blender 世界坐标（米）",
        "not_equal_to": "网格穿入：刚体没覆盖的骨在胶囊口径里等于不存在，胶囊 PASS 不等于模型无穿入",
        "addon_enabled": True,
        "selftest": chk,
        "blend": a.blend,
        "roi": a.roi_label,
        "roi_bones": names,
        "rigids_total": len(objs),
        "rigid_bones_distinct": len(named),
        "roi_rigids": len(roi_objs),
        "excluded_static_rigids": excluded_static,
        "exclude_static": bool(a.exclude_static),
        "baseline_source": baseline_source,
        "baseline_sha256": base_sha,
        "baseline_pairs": len(baseline),
        "sign_note": "max_depth_m 是**超出基线的增量**（负值=新增重叠），raw_depth_m 是原始重叠；"
                     "baseline_m 是该对的基线。判定式 max(0, depth-baseline) > epsilon。",
        "roi_missing": [n for n in names if n not in named][:20],
        "frames": [f0, f1],
        "eval_policy": plan["policy"],
        "eval_plan": {
            "frame_start": plan["frame_start"],
            "first_frame": plan["first_frame"],
            "last_frame": plan["last_frame"],
            "baseline_frame": plan["baseline_frame"],
            "warmup_frames": plan["warmup_frames"],
            "visited_frames": len(plan["visited_frames"]),
            "note": "从 scene.frame_start 连续步进到末帧，预热段只步进物理不取数；"
                    "本输入上冷跳是另一条轨迹（P12：顺序求值逐位相等，冷跳 D_max 1.922861 m）",
        },
        "cache_state": cache_state,
        "frames_measured": len(rows),
        "deepest": deepest,
        "adjacent_note": ("adjacent_pairs = 同一骨链父子相邻的刚体重叠（关节区本来就重叠，属预期）；"
                          "other_pairs = 非相邻骨之间的重叠（才是可疑的）"),
        "per_frame": per_frame,
        "elapsed_s": round(time.time() - t0, 1),
        "caveats": [
            "刚体胶囊是 PMX 作者给的近似体，不是网格表面；胶囊无重叠不能替代网格测量",
            "BOX 形状按球处理（clearance.axis_of 只分球/胶囊），本轮 ROI 与其余刚体里若有 BOX 需单列",
        ],
    }
    json.dump(meta, open(a.meta, "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=2)
    print("[capsule] done frames=%d deepest=%s" % (len(rows), deepest))
    # 主动干净退出：13:14 那次是在 Blender 收尾释放物理场景时撞 0xC0000005（跑完之后），
    # 这里先把解释器交还，避免同一路径再崩一次。
    sys.stdout.flush()
    sys.exit(0)


main()
