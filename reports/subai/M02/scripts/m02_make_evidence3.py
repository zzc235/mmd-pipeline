"""M02 attempt 3 的 evidence/1 canonical 生成器（规范同 attempt 2）。

    python m02_make_evidence3.py <out.json>
"""
import hashlib
import json
import os
import sys

ROOT = r"E:\dsh pr\woker2"
S8 = "out/subai/M02/s8"
SAMPLE_DIRS = ["A1", "A2", "A_FINAL", "B_FINAL", "C", "D", "E", "F",
               "P0", "P1", "P2", "P3", "P4", "P5", "P6"]
FILES_ALWAYS = ["meta.json", "collections.json", "frames.jsonl"]

COMPARISONS = ["s8_index.json", "s8_ab_result.json", "s8_ab_cachefree.json", "s8_A_vs_P0.json",
               "s8_P0_P1_repeat.json", "s8_P0_P3_fingerprint.json", "s8_P5_noground.json",
               "s2_cachefree_limit.json", "s2_cachefree_limit_absurd.json", "s8_P7_frame109.json",
               "s8_P7_result.json", "s8_control_A1A2.json", "s8_control_C.json",
               "s8_control_D.json", "s8_control_E.json", "s8_control_F.json"]

REPORTS = ["s8_hypothesis.md", "m02_cache_finding.md", "cache_state.json", "result_attempt2.md",
           "result_attempt3.md", "resample_summary.json", "dyn_diff.json",
           "dyn_diff_resample.json", "dyn_spans.json", "s2_targets.json",
           "evidence_m02_attempt2.json"]

SCRIPTS = ["m02_s8_ab.py", "m02_s8_compare.py", "m02_s8_index.py", "m02_s8_selftest.py",
           "m02_cache_state.py", "m02_s8_p7.py", "m02_dynamics_probe.py", "m02_resample_summary.py",
           "m02_dyn_diff.py", "m02_dyn_spans.py", "m02_make_evidence2.py"]


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def art(rel):
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        raise SystemExit("artifact 缺失：%s" % rel)
    return {"path": rel.replace("\\", "/"), "sha256": sha(p), "version": "1"}


def main():
    out_path = sys.argv[1]
    arts = []
    for d in SAMPLE_DIRS:
        for f in FILES_ALWAYS:
            rel = "%s/%s/%s" % (S8, d, f)
            if os.path.exists(os.path.join(ROOT, rel)):
                arts.append(art(rel))
    for f in COMPARISONS + REPORTS:
        rel = "reports/subai/M02/%s" % f
        if os.path.exists(os.path.join(ROOT, rel)):
            arts.append(art(rel))
    for f in SCRIPTS:
        arts.append(art("reports/subai/M02/scripts/%s" % f))
    for d in ("B2r_baseline", "B2r_x07"):
        for f in ("frames.jsonl", "meta.json"):
            arts.append(art("out/subai/M02/dyn/%s/%s" % (d, f)))
    for f in ("E_base.blend", "G_base.blend"):
        arts.append(art("%s/%s" % (S8, f)))

    ev = {
        "spec": "evidence/1",
        "task_id": "M02",
        "attempt": 3,
        "status": "PARTIAL",
        "files": [],
        "tests": [
            {"cmd": "python -m unittest discover -s tests (A1 @714d2b9)", "exit": 0,
             "passed": 128, "failed": 0, "skipped": 15},
            {"cmd": "blender -b -P m02_s8_ab.py -- G_base.blend REFUSE_TEST A"
                    "（应当被拒：baked 输入 + 非 P* + 无 --allow-baked）", "exit": 1,
             "passed": 1, "failed": 0, "skipped": 0},
            {"cmd": "blender -b -P m02_s8_ab.py -- G_base.blend P0..P6（7 次 --background）",
             "exit": 0, "passed": 7, "failed": 0, "skipped": 0},
            {"cmd": "blender -b -P m02_s8_p7.py -- G_base.blend 109（单帧跳转判别）",
             "exit": 0, "passed": 1, "failed": 0, "skipped": 0},
        ],
        "artifacts": arts,
        "known_risks": [
            "S8 的 EFFECTIVE 是「Blender 层 collision_collections 进解算」的证据，不是"
            "「PMX 掩码错配造成多少偏差」的证据：P2/P5 改的是集合位向量，掩码一位没动。",
            "P0 vs P2 的 D_all 1.76 m 主要来自失去地面支撑的刚体，判据只用 18 根下摆骨的 8.24 mm；"
            "地面接触单独由 P5 量到 3.62 mm，剩余约 4.62 mm 归角色间碰撞（两者只能粗略相减，非线性）。",
            "交付烘焙（A）与本项目重算（P0）差 0.9087 m（下摆首分叉 f116）：任何门禁必须写明"
            "量的是「交付轨迹」还是「重算轨迹」，两者不可混用。",
            "P5 是分辨实验，不在原始批准的变体清单里（同一授权范围内，多一次 28 秒），已在 result 说明。",
            "单场景单动作（躺姿）：结论不能外推到站立/剧烈动作。",
            "B2/B2r 两批采样的 meta 缺 point_cache 字段（先于新要求产出），缓存状态由 cache_state.json 补齐。",
        ],
        "interface": {
            "guardrail": "输入 point_cache.is_baked=True 且变体非 P* 且无 --allow-baked → 拒绝运行（退出码 1，不产出目录）",
            "free_bake_api": "bpy.ops.ptcache.free_bake_all()（仅在不保存的副本上；10 §6 只禁 bake_all()）",
            "meta_fields": ["point_cache_before", "point_cache_after_free_bake", "point_cache_after_step",
                            "free_bake_api", "in_blend_sha256_before", "in_blend_sha256_after",
                            "source_untouched", "changed_bodies", "kinematic_changed_bodies",
                            "limits_changed_count"],
            "criterion": "18 根下摆骨 D_hem >= 1.0 mm 判 EFFECTIVE（预注册于 s8_hypothesis.md）",
            "verdicts": {"S8": "EFFECTIVE", "S2": "变量未激活（已解烘焙数据上 D=0.0）"},
        },
    }
    canonical = json.dumps(ev, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    data = canonical.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    with open(out_path, "wb") as fh:
        fh.write(data)
    print("evidence/1:" + digest)
    print("bytes=%d artifacts=%d file_sha=%s" % (len(data), len(arts), sha(out_path)))


main()
