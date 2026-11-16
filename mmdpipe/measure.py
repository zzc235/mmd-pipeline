"""M04 · 逐帧测量 → measurement 装配器（纯 Python，不 import bpy）。

为什么需要这一层
----------------
Blender 侧（A1）只负责落**逐帧原始值**：`frame, bone, angle_deg`、
`frame, bone, parent_delta_deg`、`frame, roi, max_depth_m`。聚合值全在这里算，
全场只有一个口径——不会出现「你算的 p95 和我算的不一样」再吵一轮。

聚合口径（写死在代码里，别在报告里另说一套）
------------------------------------------
* 逐帧强度：`frame_max[f] = max over bones(angle_deg)`。用每帧的最大值而不是全骨平均，
  因为一根袖子甩飞就会被平均稀释掉（S5 实测 16 根袖骨 0.0°、父链 66.41° 就是这么被淹没的）。
* `median / p95 / max`：对 `frame_max[]` 取，线性插值分位数（`percentile_linear`）。
* `spike_count`：`frame_max > max(median + k*mad, abs_floor_deg)` 的帧数；
  `k`/`abs_floor_deg` 来自配置，不用魔法数字。
* `frozen`：在「父链确实在动」（`parent_delta_deg ≥ parent_min_deg`）的骨里，挑**最像冻结**
  的那一根（`max(angle) ` 最小），报它的父链增量、目标最大角、以及「角度 ≤ frozen_eps_deg
  的最长连续帧数」。没有骨满足父链条件时，`frozen_deg` 段照写，门禁会判 PASS（本来就不该动）。
* `penetration`：按 ROI 取 `min(max_depth_m)`（最负=最深），并统计有穿入的帧数与骨次。
* `plan_sequential_eval`：逐帧采样只能从 `scene.frame_start` 顺序步进——缓存不进 `.blend`，
  冷跳到中段是另一条轨迹（P12：`D_max = 1.922861 m`）。采样器不许自带「跳帧取一行」。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ASSEMBLY_VERSION = "measure/1"


class AssemblyError(ValueError):
    """输入不可用：缺列、类型错、行不是 JSON。"""


def _percentile(values, q):
    """线性插值分位数（q ∈ [0,1]）；空列表直接报错，不返回 0 冒充。"""
    if not values:
        raise AssemblyError("percentile 需要非空序列")
    if not 0.0 <= q <= 1.0:
        raise AssemblyError("q 必须在 [0,1]")
    data = sorted(values)
    if len(data) == 1:
        return float(data[0])
    pos = q * (len(data) - 1)
    low = int(pos)
    high = min(low + 1, len(data) - 1)
    frac = pos - low
    return float(data[low] + (data[high] - data[low]) * frac)


def _median(values):
    return _percentile(values, 0.5)


def _mad(values):
    med = _median(values)
    return _median([abs(v - med) for v in values])


def load_jsonl(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError as exc:
                    raise AssemblyError("%s:%d 不是 JSON：%s" % (path, lineno, exc))
                if not isinstance(row, dict):
                    raise AssemblyError("%s:%d 不是对象" % (path, lineno))
                rows.append(row)
    except OSError as exc:
        raise AssemblyError("读取失败：%s" % exc)
    return rows


def _require(row, keys, path):
    missing = [k for k in keys if k not in row]
    if missing:
        raise AssemblyError("%s 行缺列：%s" % (path, ", ".join(missing)))


def _by_frame(rows):
    """{(frame, bone): angle} —— 同帧同骨重复出现直接报错，不取最后一个糊过去。"""
    out = {}
    for row in rows:
        key = (int(row["frame"]), str(row["bone"]))
        if key in out:
            raise AssemblyError("同帧同骨重复：frame=%s bone=%s" % key)
        value = row["angle_deg"]
        if value is None:
            # 缺测量值不能当 0 参与统计：那会把「没测」算成「没动」
            raise AssemblyError("angle_deg 为 null：frame=%s bone=%s" % key)
        try:
            out[key] = float(value)
        except (TypeError, ValueError):
            raise AssemblyError("angle_deg 不是数值：frame=%s bone=%s value=%r"
                                % (key[0], key[1], value))
    return out


def _parent_by_bone(rows):
    """每根骨的父链增量取非空最大值。

    实测发现：Blender 侧首帧没有「上一帧」，`parent_delta_deg` 为 **null**（18 骨各一条）。
    那不是缺数据，是这一帧本来就没有可比的前一帧——所以跳过 null，不能当 0，
    也不能因此整条样本判 UNKNOWN（否则每份真实采样都会白白丢掉 frozen 段）。
    """
    out = {}
    for row in rows:
        value = row.get("parent_delta_deg")
        if value is None:
            continue
        bone = str(row["bone"])
        try:
            val = float(value)
        except (TypeError, ValueError):
            raise AssemblyError("parent_delta_deg 不是数值：bone=%s value=%r"
                                % (bone, value))
        out[bone] = max(out.get(bone, val), val)
    return out


def _streak(frames_sorted, values_by_frame, eps):
    """角度 ≤ eps 的最长连续帧数。"""
    best = run = 0
    for frame in frames_sorted:
        if abs(values_by_frame[frame]) <= eps:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


class SequentialEvalError(AssemblyError):
    """顺序求值计划不可满足：不能回退、不能冷跳、区间不合法。"""


def plan_sequential_eval(frame_start, first_frame, last_frame, *, baseline_frame=None):
    """逐帧采样器必须遵守的顺序求值计划（P12 实测结论，不是偏好）。

    为什么
    ------
    `B_from_blend1.blend` 的 `point_cache` 落盘时并不带帧数据（P12：重开后
    `is_baked=false` / `is_outdated=true`，`info` 仍谎报「240 frames in memory」）。
    在这种输入上**冷跳**（直接 `frame_set(109)`）得到的是第三条轨迹——与顺序求值
    逐位不相等的 `D_max = 1.922861 m`；只有「从 `scene.frame_start` 逐帧步进到目标帧」
    才和重算轨迹逐位相等（`seq@109` / `seq@240` 对 `P0` 均 `D_all = 0.000000`）。

    因此交付契约是「必须从 `frame_start` 顺序求值」，采样器在架构上就不该有
    「跳到第 N 帧取一行」这条路：本函数只产出**连续升序**的访问序列，调用方照着走。

    返回
    ----
    dict：`visited_frames`（连续升序，从 `frame_start` 起）、`warmup_frames`
    （首个被测帧之前必须空走的帧数）、以及原样记回 meta 的四个边界值。

    拒绝（`SequentialEvalError`，调用方应转 UNKNOWN，不得吞成 PASS）
    ------
    * 区间非法（`last < first`，或 `first < frame_start` 达不到）；
    * `baseline_frame` 早于 `frame_start`（冷跳才拿得到）；
    * `baseline_frame` 晚于 `last_frame`（顺序求值不能回退）。
    """
    for name, value in (("frame_start", frame_start), ("first_frame", first_frame),
                        ("last_frame", last_frame)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise SequentialEvalError("%s 必须是整数帧号：%r" % (name, value))
    if baseline_frame is not None and (isinstance(baseline_frame, bool)
                                       or not isinstance(baseline_frame, int)):
        raise SequentialEvalError("baseline_frame 必须是整数帧号：%r" % (baseline_frame,))
    if last_frame < first_frame:
        raise SequentialEvalError("区间反了：first=%d last=%d" % (first_frame, last_frame))
    if first_frame < frame_start:
        raise SequentialEvalError(
            "首个被测帧 %d 早于 scene.frame_start %d：顺序求值到不了" % (first_frame, frame_start))
    if baseline_frame is not None:
        if baseline_frame < frame_start:
            raise SequentialEvalError(
                "baseline_frame %d 早于 scene.frame_start %d" % (baseline_frame, frame_start))
        if baseline_frame > last_frame:
            raise SequentialEvalError(
                "baseline_frame %d 晚于区间末帧 %d：顺序求值不能回退（先走到再退回来等于冷跳）"
                % (baseline_frame, last_frame))
    return {
        "frame_start": frame_start,
        "first_frame": first_frame,
        "last_frame": last_frame,
        "baseline_frame": baseline_frame,
        "visited_frames": list(range(frame_start, last_frame + 1)),
        "warmup_frames": first_frame - frame_start,
        "policy": "sequential_from_frame_start",
    }


def assemble(dynamics_rows, penetration_rows, *, sample_id, evidence_mode,
             frames, assembly, penetrations_roi=None, penetrations_basis=None):
    """两路逐帧数据 → `physics_gate` 能吃的 measurement。"""
    cfg = assembly["assembly"]
    if frames.get("start") is None or frames.get("end") is None:
        raise AssemblyError("frames.start / frames.end 必须给")
    angles = _by_frame(dynamics_rows)
    if not angles:
        raise AssemblyError("dynamics 为空：没有可聚合的帧")

    per_frame = {}
    bones_by_frame = {}
    for (frame, bone), angle in angles.items():
        per_frame[frame] = max(per_frame.get(frame, angle), angle)
        bones_by_frame.setdefault(frame, set()).add(bone)
    frame_keys = sorted(per_frame)
    frame_max = [per_frame[f] for f in frame_keys]

    median = _median(frame_max)
    p95 = _percentile(frame_max, 0.95)
    peak = max(frame_max)
    spike_cfg = cfg["spike"]
    threshold = max(median + float(spike_cfg["mad_k"]) * _mad(frame_max),
                    float(spike_cfg["abs_floor_deg"]))
    spikes = sum(1 for v in frame_max if v > threshold)

    measurement = {
        "sample_id": sample_id,
        "evidence_mode": evidence_mode,
        "frames": {"start": int(frames["start"]), "end": int(frames["end"])},
        "dynamics": {
            "median": round(median, 6),
            "p95": round(p95, 6),
            "max": round(peak, 6),
            "spike_count": int(spikes),
            "bones": len({bone for (_f, bone) in angles}),
            "spike_threshold_deg": round(threshold, 6),
            "aggregation": "frame_max_then_percentile",
        },
    }

    # 冻结：只在父链确实在动的骨里挑最像冻结的那一根
    parents = _parent_by_bone(dynamics_rows)
    frozen_cfg = cfg["frozen"]
    parent_min = float(frozen_cfg["parent_min_deg"])
    eps = float(frozen_cfg["frozen_eps_deg"])
    candidates = []
    by_bone_frames = {}
    for (frame, bone), angle in angles.items():
        by_bone_frames.setdefault(bone, {})[frame] = angle
    for bone, parent in parents.items():
        if parent < parent_min or bone not in by_bone_frames:
            continue
        values = by_bone_frames[bone]
        candidates.append({
            "bone": bone,
            "parent_delta_deg": round(parent, 6),
            "target_delta_deg": round(max(values.values()), 6),
            "consecutive_frames": _streak(sorted(values), values, eps),
        })
    if candidates:
        worst = min(candidates, key=lambda c: (c["target_delta_deg"], -c["consecutive_frames"],
                                               c["bone"]))
        measurement["frozen"] = {
            "parent_delta_deg": worst["parent_delta_deg"],
            "target_delta_deg": worst["target_delta_deg"],
            "consecutive_frames": worst["consecutive_frames"],
            "bone": worst["bone"],
            "candidates": len(candidates),
        }
    else:
        # 没有骨的父链动过：如实写 0，门禁会判 PASS（本来就不该动），不是「缺数据」。
        # 但有一个更可疑的情形：父链增量**恒为 0**而目标角很大 —— 那分不清「父链真没动」
        # 还是「这一列根本没测」。M02 首采就是这样：240 帧 × 18 骨，parent_delta_deg 全 0.0，
        # 而 angle 从 1.74° 变到 67.2°。这种情况下冻结门禁必须 UNKNOWN，不能凭 0 判 PASS。
        all_parent_zero = all(v == 0.0 for v in parents.values()) if parents else True
        target_peak = max(frame_max)
        target_span = target_peak - min(frame_max)
        # 父链恒 0 有两种完全不同的含义，必须分开：
        #   a) 父骨是静止根、子骨在动 —— 这是「物理在跑」的正面证据（实测 B_from_blend1:
        #      下半身 240 帧四元数有效位全同，飘带照样甩到 67.2°）；
        #   b) 父链和目标**都不动** —— 分不清「真静止」还是「这一列没测」，只能 UNKNOWN。
        # 所以判据是「全零 + 目标跨度≈0」，不是「全零 + 目标角大」；后者会误报 a) 这种正常样本。
        suspicious = bool(parents) and all_parent_zero and \
            target_span < float(frozen_cfg.get("suspicious_zero_parent_span_deg", 1.0))
        measurement["frozen"] = {
            "parent_delta_deg": 0.0,
            "target_delta_deg": round(target_peak, 6) if suspicious else 0.0,
            "consecutive_frames": 0,
            "bone": None,
            "candidates": 0,
            "parent_all_zero": all_parent_zero,
            "target_span_deg": round(target_span, 6),
            "suspicious_zero_parent": suspicious,
        }

    if penetration_rows:
        pen_cfg = cfg["penetration"]
        eps_m = float(pen_cfg["penetration_epsilon_m"])
        by_roi = {}
        for row in penetration_rows:
            _require(row, ("frame", "roi", "max_depth_m"), "penetration")
            roi = str(row["roi"])
            depth = float(row["max_depth_m"])
            entry = by_roi.setdefault(roi, {"deepest": depth, "frames": set(), "bones": set(),
                                             "frames_seen": set(), "bones_seen": set()})
            entry["deepest"] = min(entry["deepest"], depth)
            # 「测了多少帧」与「有多少帧穿入」是两件事，必须分开落盘：
            # 只有后者时，一份干净样本（0 帧穿入）与「压根没测」在门禁眼里长得一模一样。
            entry["frames_seen"].add(int(row["frame"]))
            if row.get("bone"):
                entry["bones_seen"].add(str(row["bone"]))
            if depth <= -eps_m:
                entry["frames"].add(int(row["frame"]))
                if row.get("bone"):
                    entry["bones"].add(str(row["bone"]))
        roi = penetrations_roi or sorted(by_roi)[0]
        entry = by_roi.get(roi)
        if entry is None:
            raise AssemblyError("penetration 里没有 ROI=%s" % roi)
        measurement["penetration"] = {
            "roi": roi,
            "max_depth_m": round(entry["deepest"], 6),
            "frames": len(entry["frames"]),
            "bones": len(entry["bones"]),
            "frames_measured": len(entry["frames_seen"]),
            "bones_seen": len(entry["bones_seen"]),
            "epsilon_m": eps_m,
        }
        # 口径（mesh/capsule）由生产者声明，不在这里猜：门禁缺 basis 会判 UNKNOWN。
        if penetrations_basis:
            measurement["penetration"]["basis"] = str(penetrations_basis)
    return measurement


def build_parser():
    p = argparse.ArgumentParser(description="逐帧测量 → measurement 装配器")
    p.add_argument("--dynamics", required=True, help="逐帧 dynamics JSONL")
    p.add_argument("--penetration", help="逐帧穿透 JSONL（可缺，缺了 measurement 里就没这段）")
    p.add_argument("--assembly", default=os.path.join(
        "presets", "physics_gate", "assembly_v1.json"), help="聚合规则配置")
    p.add_argument("--sample-id", required=True)
    p.add_argument("--evidence-mode", default="stepped",
                   choices=["baked", "stepped", "render", "synthetic"])
    p.add_argument("--frame-start", type=int, required=True)
    p.add_argument("--frame-end", type=int, required=True)
    p.add_argument("--roi", help="穿透 ROI 名（多 ROI 时必须指定）")
    p.add_argument("--penetration-basis", choices=["mesh", "capsule"],
                   help="穿透口径：mesh=网格穿入 / capsule=刚体胶囊重叠。不给则门禁判 UNKNOWN")
    p.add_argument("--out", required=True)
    return p


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = build_parser().parse_args(argv)
    try:
        with open(args.assembly, encoding="utf-8") as fh:
            assembly = json.load(fh)
        for key in ("assembly_version", "assembly"):
            if key not in assembly:
                raise AssemblyError("装配配置缺字段：%s" % key)
        dynamics = load_jsonl(args.dynamics)
        penetration = load_jsonl(args.penetration) if args.penetration else []
        for row in dynamics:
            _require(row, ("frame", "bone", "angle_deg", "parent_delta_deg"), "dynamics")
        measurement = assemble(
            dynamics, penetration, sample_id=args.sample_id,
            penetrations_basis=args.penetration_basis,
            evidence_mode=args.evidence_mode,
            frames={"start": args.frame_start, "end": args.frame_end},
            assembly=assembly, penetrations_roi=args.roi)
    except (OSError, ValueError) as exc:
        sys.stderr.write("装配失败：%s\n" % exc)
        return 2
    try:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(measurement, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
    except OSError as exc:
        sys.stderr.write("写入失败：%s\n" % exc)
        return 2
    sys.stdout.write("%s dynamics=%s frozen=%s penetration=%s\n" % (
        measurement["sample_id"],
        "yes" if "dynamics" in measurement else "no",
        "yes" if "frozen" in measurement else "no",
        "yes" if "penetration" in measurement else "no"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
