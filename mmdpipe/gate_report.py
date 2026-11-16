"""M04 · 批量门禁 + 混淆矩阵（纯 Python）。

为什么要单独一层
----------------
单条样本的 `physics_gate.evaluate()` 只能回答「这条过不过」。M04 验收要的是
「好样本 pass、坏样本 fail」的**统计**，并且必须避免两件蠢事：

1. 用同一批样本既标定又验证 → 虚假 100%（任务书 §6.A.4 明令要留 holdout）；
2. 把 `UNKNOWN` 当 `PASS` 或当 `FAIL` 塞进混淆矩阵 → 分母被污染。
   本模块把 `UNKNOWN` **单列**，`误报率/漏报率` 只用「有明确结论」的样本做分母，
   并在结果里写明被排除了几条。缺数据不是结论。

数据结构
--------
record = {"sample_id", "expected": "PASS"|"FAIL", "measurement": <dict>, "split": "calibration"|"holdout"}
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import physics_gate as pg

REPORT_VERSION = "gate_report/1"


class ReportError(ValueError):
    """输入不足以出报告：如实说，不凑数字。"""


def _status_of(measurement, profile):
    return pg.evaluate(measurement, profile)["status"]


def _count(records, profile, split):
    rows = []
    for rec in records:
        if rec["split"] != split:
            continue
        status = _status_of(rec["measurement"], profile)
        rows.append({
            "sample_id": rec["sample_id"],
            "expected": rec["expected"],
            "status": status,
            "split": split,
        })
    return rows


def _matrix(rows):
    """positive = 坏样本（expected FAIL）。UNKNOWN 单列，不进 TP/FP/TN/FN。"""
    tp = fp = tn = fn = unknown = 0
    detail = []
    for row in rows:
        expected, status = row["expected"], row["status"]
        if status == pg.UNKNOWN:
            unknown += 1
            verdict = "unknown"
        elif expected == "FAIL" and status == pg.FAIL:
            tp += 1
            verdict = "tp"
        elif expected == "FAIL":
            fn += 1
            verdict = "fn"
        elif status == pg.FAIL:
            fp += 1
            verdict = "fp"
        else:
            tn += 1
            verdict = "tn"
        detail.append(dict(row, verdict=verdict))
    good = fp + tn
    bad = tp + fn
    out = {
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "unknown": unknown,
        "conclusive": good + bad,
        "false_positive_rate": (fp / good) if good else None,
        "false_negative_rate": (fn / bad) if bad else None,
        "rates_note": ("误报率/漏报率的分母只数「有明确结论」的样本；"
                       "UNKNOWN 单列，不进分母、也不当作正确"),
        "detail": detail,
    }
    return out


def build_report(records, profile):
    if not records:
        raise ReportError("没有任何样本记录")
    splits = {r["split"] for r in records}
    if "calibration" not in splits or "holdout" not in splits:
        raise ReportError(
            "缺 calibration 或 holdout 划分：同一批样本既标定又验证会得到虚假 100%%，"
            "M04 §6.A.4 不允许。请显式给 split")
    calib = _count(records, profile, "calibration")
    hold = _count(records, profile, "holdout")
    return {
        "report_version": REPORT_VERSION,
        "gate_version": pg.GATE_VERSION,
        "profile_id": profile["profile_id"],
        "profile_status": profile.get("status", "unknown"),
        "threshold_version": profile["threshold_version"],
        "calibration": _matrix(calib),
        "holdout": _matrix(hold),
        "exploratory": profile.get("status") != "production",
        "conclusion": ("探索性结论：阈值未标定，holdout 只作一次检查，不得宣称生产级误判率"
                       if profile.get("status") != "production"
                       else "按冻结阈值给出"),
    }


def _load_records(spec_path):
    """spec: {"records": [{"sample_id","expected","split","measurement": path}]}"""
    try:
        with open(spec_path, encoding="utf-8") as fh:
            spec = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ReportError("spec 读取失败：%s" % exc)
    if "records" not in spec:
        raise ReportError("spec 缺 records")
    base = os.path.dirname(os.path.abspath(spec_path))
    out = []
    for item in spec["records"]:
        for key in ("sample_id", "expected", "split", "measurement"):
            if key not in item:
                raise ReportError("record 缺字段：%s" % key)
        if item["expected"] not in ("PASS", "FAIL"):
            raise ReportError("expected 只能是 PASS / FAIL：%r" % item["expected"])
        if item["split"] not in ("calibration", "holdout"):
            raise ReportError("split 只能是 calibration / holdout：%r" % item["split"])
        path = item["measurement"]
        if not os.path.isabs(path):
            path = os.path.join(base, path)
        try:
            with open(path, encoding="utf-8") as fh:
                measurement = json.load(fh)
        except (OSError, ValueError) as exc:
            raise ReportError("measurement 读取失败（%s）：%s" % (item["sample_id"], exc))
        out.append({"sample_id": item["sample_id"], "expected": item["expected"],
                    "split": item["split"], "measurement": measurement})
    return out


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description="M04 批量门禁 + 混淆矩阵")
    p.add_argument("--spec", required=True, help="样本清单 JSON（含 split 与 measurement 路径）")
    p.add_argument("--profile", default=os.path.join(
        "presets", "physics_gate", "exploratory_v0.json"))
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    try:
        profile = pg.load_profile(args.profile)
        records = _load_records(args.spec)
        report = build_report(records, profile)
    except (OSError, ValueError) as exc:
        sys.stderr.write("无法出报告：%s\n" % exc)
        return 2
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    cal, hold = report["calibration"], report["holdout"]
    sys.stdout.write("calibration tp=%d fp=%d tn=%d fn=%d unknown=%d | "
                     "holdout tp=%d fp=%d tn=%d fn=%d unknown=%d\n" % (
                         cal["tp"], cal["fp"], cal["tn"], cal["fn"], cal["unknown"],
                         hold["tp"], hold["fp"], hold["tn"], hold["fn"], hold["unknown"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
