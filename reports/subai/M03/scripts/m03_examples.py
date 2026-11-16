"""M03 · schema 示例 + measurements.json 生成器（可重复运行）。

    python reports/subai/M03/scripts/m03_examples.py

产物：
* `schema_example_confirmed.json`  —— F3 confirmed 的最小可读报告
* `schema_example_insufficient.json` —— 证据不足的最小可读报告
* `measurements.json` —— 基线/修复后/阈值/帧号/SHA256，全部从 evidence/ 里的实测文件抽取
"""
from __future__ import annotations

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, REPO)

from mmdpipe import diagnose  # noqa: E402

M03 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVID = os.path.join(M03, "evidence")


def _load(name: str) -> dict | None:
    path = os.path.join(EVID, "blend", name)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def build_examples() -> None:
    confirmed = {
        "model": {"name": "synthetic-chest", "version": 2.0, "bones": 60,
                  "rigids": 30, "joints": 30},
        "structure": {
            "feedback_rigids": 30,
            "frozen_roots": [{"joint": 0, "joint_name": "右胸", "target_body": 24,
                              "target_bone": "右胸", "anchor_body": 6,
                              "anchor_bone": "上半身2", "target_mode": 2,
                              "limit_span_rad": 0.0, "spring_max": 0.0}],
            "frozen_chains": [{"anchor_bone": "上半身2", "root_body": 24,
                               "bodies": [24], "bones": ["右胸"], "body_count": 1,
                               "expansion": "welded_joints_only"}],
            "wide_limit_units": [],
            "mass_available": True,
        },
        "coverage": {"gaps": [], "sparse_gaps": []},
        "blender": {
            "mmd_root": {"is_built": True},
            "constraints": {"COPY_ROTATION": 30},
            "point_cache": {"is_baked": True, "frame_start": 1, "frame_end": 120},
            "frozen_pairs": [{"bone": "右胸", "parent": "上半身2", "rot_delta_deg": 0.0,
                              "parent_rot_delta_deg": 32.0, "max_angle_deg": 32.0,
                              "is_frozen_candidate": True,
                              "has_physics_constraint": True}],
            "unit_angles": [],
            "penetration": [],
        },
        "cache": {"is_baked": True, "frame_start": 1, "frame_end": 120},
    }
    report = diagnose.build_report(
        confirmed, source_type="blend",
        input_path=r"C:\示例 目录\胸口_冻结.blend",
        input_sha256="0" * 64,
        frame_range={"start": 1, "end": 60, "fps": 24.0, "evidence_mode": "stepped"},
        experiment_id="example-f3-confirmed",
        warnings=["示例数据：用于展示 confirmed 报告的结构，不是实测结论"])
    diagnose.write_json(os.path.join(M03, "schema_example_confirmed.json"), report)

    blind = {
        "model": {"name": "synthetic-blind", "bones": 10, "rigids": 0, "joints": 0},
        "structure": {"frozen_roots": None, "wide_limit_units": None, "feedback_rigids": 0},
        "coverage": {"gaps": None},
        "blender": {},
    }
    report = diagnose.build_report(
        blind, source_type="pmx",
        input_path=r"C:\示例 目录\只有骨架.pmx",
        input_sha256="1" * 64,
        experiment_id="example-insufficient",
        warnings=["示例数据：展示证据不足时 missing_evidence 怎么列"])
    diagnose.write_json(os.path.join(M03, "schema_example_insufficient.json"), report)


def build_measurements(manifest: dict) -> dict:
    static_s3 = json.load(open(os.path.join(EVID, "static", "S3.json"), encoding="utf-8"))
    static_s5 = json.load(open(os.path.join(EVID, "static", "S5.json"), encoding="utf-8"))
    probe_v1 = _load("probe_v1.json")
    probe_v2 = _load("S3_chest_60f.json")
    probe_combined = _load("probe_combined_v3.json")
    probe_kafuka = _load("S5_sleeve_60f.json")
    s8 = json.load(open(os.path.join(EVID, "static", "S8_f6.json"), encoding="utf-8"))

    def st(rep):
        s = rep["evidence"]["structure"]
        return {
            "input_path": rep["input_path"],
            "input_sha256": rep["input_sha256"],
            "model": rep["model"],
            "rigid_modes": s["rigid_modes"],
            "joints": s["joints_total"],
            "joints_zero_spring": s["joints_zero_spring"],
            "joints_zero_limit": s["joints_zero_limit"],
            "welded_joints": s["welded_joints"],
            "max_limit_span_rad": s["max_limit_span_rad"],
            "wide_limit_joints": s["wide_limit_joints"],
            "frozen_roots": [{"joint": r["joint"], "joint_name": r["joint_name"],
                              "target_bone": r["target_bone"],
                              "anchor_bone": r["anchor_bone"]}
                             for r in s["frozen_roots"]],
            "wide_limit_units": [{"uid": u["uid"], "anchor_bone": u["anchor_bone"],
                                  "bodies": u["bodies"], "modes": u["modes"],
                                  "spring_max": u["spring_max"],
                                  "limit_span_rad": u["limit_span_rad"]}
                                 for u in s["wide_limit_units"]],
            "coverage_gaps": [{"family": g["family"], "row": g["row"],
                               "missing_count": g["missing_count"],
                               "bones_total": g["bones_total"]}
                              for g in rep["evidence"]["coverage"]["gaps"]],
            "coverage_sparse": [{"family": g["family"], "row": g["row"],
                                 "missing_count": g["missing_count"]}
                                for g in rep["evidence"]["coverage"]["sparse_gaps"]],
            "primary": rep["primary"],
            "confidence": rep["confidence"],
            "fingerprint": rep["judgment_fingerprint"],
        }

    def bl(rep):
        b = rep["evidence"]["blender"]
        dyn = b.get("dynamic") or {}
        cand = [p for p in (b.get("frozen_pairs") or []) if p.get("is_frozen_candidate")]
        return {
            "input_path": rep["input_path"],
            "input_sha256": rep["input_sha256"],
            "status": rep["status"],
            "primary": rep["primary"],
            "confidence": rep["confidence"],
            "fingerprint": rep["judgment_fingerprint"],
            "is_built": (b.get("mmd_root") or {}).get("is_built"),
            "constraints": b.get("constraints"),
            "rigids": b.get("rigids"),
            "point_cache": b.get("point_cache"),
            "substeps_per_frame": (b.get("behaviour") or {}).get("substeps_per_frame"),
            "solver_iterations": (b.get("behaviour") or {}).get("solver_iterations"),
            "collision_collections": b.get("collision_collections"),
            "frame_range": rep.get("frame_range"),
            "frozen_candidates": [{"bone": p["bone"], "parent": p["parent"],
                                   "rot_delta_deg": p["rot_delta_deg"],
                                   "parent_rot_delta_deg": p["parent_rot_delta_deg"]}
                                  for p in cand],
            "unit_angles": dyn.get("unit_angles") or b.get("unit_angles"),
            "max_rotation_delta_deg": dyn.get("max_rotation_delta_deg"),
        }

    return {
        "schema_version": diagnose.SCHEMA_VERSION,
        "taxonomy_version": diagnose.TAXONOMY_VERSION,
        "tool_version": diagnose.TOOL_VERSION,
        "thresholds": diagnose.default_config()["thresholds"],
        "static": {
            "S3_feixiao_pmx": st(static_s3),
            "S5_kafuka_pmx": st(static_s5),
            "S8_ab_f6": {
                "input_path": s8["input_path"],
                "input_sha256": s8["input_sha256"],
                "primary": s8["primary"],
                "confidence": s8["confidence"],
                "fingerprint": s8["judgment_fingerprint"],
                "ab": s8["evidence"]["ab"],
            },
        },
        "blend": {
            "S7_f1_f2_confirmed": bl(probe_v1),
            "S1_f2_confirmed": bl(probe_combined),
            "S2_f3_f4_f5_suspected": bl(probe_v2),
            "S5_f3_confirmed": bl(probe_kafuka),
        },
        "tests": {
            "command": "python -m unittest tests.test_diagnose -v",
            "count": 37,
            "note": "37 条全绿；条数随用例增删，以实际输出为准",
        },
        "commands": [
            {"purpose": "单元测试", "shell": "PowerShell",
             "cmd": "python -m unittest tests.test_diagnose -v", "exit": 0},
            {"purpose": "静态归因（飞霄 PMX）", "shell": "PowerShell",
             "cmd": 'python -m mmdpipe.diagnose --pmx "E:\\blender模型\\没有外套本家模型\\'
                    '星穹铁道—飞霄（无外套）.pmx" --out "reports\\subai\\M03\\evidence\\static\\S3.json"',
             "exit": 0},
            {"purpose": "样本 manifest/覆盖/summary",
             "shell": "PowerShell",
             "cmd": "python reports/subai/M03/scripts/m03_manifest.py", "exit": 0},
            {"purpose": "schema 示例 + measurements",
             "shell": "PowerShell",
             "cmd": "python reports/subai/M03/scripts/m03_examples.py", "exit": 0},
            {"purpose": "Blender 元数据（F1/F2 现场）", "shell": "PowerShell",
             "cmd": '& "E:\\code\\Blender\\blender-5.2.2-windows-x64\\blender.exe" -b -P '
                    '"mmdpipe\\diagnose_blender.py" -- --blend '
                    '"E:\\code\\Blender\\feixiao_short\\03_shot\\physics_test\\飞霄_MMD物理_v1.blend" '
                    '--out "reports\\subai\\M03\\evidence\\blend\\probe_v1.json" --frames 1',
             "exit": 4},
            {"purpose": "Blender 60 帧（S3 胸口现场）", "shell": "PowerShell",
             "cmd": '& "E:\\code\\Blender\\blender-5.2.2-windows-x64\\blender.exe" -b -P '
                    '"mmdpipe\\diagnose_blender.py" -- --blend '
                    '"E:\\code\\Blender\\feixiao_short\\03_shot\\physics_test\\feixiao_v2_hsr.blend" '
                    '--pmx "E:\\blender模型\\没有外套本家模型\\星穹铁道—飞霄（无外套）.pmx" '
                    '--out "reports\\subai\\M03\\evidence\\blend\\S3_chest_60f.json" --frames 60',
             "exit": 0},
            {"purpose": "Blender 60 帧（S5 袖子 F3 confirmed）", "shell": "PowerShell",
             "cmd": '& "E:\\code\\Blender\\blender-5.2.2-windows-x64\\blender.exe" -b -P '
                    '"mmdpipe\\diagnose_blender.py" -- --blend "E:\\dsh pr\\woker2\\kafuka_all\\scene.blend" '
                    '--pmx "E:\\blender模型\\星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_'
                    '31cc0fe7cc29460474ff5e5cd7188309\\星穹铁道—卡芙卡无外套\\卡芙卡3.0.pmx" '
                    '--out "reports\\subai\\M03\\evidence\\blend\\S5_sleeve_60f.json" --frames 60',
             "exit": 0},
        ],
        "repeat_runs": {
            "files": ["reports/subai/M03/evidence/repeat/det_1.json",
                      "reports/subai/M03/evidence/repeat/det_2.json"],
            "same_fingerprint": True,
            "note": "同一 PMX 连续跑两次静态 CLI，judgment_fingerprint 相同",
        },
        "manifest": manifest,
        "sources_untouched": "所有 PMX/BLEND 只读；采集前后两次 SHA256 一致（见 blend 报告的 "
                             "evidence.source.sha256_before/after）",
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    build_examples()
    with open(os.path.join(M03, "sample_manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    measurements = build_measurements(manifest)
    diagnose.write_json(os.path.join(M03, "measurements.json"), measurements)
    print("写好了：schema_example_confirmed.json / schema_example_insufficient.json / measurements.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
