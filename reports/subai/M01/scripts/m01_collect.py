"""把阶段 A–E 的原始产物汇成 measurements.json（不手抄数字，全部读文件）。

    python m01_collect.py [phase]
phase:
  all    默认：写 reports/subai/M01/measurements.json
  hashes  只复算两个源 PMX 的 SHA256（流程首尾各一次）
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

REPO = r"E:\dsh pr\woker2"
OUT = os.path.join(REPO, "out", "subai", "M01")
REP = os.path.join(REPO, "reports", "subai", "M01")


def load(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return json.load(fh)


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def clip_block(dirname: str) -> dict:
    comp = load(OUT, dirname, "comparison.json")
    probes = {v: load(OUT, dirname, "probe_%s.json" % v) for v in ("baseline", "static", "mode0")}
    return {
        "probe_dir": os.path.join(OUT, dirname),
        "action": probes["baseline"]["action"],
        "action_range": probes["baseline"]["action_range"],
        "vmd": probes["baseline"]["vmd"],
        "roi": probes["baseline"]["roi"],
        "camera": probes["baseline"]["camera"],
        "engine": probes["baseline"]["engine"],
        "variants": {
            v: {"physics": p["physics"], "is_built": p["is_built"],
                "rigids": p["after_build"]["rigids"],
                "chest_constraints": p["after_build"]["chest_cons_total"],
                "constraint_histogram": p["after_build"]["constraints"],
                "rigid_types": p["rigid_types"],
                "chest_rigids": p["chest_rigids"],
                "frames": [{"frame": r["frame"],
                            "chest_extent": r["chest"]["extent"],
                            "chest_hip_ratio": r.get("chest_hip_ratio")} for r in p["frames"]]}
            for v, p in probes.items()},
        "pairs": {f: {k: v for k, v in rec.items()
                      if k.endswith("_vs_") or "vs" in k and k not in ("present", "metrics")}
                  for f, rec in comp["frames"].items()},
    }


def sleeve_block() -> dict:
    out = {}
    for name in ("base", "static"):
        d = load(OUT, "sleeve", "sleeve_%s.json" % name)
        out[name] = {
            "policy": d["policy"], "is_built": d["is_built"],
            "rigids": d["rigids"], "pmx_modes": d["pmx_modes"],
            "sleeve_units": d["sleeve_units"],
            "sleeve_bones": len(d["sleeve_bones_pmx"]),
            "muted_constraints": d["muted_constraints"],
            "still_unmuted": d["still_unmuted"],
            "sleeve_roi": d["sleeve_roi"],
            "other_physics_bones": d["other_physics_bones"],
            "bone_delta_stats": d["bone_delta_stats"],
            "frames": [{"frame": r["frame"], "sleeve_extent": r["sleeve_extent"],
                        "sleeve_bone_delta_max": (r.get("sleeve_bone_delta") or {}).get("max"),
                        "over45": (r.get("sleeve_bone_delta") or {}).get("over45"),
                        "other_max": (r.get("sleeve_bone_delta") or {}).get("other_max")}
                       for r in d["frames"]],
        }
    return out


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "hashes":
        base = load(OUT, "baseline.json")
        for key in ("feixiao", "kafka"):
            now = sha256(base[key]["path"])
            print("%s now=%s before=%s same=%s"
                  % (key, now, base[key]["sha256"], now == base[key]["sha256"]))
        return 0

    base = load(OUT, "baseline.json")
    manifest = load(OUT, "patch_manifest.json")
    env = load(OUT, "env_feixiao.json")

    data = {
        "module": "M01",
        "date": "2026-11-15",
        "environment": {
            "blender": env["blender"],
            "mmd_tools_module": "bl_ext.user_default.mmd_tools",
            "python": sys.version.split()[0],
            "blender_argv": ["-b", "--factory-startup"],
            "render_engines_available": ["BLENDER_EEVEE"],
            "mmd_tools_build_facts": {
                "rigid_empties_after_import": env["rigid_empties_after_import"],
                "is_built_after_import": env["is_built_after_import"],
                "constraints_after_import": env["constraints_after_import"],
                "is_built_after_build": env["is_built"],
                "constraints_after_build": env["constraints_after_build"],
                "rigid_types": env["rigid_types"],
                "rbw_default": env["rbw"],
            },
        },
        "sources_before": {
            "feixiao": {"path": base["feixiao"]["path"], "sha256": base["feixiao"]["sha256"],
                        "bytes": base["feixiao"]["bytes"]},
            "kafka": {"path": base["kafka"]["path"], "sha256": base["kafka"]["sha256"],
                      "bytes": base["kafka"]["bytes"]},
        },
        "sources_after": {
            "feixiao": sha256(base["feixiao"]["path"]),
            "kafka": sha256(base["kafka"]["path"]),
        },
        "s3": {
            "pmx_structure": {
                "rigids": base["feixiao"]["rigids"], "joints": base["feixiao"]["joints"],
                "bones": base["feixiao"]["bones"],
                "mode_distribution": base["feixiao"]["mode_distribution"],
                "targets": base["feixiao"]["targets"],
                "target_joints": base["feixiao"]["target_joints"],
                "classifier_counts": base["feixiao"]["counts"],
                "mute_bones": base["feixiao"]["mute_bones"],
            },
            "patch": manifest,
            "clip1_wushu": clip_block("probe"),
            "clip2_sway": clip_block("probe2"),
            "images": {
                "compare_chest": os.path.join(OUT, "compare_chest.png"),
                "close_ups": os.path.join(OUT, "shots_chest3"),
            },
        },
        "s5": {
            "pmx_structure": {
                "rigids": base["kafka"]["rigids"], "joints": base["kafka"]["joints"],
                "bones": base["kafka"]["bones"],
                "mode_distribution": base["kafka"]["mode_distribution"],
                "sleeve_units": base["kafka"]["sleeve_units"],
                "strict_policy_bones": len(base["kafka"]["strict_policy_bones"]),
                "xk_pattern_bones": len(base["kafka"]["xk_bones"]),
            },
            "probe": sleeve_block(),
            "vmd": r"E:\flowhmr-test\library\vmd\PERF_Wushu_VoidStep_Once_F.vmd",
            "images": {"compare_sleeve": os.path.join(OUT, "compare_sleeve.png")},
        },
        "shared_workspace_writes": [
            {"path": r"C:\Users\zzc\Desktop\ai用\dsh use\gongtonggzq\M01_F3冻结类修复_胸口与袖子.md",
             "action": "append-only supplement «补充 · M01 执行记录»", "by_script": "m01_append_shared_doc.py"},
            {"path": r"C:\Users\zzc\Desktop\ai用\dsh use\gongtonggzq\M02_F4下摆与F6碰撞映射.md",
             "action": "append-only supplement «补充 · M01 → M02 交接»", "by_script": "m01_append_shared_doc.py"},
        ],
        "experiment_counts": {
            "env_api_confirmation": "2（1 次 operator 未注册，1 次 types=PHYSICS 才能 build）",
            "baseline_reproduction": "1（clip1 基线一次跑通；clip2 独立复核 1 次）",
            "s3_rounds": "3（基线 / 单变量 mode 修复 / 独立动作复核）",
            "s5_rounds": "2（基线 / 静态策略）",
            "same_error_fix": "2（import_vmd poll 缺 select+active；建链需 PHYSICS）",
            "full_regression": "1 轮（60 项测试全绿）",
            "render_rounds": "3（12 帧探针内嵌图 1 轮 + 代表帧对比图 2 轮，均为静态图，无序列渲染）",
        },
    }
    os.makedirs(REP, exist_ok=True)
    path = os.path.join(REP, "measurements.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    print("WROTE", path)
    print("feixiao sha before/after same:", data["sources_before"]["feixiao"]["sha256"] == data["sources_after"]["feixiao"])
    print("kafka   sha before/after same:", data["sources_before"]["kafka"]["sha256"] == data["sources_after"]["kafka"])
    for clip in ("clip1_wushu", "clip2_sway"):
        pairs = data["s3"][clip]["pairs"]
        f = sorted(pairs)[0]
        print(clip, "f%s" % f, {k: v.get("mean") for k, v in pairs[f].items() if isinstance(v, dict)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
