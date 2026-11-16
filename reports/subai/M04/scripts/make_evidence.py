"""生成 evidence/1 canonical 证据文件：json.dumps(sort_keys, separators, ensure_ascii=False) → sha256。

用法：同目录下放 payload（python dict），或用 --gen 直接调 build_attempt6 / build_attempt7 之一。
"""
import hashlib
import json
import os
import sys

ROOT_MAIN = r"E:\dsh pr\woker2"
ROOT_A2 = r"E:\code\mmdpipe-ai\A2"
LEGACY_RAW = "legacy-raw" in sys.argv  # 见 sha_file：只为复算旧证据


def _is_text(data):
    """能不能按文本处理：无 NUL 且是合法 UTF-8。二进制（.blend 等）一律按原始字节。"""
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def sha_file(path):
    """`hash_basis: lf_normalized_v1`（D0 13:24 全队基数）：文本先 \r\n → \n 再 sha256。

    `python make_evidence.py <n> legacy-raw` 可回到旧基数（逐字节），
    只为复算 attempt 6–10 那几笔已经合并的证据。
    """
    with open(path, "rb") as fh:
        data = fh.read()
    if not LEGACY_RAW and _is_text(data):
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def file_entries(root, rels):
    out = []
    for rel in rels:
        p = os.path.join(root, rel)
        out.append({"path": rel.replace("\\", "/"), "sha256": sha_file(p), "tracked": True})
    return out


def artifact_entries(rels, version="1"):
    out = []
    for rel in rels:
        p = os.path.join(ROOT_MAIN, rel)
        out.append({"version": version, "path": rel.replace("\\", "/"), "sha256": sha_file(p)})
    return out


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def write_spec(obj, out_path, predict=False):
    """按**规范实现**落盘（D-072 起）：digest 与落盘字节都来自 `coordination.evidence`。

    为什么另开一条路而不是改 `write()`：attempt 6–10 的哈希是自建口径算的，
    改掉 `write()` 会让那几笔无法复算。新记录一律走这里，旧记录留 `write()` + `legacy-raw`。

    两道自验（照 1号 的做法，都是「应当被拒」的输入）：
      1. **`normalize()` 必须真的把 `measurements` 收进 canonical**——否则我这份记录会
         再演一次 attempt 11 的 RETURN_FIX（数落在哈希之外）。不收就 `exit 3` 且**不写文件**。
      2. 落盘后回读校验「文件 sha256 == hexdigest」——D0 每次必查的那条不变量。

    `predict=True` 只打印预测 digest 与字节数、不写文件（等 schema 落地前用它对外公布对账值）。
    """
    sys.path.insert(0, ROOT_A2)
    from coordination import evidence as E  # noqa: E402
    norm = E.normalize(obj)
    # **通用断言**（D0 13:53 的建议，比逐个键点名更不容易漏）：我写进 dict 的每个键，
    # `normalize()` 之后都必须还在。少一个就是「某个字段落在哈希之外」，而落在外面的字段等于没有
    # （attempt 11 的退件原因）。新增 schema 字段时自动被覆盖，不用回来改这里。
    lost = sorted(k for k in obj if k not in norm)
    if lost:
        print("REFUSED: coordination.evidence 的 normalize() 丢掉了 %s —— 这些字段会落在哈希之外，"
              "此刻落盘就是再造一份 RETURN_FIX（先落 schema，再出记录）" % "/".join(lost), flush=True)
        sys.exit(3)
    data = E.canonical_bytes(norm)
    digest = hashlib.sha256(data).hexdigest()
    if predict:
        meas = obj.get("measurements") or {}
        mbytes = len(json.dumps(meas, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False).encode("utf-8"))
        print("PREDICT evidence/1:" + digest)
        print("PREDICT bytes=%d measurements_bytes=%d" % (len(data), mbytes))
        return digest
    full = out_path if os.path.isabs(out_path) else os.path.join(ROOT_MAIN, out_path)
    if hashlib.sha256(E.canonical_bytes(E.normalize(obj))).hexdigest() != digest:
        raise SystemExit("规范实现不稳定：两次 normalize 结果不一致")
    with open(full, "wb") as fh:
        fh.write(data)
    on_disk = sha_file(full)
    if on_disk != digest:
        raise SystemExit("落盘字节与 hexdigest 不等：%s != %s" % (on_disk, digest))
    print("evidence/1:" + digest)
    print("file:", full, len(data), "B")
    print("file_sha256:", on_disk, "(== hexdigest)" if on_disk == digest else "(MISMATCH)")
    return digest


def write(obj, out_path):
    data = canonical(obj)
    digest = hashlib.sha256(data).hexdigest()
    full = out_path if os.path.isabs(out_path) else os.path.join(ROOT_MAIN, out_path)
    with open(full, "wb") as fh:
        fh.write(data)
    print("evidence/1:" + digest)
    print("file:", full, len(data), "B")
    print("file_sha256:", sha_file(full))
    return digest


def build_attempt6():
    files = file_entries(ROOT_A2, [
        "mmdpipe/measure.py",
        "presets/physics_gate/assembly_v1.json",
        "tests/test_measure.py",
    ])
    return {
        "spec": "evidence/1",
        "task_id": "M04",
        "attempt": 6,
        "status": "PARTIAL",
        "interface": "physics_gate/1",
        "commit": "6eab5a0",
        "merge_main": "d5c04b3",
        "scope": "冻结判据改为「父链全零 且 目标自身跨度<1°」才告警；父骨静止而子骨被物理解算属正常样本，不再误判为未测量",
        "files": files,
        "tests": [
            {"cmd": "python -m unittest discover -s tests (在 d5c04b3 上)", "exit": 0, "passed": 229,
             "failed": 0, "skipped": 15},
            {"cmd": "python -m mmdpipe.measure --dynamics .../B2_baseline/frames.jsonl "
                    "--penetration out/subai/M04/penetration/roi18skirt.jsonl", "exit": 0,
             "passed": 0, "failed": 0, "skipped": 0},
        ],
        "known_risks": [
            "改判据的实证来自 1号 的四元数查询（下半身 240 帧不动），不是我这边的独立测量",
            "跨度阈值 1.0 deg 是探索性取值；真冻结样本尚未出现过，假阳性/假阴性都未取数",
            "冻结门禁在父链静止时仍返回 PASS，理由文字仍写「本来就不该动」，与新判据口径不一致（下一笔修）",
        ],
    }


def build_attempt7():
    files = file_entries(ROOT_A2, [
        "mmdpipe/measure.py",
        "mmdpipe/physics_gate.py",
        "tests/test_measure.py",
        "tests/test_physics_gate.py",
        "tests/test_gate_report.py",
    ])
    arts = [
        ("reports/subai/M04/scripts/m04_penetration_probe.py", "1"),
        ("out/subai/M04/penetration/roi18skirt.jsonl", "1"),
        ("out/subai/M04/penetration/roi18skirt.meta.json", "1"),
        ("reports/subai/M04/gate_results/B2_baseline_pen.measurement.json", "1"),
        ("reports/subai/M04/gate_results/B2_baseline_pen.gate.json", "1"),
        ("reports/subai/M04/thresholds.md", "2"),
        ("reports/subai/M04/known_limits.md", "3"),
    ]
    return {
        "spec": "evidence/1",
        "task_id": "M04",
        "attempt": 7,
        "status": "PARTIAL",
        "interface": "physics_gate/1",
        "commit": "2ad6d6c",
        "merge_main": "d5c04b3",
        "scope": "第一份真实穿透测量（240 帧 · ROI 18_skirt_rigid）+ 修掉「测了没穿入」被判成「没测」的门禁缺陷 + "
                 "冻结 PASS 理由改按目标自身跨度",
        "files": files,
        "artifacts": artifact_entries([p for p, _ in arts]),
        "tests": [
            {"cmd": "python -m unittest discover -s tests (在 2ad6d6c 上)",
             "exit": 0, "passed": 233, "failed": 0, "skipped": 15},
            {"cmd": "python -m mmdpipe.measure --dynamics .../B2_baseline/frames.jsonl "
                    "--penetration out/subai/M04/penetration/roi18skirt.jsonl --roi 18_skirt_rigid",
             "exit": 0, "passed": 0, "failed": 0, "skipped": 0},
            {"cmd": "python -m mmdpipe.physics_gate --measurement "
                    "out/subai/M04/penetration/B2_baseline.measurement.json "
                    "--profile presets/physics_gate/exploratory_v0.json",
             "exit": 0, "passed": 0, "failed": 0, "skipped": 0},
        ],
        "measurements": {
            "penetration": {"roi": "18_skirt_rigid", "frames_measured": 240, "frames": 0,
                            "max_depth_m": -0.017064, "deepest_frame": 94,
                            "deepest_bone": "下擺_0_12", "epsilon_m": 0.02},
            "frozen": {"parent_delta_deg": 0.0, "target_span_deg": 38.950195},
            "overshoot": {"median_deg": 67.09426, "p95_deg": 67.187151, "max_deg": 67.198611,
                          "spike_count": 0},
            "aggregate": {"status": "PASS", "unknown_gates": [], "failed_gates": [], "exit": 0},
        },
        "known_risks": [
            "穿透深度 240 帧只波动 2.9 mm、23% 的 ROI 顶点每帧判为内部：更像接触重叠或射线奇偶法的系统性偏移，"
            "不是偶发穿刺；epsilon 0.02 m 与实测 0.0171 m 只差 2.9 mm，不能据此说穿透阈值已标定",
            "没有正控（原计划把 ROI 换成必不穿入的髪骨对照），锁被 1号 取走后未跑",
            "ROI 是 18 根有刚体的下摆骨，不是历史 S4 第 11 行（那 11 根无刚体、其工程已不存在），与 -0.202 m 无可比性",
            "单场景单动作（躺姿和胡桃睡觉），不能外推到站立或剧烈动作",
            "冻结的 target_span_deg < 1.0 判据仍无真实阳性样本",
            "混淆矩阵仍无法计算：好样本/坏样本配对不存在",
        ],
    }


def build_attempt8():
    files = file_entries(ROOT_A2, [
        "mmdpipe/measure.py",
        "mmdpipe/physics_gate.py",
        "tests/test_measure.py",
        "tests/test_physics_gate.py",
        "tests/test_gate_report.py",
    ])
    arts = [
        ("reports/subai/M04/scripts/m04_probe_selftest.py", "1"),
        ("reports/subai/M04/scripts/m04_penetration_probe.py", "2"),
        ("out/subai/M04/penetration/probe_selftest.json", "1"),
        ("out/subai/M04/penetration/control_hair.jsonl", "1"),
        ("out/subai/M04/penetration/control_hair.meta.json", "1"),
        ("out/subai/M04/penetration/B2_baseline.nodefence.measurement.json", "1"),
        ("out/subai/M04/penetration/B2_baseline.nodefence.gate.json", "1"),
        ("reports/subai/M04/thresholds.md", "3"),
        ("reports/subai/M04/known_limits.md", "4"),
    ]
    return {
        "spec": "evidence/1",
        "task_id": "M04",
        "attempt": 8,
        "status": "PARTIAL",
        "interface": "physics_gate/1",
        "correction_of": 7,
        "commit": "2ad6d6c",
        "merge_main": "d5c04b3",
        "scope": "撤回 attempt 7 的穿透数字：探针自检不通过（外推 10 cm 17.4% 假阳、内推 3 cm 43.4% 假阴、"
                 "最近面距离偏小 1.7 cm），−0.0171 m 落在方法偏置内；穿透门禁回到 UNKNOWN",
        "files": files,
        "artifacts": artifact_entries([p for p, _ in arts]),
        "tests": [
            {"cmd": "python -m unittest discover -s tests (在 2ad6d6c 上，与 attempt 7 相同代码)",
             "exit": 0, "passed": 233, "failed": 0, "skipped": 15},
            {"cmd": "python -m mmdpipe.physics_gate --measurement "
                    "out/subai/M04/penetration/B2_baseline.nodefence.measurement.json "
                    "--profile presets/physics_gate/exploratory_v0.json",
             "exit": 3, "passed": 0, "failed": 0, "skipped": 0},
        ],
        "measurements": {
            "probe_selftest": {"samples": 304, "outward_10cm_rate": 0.8257,
                               "inward_3cm_rate": 0.5658, "inward_depth_median_err_m": -0.01707},
            "control_hair_roi": {"frames": 60, "deepest_m": -0.009711, "bone": "側髪2-2.L"},
            "regated": {"status": "UNKNOWN", "unknown_gates": ["penetration"],
                        "frozen": "PASS", "overshoot": "PASS", "exit": 3},
        },
        "known_risks": [
            "穿透门禁在真实样本上仍无可用数字；上一次的 -0.0171 m 已被自己的自检推翻",
            "自检是在拿到 D0 批准的 40 秒髪骨对照之外多跑的 10 秒（自费性质），未先申请",
            "髪骨对照本身也只证明方法有系统性偏置，不能证明偏置的确切来源（薄壳 or 奇偶法 or 两者）",
            "M04 的过冲/冻结数字不受 1号 的 baked 缓存发现影响（量的是要交付的轨迹本身），但同样只有单场景单动作",
            "混淆矩阵、冻结真实阳性样本、R0 样本三项仍缺",
        ],
    }


def build_attempt9():
    files = file_entries(ROOT_A2, [
        "mmdpipe/measure.py",
        "mmdpipe/physics_gate.py",
        "tests/test_physics_gate.py",
        "tests/test_gate_report.py",
    ])
    arts = [
        ("reports/subai/M04/thresholds.md", "4"),
        ("reports/subai/M04/penetration_method.md", "2"),
        ("reports/subai/M04/scripts/m04_penetration_probe.py", "3"),
        ("reports/subai/M04/scripts/m04_capsule_probe.py", "1"),
        ("out/subai/M04/penetration/gate_reject.meta.json", "1"),
        ("out/subai/M04/penetration/gate_reject.log", "1"),
    ]
    return {
        "spec": "evidence/1",
        "task_id": "M04",
        "attempt": 9,
        "status": "PARTIAL",
        "interface": "physics_gate/1",
        "commit": "984d947",
        "scope": "穿透口径 basis 必填（mesh/capsule）+ reason 带口径名 + 按口径选 epsilon；"
                 "探针 NOT_MEASURED 出口改 sys.exit(3)；thresholds.md 出处栏按 D0 强版本重写；"
                 "胶囊探针脚本已写（未在 Blender 里跑过，未交数字）",
        "files": files,
        "artifacts": artifact_entries([p for p, _ in arts]),
        "tests": [
            {"cmd": "python -m unittest discover -s tests (在 984d947 上)",
             "exit": 0, "passed": 238, "failed": 0, "skipped": 15},
        ],
        "verification": {
            "selftest_gate_rejection": {
                "jsonl_produced": False,
                "meta_status": "NOT_MEASURED",
                "selftest": {"samples": 202, "outward_10cm_rate": 0.8168,
                             "inward_3cm_rate": 0.5198,
                             "inward_depth_median_err_m": -0.016966},
                "abort_log": "[probe] ABORT selftest failed -> NOT_MEASURED",
                "exit_code_note": "该次运行时退出码为 0（脚本 return），已改为 sys.exit(3)，改动后未重跑",
            },
        },
        "known_risks": [
            "m04_capsule_probe.py 未在 Blender 里执行过：连自检都还没跑，不得视为可用",
            "sys.exit(3) 的改动同样未在 Blender 里复跑（改了脚本尾部出口，下次锁窗口一并验）",
            "basis 只做到「必填 + 按口径选 epsilon」，胶囊口径本身仍无任何场景数字",
            "thresholds.md 出处栏已按 is_outdated=true 的强版本写明，但哪条动画是渲染真正发生的仍未判定（1号 P7 在查）",
        ],
    }


def build_attempt10():
    files = file_entries(ROOT_A2, [
        "mmdpipe/physics_gate.py",
        "tests/test_physics_gate.py",
    ])
    arts = [
        ("reports/subai/M04/baselines/B_from_blend1_roi18_capsule_v1.json", "1"),
        ("out/subai/M04/penetration/capsule_roi18_delta.jsonl", "1"),
        ("out/subai/M04/penetration/capsule_roi18_delta.meta.json", "1"),
        ("out/subai/M04/penetration/B2_capsule_delta.measurement.json", "1"),
        ("out/subai/M04/penetration/B2_capsule_delta.gate.json", "1"),
        ("reports/subai/M04/scripts/m04_capsule_probe.py", "4"),
        ("reports/subai/M04/known_limits.md", "5"),
    ]
    return {
        "spec": "evidence/1",
        "task_id": "M04",
        "attempt": 10,
        "status": "PARTIAL",
        "interface": "physics_gate/1",
        "commit": "ac1cef0",
        "scope": "胶囊口径改为「相对基线」判定（D-056）：按刚体对落版本化基线、判定用 max(0, depth-baseline)、"
                 "缺基线判 UNKNOWN；同时把胶囊 PASS 的 reason 从「无重叠」改成「未超出基线」",
        "files": files,
        "artifacts": artifact_entries([p for p, _ in arts]),
        "tests": [
            {"cmd": "python -m unittest discover -s tests (in tests/, HEAD ac1cef0)",
             "exit": 0, "passed": 238, "failed": 0, "skipped": 15},
            {"cmd": "python -m mmdpipe.physics_gate --measurement "
                    "out/subai/M04/penetration/B2_capsule_delta.measurement.json "
                    "--profile presets/physics_gate/exploratory_v0.json",
             "exit": 0, "passed": 0, "failed": 0, "skipped": 0},
        ],
        "measurements": {
            "baseline": {"file": "reports/subai/M04/baselines/B_from_blend1_roi18_capsule_v1.json",
                         "sha256_prefix": "b3cbe2e8", "pairs": 5076, "frame": 1},
            "capsule_roi18_delta": {
                "roi": "roi18_capsule", "frames_measured": 20,
                "max_delta_m": -0.002121, "raw_depth_at_that_pair_m": -0.019942,
                "baseline_at_that_pair_m": -0.017821,
                "deepest_bone": "下擺_0_10", "deepest_other": "下擺_1_10",
                "pairs_without_baseline": 0,
            },
            "gate": {"status": "PASS", "penetration": "PASS", "frozen": "PASS",
                     "overshoot": "PASS", "exit": 0},
            "context": {"raw_absolute_capsule_overlap_m": -0.0946,
                        "why_not_used": "该值 20 帧内只波动 0.15 mm，是静态布局（下半身胶囊大、"
                                        "裙摆胶囊起点在其内部），不是动力学事件"},
        },
        "known_risks": [
            "基线只对这一份交付物成立：第 11 行 11 个静态占位刚体只存在于 Nov-7 的 B_from_blend1（324 刚体），"
            "今天重建产物是 312 刚体、无占位体，换工程基线不成立",
            "20 帧、单场景单动作（躺姿）；基线取 f1，f1 的增量按定义为 0",
            "胶囊仍是作者摆的近似体：相邻骨关节区常态重叠 120 对/帧，本口径只测「超出基线的增量」",
            "Blender 仍在退出路径撞 0xC0000005（sys.exit(0) 未阻止），产物完整但退出码非 0",
        ],
    }


def build_attempt11():
    files = file_entries(ROOT_A2, [
        "mmdpipe/measure.py",
        "tests/test_measure.py",
    ])
    arts = [
        ("reports/subai/M04/scripts/m04_capsule_probe.py", "5"),
        ("reports/subai/M04/scripts/m04_mesh_probe_v2.py", "1"),
        ("reports/subai/M04/mesh_v2_selftest.md", "1"),
        ("reports/subai/M04/known_limits.md", "6"),
        ("out/subai/M04/mesh_probe/v2_selftest.meta.json", "1"),
        ("out/subai/M04/mesh_probe/islands.json", "1"),
        ("out/subai/M04/mesh_probe/ref_probe.json", "1"),
        ("out/subai/M04/mesh_probe/m04_mesh_islands.py", "1"),
        ("out/subai/M04/mesh_probe/m04_ref_probe.py", "1"),
        ("out/subai/M04/penetration/_policy_check/A.meta.json", "1"),
        ("out/subai/M04/penetration/_policy_check/A.jsonl", "1"),
        ("out/subai/M04/penetration/_policy_check/B.meta.json", "1"),
    ]
    return {
        "spec": "evidence/1",
        "task_id": "M04",
        "attempt": 11,
        "status": "PARTIAL",
        "interface": "physics_gate/1",
        "commit": "f3fd0e1",
        "hash_basis": "lf_normalized_v1",
        "scope": "① 逐帧采样改为「从 scene.frame_start 顺序步进」的计划制（P12：缓存不进 .blend，冷跳是第三条轨迹），"
                 "回退/冷跳在计划阶段拒绝；② 网格口径 v2（岛隔离 + 最近面法向符号的 signed distance）实现到自检可过，"
                 "并按派活边界只报方法可用与自检读数，**不含任何场景数字**；③ known_limits 补「基线只对本交付物成立」"
                 "与「基线存储精度 1 µm」两节",
        "files": files,
        "artifacts": artifact_entries([p for p, _ in arts]),
        "tests": [
            {"cmd": "python -m unittest discover -s tests (in tests/, HEAD f3fd0e1)",
             "exit": 0, "passed": 335, "failed": 0, "skipped": 15},
            {"cmd": "python -m unittest discover -s . -p test_measure.py (in tests/)",
             "exit": 0, "passed": 33, "failed": 0, "skipped": 0},
            {"cmd": "blender --background --factory-startup --python m04_capsule_probe.py -- "
                    "--frames 3:5 --baseline <baselines/B_from_blend1_roi18_capsule_v1.json>",
             "exit": -1073741819, "passed": 0, "failed": 0, "skipped": 0},
            {"cmd": "blender --background --factory-startup --python m04_capsule_probe.py -- "
                    "--frames 3:5 --baseline-frame 40",
             "exit": 3, "passed": 0, "failed": 0, "skipped": 0},
            {"cmd": "blender --background --factory-startup --python m04_mesh_probe_v2.py -- "
                    "--blend out/subai/M02/blend/B_from_blend1.blend",
             "exit": 0, "passed": 0, "failed": 0, "skipped": 0},
        ],
        "measurements": {
            # `tests[]` 的行会被 normalize() 重建（只留 cmd/exit/passed/failed/skipped），
            # 所以每条的说明放这里——这里才是进哈希的地方。放在 tests[] 里会让
            # 「文件 sha256 == digest」这条等式不成立，而没有这条等式就没法证明记录没被换过。
            "tests_notes": {
                "capsule_smoke_frames3-5": "跑完才崩（0xC0000005，老毛病）；产物完整，"
                                           "meta 给出 eval_policy=sequential_from_frame_start "
                                           "warmup=2 visited=5",
                "capsule_reject_baseline_frame_40": "应当被拒：NOT_MEASURED，reason 写明"
                                                    "「晚于区间末帧，顺序求值不能回退」，不产出任何数字",
                "mesh_v2_default": "METHOD_OK_NO_SCENE_NUMBERS（默认不出数；--measure 才跑）",
            },
            "eval_policy": {
                "policy": "sequential_from_frame_start",
                "warmup_frames": 2, "visited_frames": 5,
                "why": "P12：seq@109/seq@240 对 P0 逐位相等（D_all=0.000000），冷跳 D_max=1.922861 m",
                "reproduction_delta_vs_attempt10": "f3/f5 逐位相同，f4 差 1 µm"
                                                  "（基线 JSON 存 6 位小数，当场算为全精度）",
            },
            "mesh_v2_selftest": {
                "gate": {"outward_rate": 0.9933, "inward_rate": 0.9867,
                         "inward_depth_median_err_m": -0.000267,
                         "geometry": "UV 球 r=10 cm（解析闭流形），150 点"},
                "controls": {"flipped": {"outward_rate": 0.0067, "inward_rate": 0.0133,
                                        "rejected_as_designed": True},
                             "realm_parity_v1": {"outward_rate": 0.8967, "inward_rate": 0.6633,
                                                 "inward_depth_median_err_m": -0.008649,
                                                 "rejected_as_designed": True}},
                "realm_input_quality": {
                    "islands": 885, "body_islands": 723, "body_polys": 32266,
                    "target_has_skirt_polys": 0, "candidates": 1305,
                    "scoreable_kept": 300, "unscoreable_rate": 0.7701,
                    "sdf_on_realm": {"outward_rate": 0.9367, "inward_rate": 0.9067,
                                     "inward_depth_median_err_m": -0.008226},
                },
                "no_scene_numbers": True,
            },
        },
        "known_risks": [
            "网格口径 v2 的数字只能读成「可计分区域内的深度」：这份交付物体表面 77.01% 连能否计分都不成立，"
            "可计分样本上判对率 0.9367/0.9067 也达不到 95%",
            "v1 的自检本身不公平（薄处/凹折/开放边界让「±法向偏移是否在体内」不良定义），"
            "「v1 的方法错在哪」这句已按此更正；v1 数字仍然作废",
            "胶囊基线只对 Nov-7 这份交付物成立（324 刚体、含 11 个 $name_j），今天重建是 312 刚体、无占位体",
            "基线 JSON 存 6 位小数 → 用版本化基线重跑与当场算基线差 ≤1 µm；下一版存 9 位，已哈希的不改",
            "本笔不含任何场景穿透数字；M04 的最终穿透数字要等可重建的新交付物重取",
            "Blender 仍在退出路径撞 0xC0000005（sys.exit(0) 未阻止），产物完整但退出码非 0",
        ],
    }


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "6"
    builders = {"6": build_attempt6, "7": build_attempt7, "8": build_attempt8,
                "9": build_attempt9, "10": build_attempt10, "11": build_attempt11}
    obj = builders[which]()
    out = sys.argv[2] if len(sys.argv) > 2 else "reports/subai/M04/evidence_m04_attempt%s.json" % which
    # 默认走**规范实现**：`spec` 也就是默认值。要复算 attempt 6–10 那几笔旧记录时显式加
    # `legacy`（旧口径：整份 dict 序列化，不经过 normalize）。
    # 2026-11-16 14:0x 的教训：默认是 legacy 时，我少打一个 `spec` 就写出了一份「长度对、字节不对」
    # 的记录——`check` 判 exit 5，而 `sha256(文件) == digest` 这条等式当场不成立。危险的默认值必须换掉。
    if "legacy" in sys.argv[3:]:
        write(obj, out)
    else:
        write_spec(obj, out, predict="predict" in sys.argv[3:])
