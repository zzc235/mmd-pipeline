"""M02 attempt 2 的 evidence/1 canonical 生成器（规范见 D0 的 evidence_hash v1）。

    python m02_make_evidence2.py <out.json>

canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
evidence/1:<sha256(canonical 的 utf-8 字节)>
落盘文件内容 == canonical 字符串本身（无尾随换行），因此文件 sha256 恰等于 hexdigest。
"""
import hashlib
import json
import os
import sys

ROOT = r"E:\dsh pr\woker2"


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def art(rel):
    p = os.path.join(ROOT, rel)
    return {"path": rel.replace("\\", "/"), "sha256": sha(p),
            "version": "1" if rel.endswith(".json") else "1"}


ARTIFACTS = [
    "out/subai/M02/dyn/B2r_baseline/frames.jsonl",
    "out/subai/M02/dyn/B2r_baseline/meta.json",
    "out/subai/M02/dyn/B2r_x07/frames.jsonl",
    "out/subai/M02/dyn/B2r_x07/meta.json",
    "reports/subai/M02/resample_summary.json",
    "reports/subai/M02/dyn_diff_resample.json",
    "reports/subai/M02/dyn_diff.json",
    "reports/subai/M02/dyn_spans.json",
    "reports/subai/M02/cache_state.json",
    "reports/subai/M02/m02_cache_finding.md",
    "reports/subai/M02/result_attempt2.md",
    "reports/subai/M02/s8_hypothesis.md",
    "reports/subai/M02/scripts/m02_dynamics_probe.py",
    "reports/subai/M02/scripts/m02_resample_summary.py",
    "reports/subai/M02/scripts/m02_cache_state.py",
    "reports/subai/M02/scripts/m02_dyn_diff.py",
    "reports/subai/M02/scripts/m02_dyn_spans.py",
    "reports/subai/M02/scripts/m02_s8_ab.py",
    "reports/subai/M02/scripts/m02_s8_compare.py",
]


def main():
    out_path = sys.argv[1]
    ev = {
        "spec": "evidence/1",
        "task_id": "M02",
        "attempt": 2,
        "status": "PARTIAL",
        "files": [],
        "tests": [
            {"cmd": "python -m unittest discover -s tests (A1 @714d2b9)", "exit": 0,
             "passed": 128, "failed": 0, "skipped": 15},
            {"cmd": "python -m unittest tests.test_pmx_patch (A1 @714d2b9)", "exit": 0,
             "passed": 23, "failed": 0, "skipped": 0},
            {"cmd": "python scripts/m02_resample_summary.py（可比性：angle/rot 逐行最大差 0.0）",
             "exit": 0, "passed": 1, "failed": 0, "skipped": 0},
        ],
        "artifacts": [art(a) for a in ARTIFACTS],
        "known_risks": [
            "B2r 两批采样来自 B_from_blend1.blend / B_x07.blend，二者 point_cache.is_baked=True："
            "本笔数字是交付工程里已烘焙轨迹的回放，不是本次重算的结果。作为「交付动画的观测量」有效，"
            "作为「改参数 ⇒ 轨迹变化」的实验无效。",
            "B2r_baseline / B2r_x07 的 meta.json 缺 point_cache.is_baked 与缓存帧范围两项"
            "（先于 13:02 的新要求产出）；缓存状态由 reports/subai/M02/cache_state.json 事后单独取证补齐。",
            "S8 阶段 E（collision_collections A/B）判 UNKNOWN：A/B/C/E 四版 frames.jsonl 逐字节相同，"
            "疑为缓存回放；D（全 kinematic）与 F（挪 1 cm）变了，但都不足以当成「真解算」的证据。"
            "解烘焙重算需批准后另行提交。",
            "S2 的「±0.7 rad 未激活」原证据（B2 两版逐字节相同）作废；现有替代证据是未烘焙的 "
            "prepared_baseline vs prepared_x07，最大差 7e-5 deg（1.2e-6 rad），强度仅到「限位没吃到」。",
            "新列 bone_world_delta_deg 是相邻帧世界朝向夹角（度），第 1 帧为 null；"
            "它不区分「物理驱动」与「动画驱动」，只回答「这一帧动没动」。",
        ],
        "interface": {
            "columns": ["frame", "bone", "angle_deg", "rot_x_deg", "rot_y_deg", "rot_z_deg",
                        "parent_delta_deg", "bone_world_delta_deg"],
            "row_semantics": "每个 (frame, bone) 一行，逐帧原始值，不做聚合；row_count = frames × bones",
            "comparability": "B2r 与 B2 的 angle_deg / rot_x·y·z_deg 逐行最大差 0.0（17280 行/版），"
                             "新列只增不改",
        },
    }
    canonical = json.dumps(ev, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    data = canonical.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    with open(out_path, "wb") as fh:
        fh.write(data)
    print("evidence/1:" + digest)
    print("bytes=%d  file_sha=%s" % (len(data), sha(out_path)))


main()
