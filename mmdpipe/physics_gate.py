"""M04 · 物理量化门禁求值器（纯 Python，不 import bpy）。

三类门禁：动力学过冲 / 冻结 / 穿透。输入是**测量 JSON**（measurement）与可选的
M03 `diagnose/1` 报告（diagnosis），阈值全部来自外置 profile，代码里不出现任何
样本专用数字。

判定语义
--------
* 门禁判的是**物理质量**：`PASS` = 没抓到这类问题。
* 三类门禁各自独立求值，最后聚合；**一个门禁 UNKNOWN 不会被别的 PASS 淹没**。
  聚合只在 `PASS / FAIL / UNKNOWN` 三级之间发生，优先级 `FAIL > UNKNOWN > PASS`；
  `OUT_OF_SCOPE` 在聚合前被排除（三类全范围外时结果为 `UNKNOWN`）。
  **`ERROR` 不是聚合结果**：它是 `GateInputError` 异常，一路冒到 `main()` 返回
  退出码 2 且**不产出任何 gate JSON**。消费方只能看退出码，别写「ERROR 状态」的解析分支
  ——那条分支永远到不了。
* 缺字段一律 `UNKNOWN`，不当 PASS —— 这是本模块最容易写错、也最贵的一处。

状态与退出码
------------
`PASS=0 / FAIL=1 / 输入或配置 ERROR=2 / UNKNOWN=3`（写进 `main()`，给 M07 接线用）。

符号约定（与历史数据一致，别猜）
--------------------------------
`penetration.max_depth_m` **负值表示穿入**（M04 任务书 §2：历史 f150 最深
-0.202 m）。epsilon 以绝对值比较：`max_depth_m <= -epsilon` 判穿入。

探索性声明
----------
默认 profile 是 `exploratory_v0`：M01/M02 的实测尚未验收，任何阈值都还不能当生产
门限。结果里带 `profile_status`，消费方必须能看到「探索性」这三个字。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

GATE_VERSION = "physics_gate/1"

PASS, FAIL, UNKNOWN, ERROR = "PASS", "FAIL", "UNKNOWN", "ERROR"
EXIT_PASS, EXIT_FAIL, EXIT_ERROR, EXIT_UNKNOWN = 0, 1, 2, 3

OVERVIEW = ("overshoot", "frozen", "penetration")


class GateInputError(ValueError):
    """输入或配置不可用：返回 ERROR，不猜。"""


def _num(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GateInputError("%s 必须是数值，收到 %r" % (field, value))
    if value != value or value in (float("inf"), float("-inf")):
        raise GateInputError("%s 不能是 NaN/Inf" % field)
    return float(value)


def _int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise GateInputError("%s 必须是整数，收到 %r" % (field, value))
    return int(value)


def _section(measurement, name):
    """取一段测量；没有或为 null → None（调用方判 UNKNOWN）。"""
    if not isinstance(measurement, dict):
        raise GateInputError("measurement 必须是对象")
    return measurement.get(name)


def _result(gate, status, reason, evidence=None, missing=None):
    return {
        "gate": gate,
        "status": status,
        "reason": reason,
        "evidence": evidence or {},
        "missing": sorted(missing or []),
    }


def _frames_ok(measurement, cfg, gate):
    frames = measurement.get("frames") or {}
    start, end = frames.get("start"), frames.get("end")
    if start is None or end is None:
        return False, "frames.start/frames.end"
    span = _int(end, "frames.end") - _int(start, "frames.start") + 1
    need = int(cfg.get("min_frames", 1))
    if span < need:
        return False, "帧数不足：span=%d < min_frames=%d" % (span, need)
    return True, span


# ---------------------------------------------------------------- 三类门禁
def gate_overshoot(measurement, cfg):
    """动力学过冲：robust 统计 + 绝对幅值下限，防安静动作被 median≈0 放大。"""
    dyn = _section(measurement, "dynamics")
    if dyn is None:
        return _result("overshoot", UNKNOWN, "缺 dynamics 段",
                       missing=["dynamics"])
    missing = [k for k in ("median", "p95", "max", "spike_count") if k not in dyn]
    if missing:
        return _result("overshoot", UNKNOWN,
                       "dynamics 缺字段：" + ", ".join(missing),
                       missing=["dynamics." + m for m in missing])
    median = _num(dyn["median"], "dynamics.median")
    p95 = _num(dyn["p95"], "dynamics.p95")
    peak = _num(dyn["max"], "dynamics.max")
    spikes = _int(dyn["spike_count"], "dynamics.spike_count")
    bones = _int(dyn.get("bones", 0), "dynamics.bones")

    ok, span = _frames_ok(measurement, cfg, "overshoot")
    if not ok:
        return _result("overshoot", UNKNOWN, span, missing=["frames"])
    if bones < int(cfg.get("min_bones", 1)):
        return _result("overshoot", UNKNOWN,
                       "测量骨数 %d < min_bones %d" % (bones, cfg.get("min_bones", 1)),
                       missing=["dynamics.bones"])

    p95_max = float(cfg["p95_max_deg"])
    floor = float(cfg["max_abs_floor_deg"])
    spike_max = int(cfg["spike_count_max"])
    evid = {"median_deg": median, "p95_deg": p95, "max_deg": peak,
            "spike_count": spikes, "bones": bones, "frames": span,
            "p95_max_deg": p95_max, "max_abs_floor_deg": floor,
            "spike_count_max": spike_max}
    if p95 > p95_max and peak > floor:
        return _result("overshoot", FAIL,
                       "p95 %.3f° > %.3f° 且峰值 %.3f° 超过绝对下限 %.3f°"
                       % (p95, p95_max, peak, floor), evid)
    if spikes > spike_max:
        return _result("overshoot", FAIL,
                       "尖峰帧 %d > 允许 %d" % (spikes, spike_max), evid)
    return _result("overshoot", PASS,
                   "p95 %.3f° ≤ %.3f°，尖峰 %d ≤ %d" % (p95, p95_max, spikes, spike_max),
                   evid)


def gate_frozen(measurement, cfg):
    """冻结：父链确实在动，而目标相对增量近零，且**持续**多帧。"""
    frz = _section(measurement, "frozen")
    if frz is None:
        return _result("frozen", UNKNOWN, "缺 frozen 段", missing=["frozen"])
    missing = [k for k in ("parent_delta_deg", "target_delta_deg", "consecutive_frames")
               if k not in frz]
    if missing:
        return _result("frozen", UNKNOWN, "frozen 缺字段：" + ", ".join(missing),
                       missing=["frozen." + m for m in missing])
    parent = _num(frz["parent_delta_deg"], "frozen.parent_delta_deg")
    target = _num(frz["target_delta_deg"], "frozen.target_delta_deg")
    streak = _int(frz["consecutive_frames"], "frozen.consecutive_frames")

    ok, span = _frames_ok(measurement, cfg, "frozen")
    if not ok:
        return _result("frozen", UNKNOWN, span, missing=["frames"])

    parent_min = float(cfg["parent_delta_min_deg"])
    target_max = float(cfg["target_delta_max_deg"])
    need_streak = int(cfg["min_consecutive_frames"])
    evid = {"parent_delta_deg": parent, "target_delta_deg": target,
            "consecutive_frames": streak, "frames": span,
            "parent_delta_min_deg": parent_min, "target_delta_max_deg": target_max,
            "min_consecutive_frames": need_streak}
    if parent < parent_min:
        return _result("frozen", PASS,
                       "父链只动了 %.3f° < %.3f°：本来就不该动，不判冻结"
                       % (parent, parent_min), evid)
    if target > target_max:
        return _result("frozen", PASS,
                       "目标相对动了 %.3f° > %.3f°：没冻结" % (target, target_max), evid)
    if streak < need_streak:
        return _result("frozen", PASS,
                       "零变化只持续 %d 帧 < %d 帧：单帧不算冻结" % (streak, need_streak),
                       evid)
    return _result("frozen", FAIL,
                   "父链动 %.3f° 而目标只动 %.3f°，连续 %d 帧：判冻结"
                   % (parent, target, streak), evid)


def gate_penetration(measurement, cfg):
    """穿透：按 ROI 统计穿入深度、帧数、骨次。负值表示穿入。"""
    pen = _section(measurement, "penetration")
    if pen is None:
        return _result("penetration", UNKNOWN, "缺 penetration 段（需 Blender 逐帧测量）",
                       missing=["penetration"])
    missing = [k for k in ("max_depth_m", "frames", "bones") if k not in pen]
    if missing:
        return _result("penetration", UNKNOWN, "penetration 缺字段：" + ", ".join(missing),
                       missing=["penetration." + m for m in missing])
    depth = _num(pen["max_depth_m"], "penetration.max_depth_m")
    frames = _int(pen["frames"], "penetration.frames")
    bones = _int(pen["bones"], "penetration.bones")
    roi = pen.get("roi")
    if roi is None:
        # ROI 缺失时深度数字没有归属，不能拿来判合格
        return _result("penetration", UNKNOWN, "缺 ROI：深度数字无归属",
                       missing=["penetration.roi"])

    eps = float(cfg["depth_epsilon_m"])
    min_frames = int(cfg.get("min_frames", 1))
    evid = {"roi": roi, "max_depth_m": depth, "frames": frames, "bones": bones,
            "epsilon_m": eps, "sign_convention": cfg.get("sign_convention",
                                                          "negative_depth_is_penetration")}
    if frames < min_frames or bones < int(cfg.get("min_bones", 1)):
        return _result("penetration", UNKNOWN,
                       "帧数 %d / 骨次 %d 不足以判定" % (frames, bones),
                       missing=["penetration.frames", "penetration.bones"])
    if depth <= -eps:
        return _result("penetration", FAIL,
                       "ROI %s 最深穿入 %.4f m，超过 epsilon %.4f m" % (roi, depth, eps),
                       evid)
    return _result("penetration", PASS,
                   "ROI %s 最深 %.4f m，未超过 epsilon %.4f m" % (roi, depth, eps), evid)


GATES = {
    "overshoot": gate_overshoot,
    "frozen": gate_frozen,
    "penetration": gate_penetration,
}


# ---------------------------------------------------------------- 配置与聚合
def load_profile(path):
    try:
        with open(path, encoding="utf-8") as fh:
            profile = json.load(fh)
    except OSError as exc:
        raise GateInputError("配置读取失败：%s" % exc)
    except ValueError as exc:
        raise GateInputError("配置不是合法 JSON：%s" % exc)
    for key in ("profile_id", "threshold_version", "gates"):
        if key not in profile:
            raise GateInputError("配置缺字段：%s" % key)
    for gate in GATES:
        if gate not in profile["gates"]:
            raise GateInputError("配置缺门禁：%s" % gate)
    return profile


def evaluate(measurement, profile, diagnosis=None, evidence_paths=None):
    """对一条测量求值；diagnosis 只作附注，不参与门禁（M04 不改 M03 判据）。

    `measurement["out_of_scope"]` 可以列出**本模块口径之外**的门禁，例如 S1/S6 的 Bullet
    初始穿透 R0 不属于过冲/冻结/穿透三类——按 M04 §6.F.1 必须标 `OUT_OF_SCOPE`，不能
    因为「它这一条没数据」就整条样本判 UNKNOWN，更不能算 PASS。
    """
    if not isinstance(profile, dict) or "gates" not in profile:
        raise GateInputError("profile 不可用")
    scope = measurement.get("out_of_scope") or []
    if isinstance(scope, str):
        scope = [scope]
    unknown_scope = [g for g in scope if g not in GATES]
    if unknown_scope:
        raise GateInputError("out_of_scope 里有未知门禁：%s" % ", ".join(unknown_scope))

    results = {}
    for name, fn in GATES.items():
        if name in scope:
            results[name] = _result(name, "OUT_OF_SCOPE",
                                    "该样本的这一类不在本模块口径内（R0 等）",
                                    missing=[])
            continue
        results[name] = fn(measurement, profile["gates"][name])

    statuses = [r["status"] for r in results.values() if r["status"] != "OUT_OF_SCOPE"]
    if FAIL in statuses:
        status = FAIL
    elif UNKNOWN in statuses:
        status = UNKNOWN
    elif not statuses:
        # 三类门禁全被声明为范围外：没有任何一条门禁支持 PASS
        status = UNKNOWN
    else:
        status = PASS

    out = {
        "gate_version": GATE_VERSION,
        "profile_id": profile["profile_id"],
        "profile_status": profile.get("status", "unknown"),
        "threshold_version": profile["threshold_version"],
        "sample_id": (measurement or {}).get("sample_id"),
        "evidence_mode": (measurement or {}).get("evidence_mode"),
        "status": status,
        "failed_gates": sorted(k for k, r in results.items() if r["status"] == FAIL),
        "unknown_gates": sorted(k for k, r in results.items() if r["status"] == UNKNOWN),
        "out_of_scope_gates": sorted(k for k, r in results.items()
                                     if r["status"] == "OUT_OF_SCOPE"),
        "gate_results": results,
        "evidence_paths": list(evidence_paths or []),
        "warnings": [],
        "diagnosis_ref": None,
    }
    if isinstance(diagnosis, dict):
        out["diagnosis_ref"] = {
            "schema_version": diagnosis.get("schema_version"),
            "primary": diagnosis.get("primary"),
            "confidence": diagnosis.get("confidence"),
            "judgment_fingerprint": diagnosis.get("judgment_fingerprint"),
        }
    if out["profile_status"] != "production":
        out["warnings"].append(
            "profile_status=%s：阈值未经生产标定，结论只能当探索性证据"
            % out["profile_status"])
    return out


def exit_code_for(status):
    return {"PASS": EXIT_PASS, "FAIL": EXIT_FAIL,
            "UNKNOWN": EXIT_UNKNOWN, "ERROR": EXIT_ERROR}[status]


# ---------------------------------------------------------------- CLI
def build_parser():
    p = argparse.ArgumentParser(
        description="M04 物理量化门禁（过冲 / 冻结 / 穿透）")
    p.add_argument("--measurement", required=True, help="测量 JSON（只读）")
    p.add_argument("--profile", default=os.path.join(
        "presets", "physics_gate", "exploratory_v0.json"), help="门限配置 JSON")
    p.add_argument("--diagnosis", help="可选：M03 diagnose/1 报告 JSON（只作附注）")
    p.add_argument("--out", help="输出 JSON（默认只写 stdout）")
    return p


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = build_parser().parse_args(argv)
    try:
        with open(args.measurement, encoding="utf-8") as fh:
            measurement = json.load(fh)
    except (OSError, ValueError) as exc:
        sys.stderr.write("测量文件不可读：%s\n" % exc)
        return EXIT_ERROR
    try:
        profile = load_profile(args.profile)
    except GateInputError as exc:
        sys.stderr.write("配置不可用：%s\n" % exc)
        return EXIT_ERROR
    diagnosis = None
    if args.diagnosis:
        try:
            with open(args.diagnosis, encoding="utf-8") as fh:
                diagnosis = json.load(fh)
        except (OSError, ValueError) as exc:
            sys.stderr.write("诊断文件不可读：%s\n" % exc)
            return EXIT_ERROR
    try:
        report = evaluate(measurement, profile, diagnosis,
                          evidence_paths=[args.measurement])
    except GateInputError as exc:
        sys.stderr.write("输入不可用：%s\n" % exc)
        return EXIT_ERROR

    blob = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
            with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(blob + "\n")
        except OSError as exc:
            sys.stderr.write("输出写入失败：%s\n" % exc)
            return EXIT_ERROR
    sys.stdout.write("%s %s failed=%s unknown=%s\n" % (
        report["sample_id"], report["status"],
        ",".join(report["failed_gates"]) or "-",
        ",".join(report["unknown_gates"]) or "-"))
    return exit_code_for(report["status"])


if __name__ == "__main__":
    raise SystemExit(main())
