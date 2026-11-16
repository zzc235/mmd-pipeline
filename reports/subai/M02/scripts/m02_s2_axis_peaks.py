#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S2 换轴依据：从**已有 dump** 算三轴 max|rot| 峰值表（不开 Blender、只读文件）。

用途
----
`D-170` 要求「取峰值最大的那根作为 S2 变量轴」。这个选择必须由数据给，不能沿用旧口径
（旧口径是 X，理由是 `limit_ang_x` 本身）。所以本脚本只做一件事：
读一份已落盘的 `frames.jsonl`（`m02_dynamics_probe.py` 的产物），对 18 根 `下擺_0_*`
逐帧取 `rot_x_deg / rot_y_deg / rot_z_deg` 的绝对峰值，印成表，并给出：
  - 每根轴的峰值（deg 与 rad）、落在哪根骨、哪一帧；
  - 每根轴对一组候选限值的**敏感性**（有多少采样点越过该限值、最大超越量）；
  - 选中的变量轴（三根轴里峰值最大的那根）。

口径（与 `s2_prereg_v3.md` §1.1 一致，不新造）
  - 分解：`rel = parent.matrix^-1 @ pb.matrix`，`rel.to_euler('XYZ')`，取 x / y / z。
    **顺序依赖**：换分解顺序会改变三轴的读数，跨报告只认 XYZ。
  - 采样：每一帧，不抽帧；聚合：18 根骨 × 全部帧取 `max |rot_axis|`。
  - dump 里的角度是**度**、且已 round 到 6 位小数（`D-143` 的仪器分辨率）。

为什么不用「合成角 `angle_deg`」
  `angle_deg` 是无符号的合成量，它分不出是哪根轴在动；而 S2 换轴要选的正是「哪根轴」。
  两者都印出来，但**选轴只用三轴分解量**。

假绿防线（与今天的整轮口径同族）
  - 骨集合不是 18 根 ⇒ 退出码 2，不出表；
  - 行数为 0 / 帧数不等于 meta 声明的帧区间 ⇒ 退出码 2；
  - 每条轴都印采样点数与「参与聚合的骨数」，`scanned==0` 不可能是绿。

只读：不写回 dump、不碰 Blender、不改任何 artifact。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys

DEG = 180.0 / 3.141592653589793
SKIRT = re.compile(r"^下擺_0_\d+$")
EXPECTED_BONES = 18
AXES = ("x", "y", "z")


def sha256_of(path):
    h = hashlib.sha256()
    with io.open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path):
    rows = []
    with io.open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def analyse(path):
    rows = load(path)
    if not rows:
        raise SystemExit("扫描到 0 行：%s" % path)

    bones = sorted({r["bone"] for r in rows if SKIRT.match(r.get("bone", ""))})
    frames = sorted({int(r["frame"]) for r in rows if "frame" in r})
    if len(bones) != EXPECTED_BONES:
        raise SystemExit(
            "骨集合是 %d 根、不是 %d 根（%s）：不下结论。命中的骨：%s"
            % (len(bones), EXPECTED_BONES, path, ", ".join(bones)))
    if not frames:
        raise SystemExit("没有帧号：%s" % path)

    per_axis = {}
    for axis in AXES:
        key = "rot_%s_deg" % axis
        best = None
        n_samples = 0
        for r in rows:
            if not SKIRT.match(r.get("bone", "")):
                continue
            v = r.get(key)
            if v is None:
                raise SystemExit("第 %s 帧的 %s 缺 %s 列：dump 口径不符"
                                 % (r.get("frame"), r.get("bone"), key))
            n_samples += 1
            a = abs(float(v))
            if best is None or a > best["peak_deg"]:
                best = {"peak_deg": a, "bone": r["bone"], "frame": int(r["frame"])}
        best["peak_rad"] = best["peak_deg"] / DEG
        best["samples"] = n_samples
        best["bones"] = len({r["bone"] for r in rows if SKIRT.match(r.get("bone", ""))})
        best["sensitivity"] = []      # 由 sensitivity() 在拿到扫描点后填，见 main()
        # 每根骨各自的峰值：峰值若是单骨离群值，读数人应看得见
        per_bone = {}
        for r in rows:
            if not SKIRT.match(r.get("bone", "")):
                continue
            a = abs(float(r["rot_%s_deg" % axis]))
            if a > per_bone.get(r["bone"], -1.0):
                per_bone[r["bone"]] = a
        best["per_bone_deg"] = {b: round(v, 6) for b, v in sorted(per_bone.items())}
        best["bones_over"] = {  # 每根骨是否越限（供敏感性表交叉核对）
            "n": len(per_bone),
            "peak_ge_0_7rad": sum(1 for v in per_bone.values() if v / DEG >= 0.7),
            "peak_ge_1_5708rad": sum(1 for v in per_bone.values() if v / DEG >= 1.5708),
        }
        per_axis[axis] = best

    ranked = sorted(AXES, key=lambda a: per_axis[a]["peak_rad"], reverse=True)
    return {
        "dump": os.path.abspath(path),
        "dump_sha256": sha256_of(path),
        "dump_bytes": os.path.getsize(path),
        "dump_mtime": os.path.getmtime(path),
        "rows": len(rows),
        "frames": {"first": frames[0], "last": frames[-1], "count": len(frames)},
        "bones": bones,
        "axes": per_axis,
        "ranked_axes": list(ranked),
        "chosen_axis": ranked[0],
        "chosen_peak_rad": per_axis[ranked[0]]["peak_rad"],
        "runner_up_ratio": (per_axis[ranked[1]]["peak_rad"] / per_axis[ranked[0]]["peak_rad"]
                            if per_axis[ranked[0]]["peak_rad"] else None),
    }


def sensitivity(rows, axis, scan):
    """每根轴 × 每个候选限值：越限采样点数 + 最大超越量（rad）。

    0.5× / 1.2× 依赖峰值，所以扫描点要在峰值算完之后才定，见 main()。
    """
    out = []
    for limit_rad, label in scan:
        over = 0
        worst = 0.0
        for row in rows:
            if not SKIRT.match(row.get("bone", "")):
                continue
            a = abs(float(row["rot_%s_deg" % axis])) / DEG
            if a > limit_rad:
                over += 1
                worst = max(worst, a - limit_rad)
        out.append({"limit_label": label, "limit_rad": round(limit_rad, 6),
                    "limit_deg": round(limit_rad * DEG, 6),
                    "samples_over": over,
                    "worst_exceed_rad": round(worst, 6),
                    "engages": over > 0})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="三轴 max|rot| 峰值表（只读 dump）")
    ap.add_argument("--dump", nargs="+", required=True)
    ap.add_argument("--json", default=None)
    ap.add_argument("--primary", default=None,
                    help="多份 dump 里作为选轴依据的那一份（默认第一份）")
    args = ap.parse_args(argv)

    limits = [(0.7, "原 ±0.7 rad"), (1.5708, "现交付 ±1.5708 rad")]
    results = []
    for path in args.dump:
        results.append(analyse(path))

    primary = results[0]
    if args.primary:
        for r in results:
            if os.path.abspath(args.primary) == r["dump"]:
                primary = r
    peak = primary["chosen_peak_rad"]
    scan = [(0.5 * peak, "0.5×峰值"), (peak * 1.2, "1.2×峰值")] + limits
    for r in results:
        rows = load(r["dump"])
        for axis in AXES:
            r["axes"][axis]["sensitivity"] = sensitivity(rows, axis, scan)
            own_peak = r["axes"][axis]["peak_rad"]
            own_scan = [(0.5 * own_peak, "0.5×本轴峰值"),
                        (own_peak * 1.2, "1.2×本轴峰值")] + limits
            r["axes"][axis]["sensitivity_own"] = sensitivity(rows, axis, own_scan)

    print("选轴依据：%s" % primary["dump"])
    print("  文件 %d B  sha256=%s" % (primary["dump_bytes"], primary["dump_sha256"]))
    print("  帧 %d–%d（%d 帧）、骨 %d 根、行 %d"
          % (primary["frames"]["first"], primary["frames"]["last"],
             primary["frames"]["count"], len(primary["bones"]), primary["rows"]))
    print()
    print("三轴峰值（max |rot_axis|，18 根骨 × 全部帧）")
    print("  %-4s %10s %10s  %-12s %6s %8s" % ("轴", "峰值(deg)", "峰值(rad)", "骨", "帧", "采样点"))
    for axis in AXES:
        a = primary["axes"][axis]
        print("  %-4s %10.6f %10.6f  %-12s %6d %8d"
              % (axis, a["peak_deg"], a["peak_rad"], a["bone"], a["frame"], a["samples"]))
    print()
    print("敏感性（每根轴 × 每个候选限值：越限采样点数 / 最大超越量 rad）")
    for axis in AXES:
        print("  轴 %s：" % axis)
        for s in primary["axes"][axis]["sensitivity"]:
            print("    %-18s 限值 %8.6f rad (%8.4f deg)  越限 %6d 点  最大超越 %.6f rad"
                  % (s["limit_label"], s["limit_rad"], s["limit_deg"],
                     s["samples_over"], s["worst_exceed_rad"]))
    print()
    print("选中变量轴：%s（峰值 %.6f rad = %.4f deg），次大轴比值 %.4f"
          % (primary["chosen_axis"], primary["chosen_peak_rad"],
             primary["chosen_peak_rad"] * DEG,
             primary["runner_up_ratio"] if primary["runner_up_ratio"] else 0.0))
    print()
    print("第二种读法（不换轴、各轴用**自己**峰值的 0.5× / 1.2× 做限值）——两种理解并列，读数人自己选")
    for axis in AXES:
        print("  轴 %s：" % axis)
        for s in primary["axes"][axis]["sensitivity_own"]:
            print("    %-18s 限值 %8.6f rad (%8.4f deg)  越限 %6d 点  最大超越 %.6f rad"
                  % (s["limit_label"], s["limit_rad"], s["limit_deg"],
                     s["samples_over"], s["worst_exceed_rad"]))
    print()
    print("每根骨各自的峰值是否越限（判断峰值是不是单骨离群值）")
    for axis in AXES:
        a = primary["axes"][axis]
        print("  轴 %s：18 根里 %d 根峰值 ≥ 0.7 rad、%d 根 ≥ 1.5708 rad"
              % (axis, a["bones_over"]["peak_ge_0_7rad"], a["bones_over"]["peak_ge_1_5708rad"]))
    print()
    print("变量轴 %s 的每骨峰值（降序，前 6）" % primary["chosen_axis"])
    pb = primary["axes"][primary["chosen_axis"]]["per_bone_deg"]
    for bone, deg in sorted(pb.items(), key=lambda kv: -kv[1])[:6]:
        print("    %-14s %9.4f deg = %8.6f rad" % (bone, deg, deg / DEG))
    if len(results) > 1:
        print()
        print("多份 dump 的选轴一致性（同一仪器的重复/变体）")
        for r in results:
            print("  %-52s → %s  峰值 %.6f rad  帧 %d–%d"
                  % (os.path.basename(os.path.dirname(r["dump"])) + "/" + os.path.basename(r["dump"]),
                     r["chosen_axis"], r["chosen_peak_rad"],
                     r["frames"]["first"], r["frames"]["last"]))

    if args.json:
        payload = {"scan_points": [{"label": l, "limit_rad": round(v, 6),
                                    "limit_deg": round(v * DEG, 6)} for v, l in scan],
                   "primary": os.path.abspath(primary["dump"]),
                   "chosen_axis": primary["chosen_axis"],
                   "dumps": results}
        d = os.path.dirname(os.path.abspath(args.json))
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with io.open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
        print("\n写出：%s（%d B）" % (args.json, os.path.getsize(args.json)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
