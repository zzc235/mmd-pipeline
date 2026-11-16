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
        out[key] = float(row["angle_deg"])
    return out


def _parent_by_bone(rows):
    out = {}
    for row in rows:
        bone = str(row["bone"])
        val = float(row["parent_delta_deg"])
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


def assemble(dynamics_rows, penetration_rows, *, sample_id, evidence_mode,
             frames, assembly, penetrations_roi=None):
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
        # 没有骨的父链动过：如实写 0，门禁会判 PASS（本来就不该动），不是「缺数据」
        measurement["frozen"] = {
            "parent_delta_deg": 0.0,
            "target_delta_deg": 0.0,
            "consecutive_frames": 0,
            "bone": None,
            "candidates": 0,
        }

    if penetration_rows:
        pen_cfg = cfg["penetration"]
        eps_m = float(pen_cfg["penetration_epsilon_m"])
        by_roi = {}
        for row in penetration_rows:
            _require(row, ("frame", "roi", "max_depth_m"), "penetration")
            roi = str(row["roi"])
            depth = float(row["max_depth_m"])
            entry = by_roi.setdefault(roi, {"deepest": depth, "frames": set(), "bones": set()})
            entry["deepest"] = min(entry["deepest"], depth)
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
            "epsilon_m": eps_m,
        }
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
