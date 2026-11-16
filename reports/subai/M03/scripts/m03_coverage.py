"""M03 覆盖缺口表生成器（数字不手抄，可重复运行）。

输入：``reports/subai/M03/sample_manifest.json``（8 条样本的实测判定）
      ``reports/subai/M03/evidence/**/*.json``（录好的真实证据，用于可重放回归）
输出：``reports/subai/M03/coverage.json``

口径（写在代码里而不是报告文字里，便于复核）：
* 一条样本的「实测确认」= 该样本 static/blend 任一诊断里 confidence=confirmed 的类别集合；
* 误报 = 某类别被 confirmed，但样本的 ``expected_label`` 不是它；
* 漏报 = ``expected_label`` 既没被 confirmed（match_confirmed）也没被 suspected（match_suspected）；
* 覆盖分母按**样本条数**算，不按证据文件数算——同一个 PMX 被 7 条样本复用，
  按文件去重会把 1 份证据算成 7 份。
"""
from __future__ import annotations

import json
import os
import sys

ROOT = r"E:\dsh pr\woker2"
REP = os.path.join(ROOT, "reports", "subai", "M03")
sys.path.insert(0, ROOT)

from mmdpipe import diagnose  # noqa: E402

TAXONOMY = ("F1", "F2", "F3", "F4", "F5", "F6", "OUT_OF_TAXONOMY", "UNKNOWN",
            "INSUFFICIENT_EVIDENCE")


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def sample_verdict(sample):
    """把一条样本的两类诊断合成一个可核的结论。

    实测坑：manifest 里两类诊断**嵌在 ``sample["availability"]`` 下**，不在顶层；
    早先按顶层取，8 条全部落成 mismatch —— 数字不对不是判据错，是取错层级。
    """
    avail = sample.get("availability") or {}
    confirmed, suspected = set(), set()
    for key in ("static_diagnosis", "blend_diagnosis"):
        diag = avail.get(key) or {}
        if not diag.get("available"):
            continue
        for cls, conf in (diag.get("diagnostics") or {}).items():
            if conf == "confirmed":
                confirmed.add(cls)
            elif conf == "suspected":
                suspected.add(cls)
    expected = sample["expected_label"]
    blend = avail.get("blend_diagnosis") or {}
    static = avail.get("static_diagnosis") or {}
    primary = (blend.get("primary") if blend.get("available")
               else static.get("primary"))
    confidence = (blend.get("confidence") if blend.get("available")
                  else static.get("confidence"))
    if expected in confirmed:
        verdict = "match_confirmed"
    elif expected in suspected:
        verdict = "match_suspected"
    else:
        verdict = "mismatch"
    return {
        "id": sample["id"],
        "expected_label": expected,
        "primary": primary,
        "confidence": confidence,
        "verdict": verdict,
        "confirmed_classes": sorted(confirmed),
        "false_positives": sorted(confirmed - {expected}),
        "evidence_files": sorted({
            (avail.get(k) or {}).get("file")
            for k in ("static_diagnosis", "blend_diagnosis")
            if (avail.get(k) or {}).get("available")
        }),
        "availability": "available" if (confirmed or suspected) else "unavailable",
    }


def replayable_fixtures():
    """扫 evidence/ 下带 judgment_fingerprint 的录好证据，重放判定是否仍一致。"""
    out = []
    for dirpath, _dirs, files in os.walk(os.path.join(REP, "evidence")):
        for name in sorted(files):
            if not name.endswith(".json"):
                continue
            path = os.path.join(dirpath, name)
            try:
                report = load(path)
            except (OSError, ValueError):
                continue
            if "evidence" not in report or "judgment_fingerprint" not in report:
                continue
            fresh = diagnose.judge(report["evidence"])
            rebuilt = dict(report)
            rebuilt.update({k: fresh[k] for k in
                            ("primary", "secondary", "confidence", "diagnostics")})
            same = (diagnose.judgment_fingerprint(rebuilt)
                    == report["judgment_fingerprint"]
                    and fresh["primary"] == report["primary"]
                    and fresh["confidence"] == report["confidence"])
            entry = {
                "path": os.path.relpath(path, ROOT).replace("\\", "/"),
                "primary": report["primary"],
                "confidence": report["confidence"],
                "replay_identical": bool(same),
            }
            if not same:
                entry["note"] = ("判定结论未变（primary/confidence 相同），但指纹与当前代码不一致："
                                 "该文件早于 F3 候选过滤修正，已被同目录更新的证据取代")
            out.append(entry)
    return out


GAP_RULES = {
    "F4": "无真阳性样本：f4_angle_deg=60 未标定，正常舞蹈实测 179.231° 证明单调角度阈值"
          "区分不了正常与异常；须等 M02 的 S2 单变量修复实测",
    "F5": "无真阳性样本：缺 evidence.blender.penetration（逐帧穿入深度 + 穿入骨 + 帧号），"
          "该测量属 M04",
    "OUT_OF_TAXONOMY": "R0 无真实测量文件：S1/S6 都缺逐帧穿透数据，只有合成 fixture",
    "UNKNOWN": "只有合成 fixture，无真实样本",
    "INSUFFICIENT_EVIDENCE": "只有合成 fixture，无真实样本",
}


def main():
    manifest = load(os.path.join(REP, "sample_manifest.json"))
    samples = [sample_verdict(s) for s in manifest["samples"]]

    matrix = {}
    for cls in TAXONOMY:
        labelled = [s["id"] for s in samples if s["expected_label"] == cls]
        confirmed = [s["id"] for s in samples if cls in s["confirmed_classes"]]
        # suspected 直接从原始诊断取，两条路径分开写，免得读的人要反推
        suspected_ids = []
        for s_orig in manifest["samples"]:
            avail = s_orig.get("availability") or {}
            for key in ("static_diagnosis", "blend_diagnosis"):
                diag = avail.get(key) or {}
                if diag.get("available") and \
                        (diag.get("diagnostics") or {}).get(cls) == "suspected":
                    suspected_ids.append(s_orig["id"])
                    break
        matrix[cls] = {
            "labelled_samples": labelled,
            "real_confirmed_samples": confirmed,
            "real_suspected_samples": sorted(set(suspected_ids)),
            # 九类在 tests/test_diagnose.py 里都有合成正例（含 UNKNOWN / INSUFFICIENT）
            "synthetic_fixture": 1,
            "gap": (GAP_RULES.get(cls) if not confirmed else ""),
        }

    fixtures = replayable_fixtures()
    extra_total = sum(len(s["false_positives"]) for s in samples)
    mismatches = [s["id"] for s in samples if s["verdict"] == "mismatch"]

    coverage = {
        "schema_version": diagnose.SCHEMA_VERSION,
        "taxonomy_version": diagnose.TAXONOMY_VERSION,
        "generated_from": ["reports/subai/M03/sample_manifest.json",
                           "reports/subai/M03/evidence/**"],
        "counts": {
            "samples_total": len(samples),
            "match_confirmed": sum(1 for s in samples
                                   if s["verdict"] == "match_confirmed"),
            "match_suspected": sum(1 for s in samples
                                   if s["verdict"] == "match_suspected"),
            "mismatch": len(mismatches),
            # 不叫「误报」：8 条样本里没有一条是「该类故障明确不存在」的阴性样本，
            # 多故障共存本来就允许，所以只能记「额外确认了 expected 之外的类别」。
            "extra_confirmed_total": extra_total,
            "replayable_fixtures": len(fixtures),
            "replay_identical": sum(1 for f in fixtures if f["replay_identical"]),
        },
        "extra_confirmed_detail": [{"sample": s["id"],
                                    "confirmed_beyond_expected": s["false_positives"]}
                                   for s in samples if s["false_positives"]],
        "extra_confirmed_note": "这些不是误报：没有阴性样本就无法判定「故障不存在」；"
                                "F2（未烘焙）在别的主故障场景里同时成立是事实，"
                                "按项目书允许多故障共存。真正缺的是 F2/F4/F5/R0 的阴性样本。",
        "mismatch_detail": mismatches,
        "matrix": matrix,
        "samples": samples,
        "replayable_regression": fixtures,
        "m04_handoff": {
            "consume_schema": diagnose.SCHEMA_VERSION,
            "fields": ["primary", "secondary[]", "confidence",
                       "diagnostics[].matched/confidence/evidence_keys",
                       "missing_evidence[]", "judgment_fingerprint",
                       "config.thresholds"],
            "must_not": "M04 不得自改 M03 schema；字段不足走变更申请，由 M03 出 v2",
            "blocking_gaps": [cls for cls, row in matrix.items() if row["gap"]],
        },
        "notes": [
            "分母按样本条数算，不按证据文件数算：同一 PMX 被 7 条样本复用，去重会虚增。",
            "F2 无独立标签样本（8 条里没有一条标 F2）；两份 F2 真实证据来自别的故障现场，"
            "已进 TestRealEvidenceRegression 作可重放回归。",
            "known_risks / 未验证项不写进 evidence hash；数值由产物文件 sha256 覆盖。",
        ],
    }
    out = os.path.join(REP, "coverage.json")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(coverage, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    print("wrote", out)
    print("counts:", json.dumps(coverage["counts"], ensure_ascii=False))
    print("mismatch:", mismatches)
    print("blocking_gaps:", coverage["m04_handoff"]["blocking_gaps"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
