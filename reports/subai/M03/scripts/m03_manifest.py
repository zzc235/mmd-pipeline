"""M03 · 8 条坏样本 manifest / 覆盖矩阵 / 汇总生成器（可重复运行）。

跑法（仓库根目录）：

    python reports/subai/M03/scripts/m03_manifest.py

它做四件事，全部只读：
1. 对每条样本做「路径只做存在性检查」，缺的写 missing，不用近似工程替代；
2. 对可用的 PMX 跑静态归因，每条落 `evidence/static/<id>.json`；
3. 把已采到的 Blender 证据（`evidence/blend/*.json`）挂回样本，标明动态证据是否可用；
4. S8 用真实的 A/B 渲染图算像素摘要，生成 `evidence/ab/` 两份测量 JSON 再比对。

输出：`sample_manifest.json`、`coverage.json`、`summary.json`。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, REPO)

from mmdpipe import diagnose  # noqa: E402

M03 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVID = os.path.join(M03, "evidence")

FEIXIAO_PMX = r"E:\blender模型\没有外套本家模型\星穹铁道—飞霄（无外套）.pmx"
KAFUKA_PMX = (r"E:\blender模型\星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_"
              r"31cc0fe7cc29460474ff5e5cd7188309\星穹铁道—卡芙卡无外套\卡芙卡3.0.pmx")
FEIXIAO_DIR = r"E:\code\Blender\feixiao_short"
PHYS = os.path.join(FEIXIAO_DIR, r"03_shot\physics_test")
MASK_AB = os.path.join(PHYS, "mask_ab")

# 8 条样本。expected_label 来自《项目书》第 4 章；source 写明是历史基线还是本轮实测。
SAMPLES = [
    {
        "id": "S1",
        "expected_label": diagnose.OUT_OF_TAXONOMY,
        "expected_detail": "R0 头发穿模（强制初始穿透）",
        "model": "星穹铁道—飞霄（无外套）",
        "symptom": "头发插进头部/身体，首帧即穿",
        "blend_path": os.path.join(FEIXIAO_DIR, r"04_anim\feixiao_combined_v3.blend"),
        "pmx_path": FEIXIAO_PMX,
        "auxiliary_files": [],
        "required_evidence": ["blender.penetration（逐帧穿入）"],
        "known_numbers": {
            "file_bytes": {"value": 17433907, "source": "项目书 S1（与磁盘实测一致）"},
            "closed_by": {"value": "PMX v2（fixB 线作废）", "source": "项目书 S1"},
        },
        "source": "项目书 S1（已验证 · 已闭环）",
        "blend_evidence": "probe_combined_v3.json",
        "notes": "该文件是【修复后】的场景；R0 是历史症状，本轮没有穿透测量文件，"
                 "不能用它证明 R0 仍存在。当前状态只能读到 F2（未烘焙）。",
    },
    {
        "id": "S2",
        "expected_label": "F4",
        "expected_detail": "零弹簧 + ±90° 宽限位（下摆甩到接近水平）",
        "model": "星穹铁道—飞霄（无外套）",
        "symptom": "转身/甩发/弯腰时布片近水平",
        "blend_path": os.path.join(PHYS, "feixiao_v2_hsr.blend"),
        "pmx_path": FEIXIAO_PMX,
        "auxiliary_files": [],
        "required_evidence": ["structure.wide_limit_units", "blender.unit_angles"],
        "known_numbers": {
            "skirt_rigids_mode2": {"value": 153, "source": "项目书 S2"},
            "root_mass_kg": {"value": 20.0, "source": "项目书 S2（pmx.py 不解析质量，本轮不可复核）"},
            "joint_springs_zero": {"value": 272, "source": "项目书 S2（本轮实测 PMX 全部 389 个关节弹簧为 0）"},
            "root_limit_x_rad": {"value": 1.571, "source": "项目书 S2（本轮实测 max_limit_span=1.570796）"},
        },
        "source": "项目书 S2（已验证 · 待拍板）",
        "blend_evidence": "S3_chest_60f.json",
        "notes": "下摆单元在 PMX 层实测 154 体 / 153 mode2 / 弹簧 0 / 限位 1.570796，"
                 "与项目书一致；「大角度」阈值未标定，只能 suspected。",
    },
    {
        "id": "S3",
        "expected_label": "F3",
        "expected_detail": "硬约束冻结（胸口鼓包/折叠）",
        "model": "星穹铁道—飞霄（无外套）",
        "symptom": "胸区折叠、凸起、穿插，首帧即存在",
        "blend_path": None,
        "pmx_path": FEIXIAO_PMX,
        "auxiliary_files": [],
        "required_evidence": ["structure.frozen_roots", "blender.frozen_pairs"],
        "known_numbers": {
            "chest_rigids": {"value": "PMX idx 24–29", "source": "项目书 S3（本轮静态实测同 6 体）"},
            "baked_increment_f1_f60_deg": {"value": 0.0, "source": "项目书 S3 证据①"},
            "constraint_toggle_vertex_delta_m": {"value": 0.1837, "source": "项目书 S3 证据②(f1)"},
        },
        "source": "项目书 S3（高置信 · 待拍板）",
        "blend_evidence": None,
        "notes": "静态已抓到 7 个焊接冻结根，其中 右胸/左胸 焊在 上半身2 上（6DOF 全锁），"
                 "与项目书一致。可用候选场景里胸口骨没有 COPY_ROTATION（=不是胸口冻结现场），"
                 "动态证据判为 UNAVAILABLE，不硬凑 confirmed。",
    },
    {
        "id": "S4",
        "expected_label": "F5",
        "expected_detail": "骨无刚体（下摆第 11 行穿小腿）",
        "model": "星穹铁道—飞霄（无外套）",
        "symptom": "下摆穿小腿",
        "blend_path": os.path.join(PHYS, "feixiao_phys_row11.blend"),
        "pmx_path": FEIXIAO_PMX,
        "auxiliary_files": [],
        "required_evidence": ["coverage.gaps", "blender.penetration"],
        "known_numbers": {
            "row11_bones_without_rigid": {"value": 11, "source": "项目书 S4（本轮静态实测 11/11）"},
            "penetration_f150_m": {"value": -0.202, "source": "项目书 S4"},
            "rigids_before_after": {"value": [312, 323], "source": "项目书 S4"},
        },
        "source": "项目书 S4（已验证 · 效果已测）",
        "blend_evidence": None,
        "notes": "规范文件 feixiao_phys_row11.blend 在磁盘上已不存在（只有 _废弃 与 .blend1），"
                 "按准则不拿近似工程替代；覆盖缺口由 PMX 静态实测支撑，穿透证据留在 known_numbers。",
    },
    {
        "id": "S5",
        "expected_label": "F3",
        "expected_detail": "硬约束冻结（卡芙卡袖子乱飞）",
        "model": "星穹铁道—卡芙卡（无外套）",
        "symptom": "袖子乱飞 / 被钉在世界空间",
        "blend_path": os.path.join(REPO, "kafuka_all", "scene.blend"),
        "pmx_path": KAFUKA_PMX,
        "auxiliary_files": [],
        "required_evidence": ["structure.frozen_roots", "blender.frozen_pairs"],
        "known_numbers": {
            "welded_joints_pmx": {"value": 57, "source": "本轮静态实测"},
            "frozen_sleeve_bones": {"value": 16, "source": "本轮动态实测 f1→f60"},
            "sleeve_local_delta_deg": {"value": 0.0, "source": "本轮动态实测"},
            "parent_world_delta_deg": {"value": 66.41, "source": "本轮动态实测"},
        },
        "source": "项目书 S5（高置信 · 待拍板）→ 本轮升级为 confirmed",
        "blend_evidence": "S5_sleeve_60f.json",
        "notes": "项目书里 S5 只是「与 S3 同类」的推论；本轮用 16 根袖骨（xk_*）"
                 "「父链 66.41° / 自身 0.0°」的实测把它升级为 confirmed。",
    },
    {
        "id": "S6",
        "expected_label": diagnose.OUT_OF_TAXONOMY,
        "expected_detail": "R0 头发穿模不复位",
        "model": "星穹铁道—飞霄（无外套）",
        "symptom": "头发穿模后不复位",
        "blend_path": None,
        "pmx_path": FEIXIAO_PMX,
        "auxiliary_files": [],
        "required_evidence": ["blender.penetration", "r0.detected"],
        "known_numbers": {
            "mechanism": {"value": "Bullet 初始穿透 R0", "source": "项目书 S6"},
        },
        "source": "项目书 S6（现象/定性完成）",
        "blend_evidence": None,
        "notes": "没有逐帧穿透测量文件；本轮不启动长渲染，R0 判据用合成 fixture 覆盖，"
                 "真实样本留缺（不宣称六类都有真实样本）。",
    },
    {
        "id": "S7",
        "expected_label": "F1",
        "expected_detail": "没 build（下摆直筒不动）",
        "model": "星穹铁道—飞霄（无外套）",
        "symptom": "下摆完全不动、呈直筒",
        "blend_path": os.path.join(PHYS, "飞霄_MMD物理_v1.blend"),
        "pmx_path": FEIXIAO_PMX,
        "auxiliary_files": [],
        "required_evidence": ["blender.mmd_root.is_built", "blender.constraints"],
        "known_numbers": {
            "is_built": {"value": False, "source": "本轮实测"},
            "copy_rotation": {"value": 0, "source": "本轮实测（约束直方图里没有 COPY_ROTATION）"},
            "expected_copy_rotation_after_build": {"value": 264, "source": "项目书 S7（仅飞霄）"},
        },
        "source": "项目书 S7（已验证 · 已解决）",
        "blend_evidence": "probe_v1.json",
        "notes": "实测 is_built=False、COPY_ROTATION=0、未烘焙 → F1 + F2 双命中。",
    },
    {
        "id": "S8",
        "expected_label": "F6",
        "expected_detail": "改了不生效（碰撞掩码）",
        "model": "星穹铁道—飞霄（无外套）",
        "symptom": "按 MMD 分组开双向掩码，穿模毫无改善",
        "blend_path": None,
        "pmx_path": FEIXIAO_PMX,
        "auxiliary_files": sorted(
            os.path.join(MASK_AB, n) for n in
            ("A_before_110.png", "B_after_110.png", "A_before_140.png",
             "B_after_140.png", "A_before_170.png", "B_after_170.png")),
        "required_evidence": ["ab.variable_changed", "ab.fields_compared", "ab.result_identical"],
        "known_numbers": {
            "penetration_frames": {"value": 31, "source": "项目书 S8（历史基线）"},
            "penetration_bone_hits": {"value": 1068, "source": "项目书 S8（历史基线）"},
            "max_depth_m": {"value": -0.291, "source": "项目书 S8（历史基线）"},
            "all_rigids_collision_collections": {"value": "(0,)", "source": "本轮实测 312/312"},
        },
        "source": "项目书 S8（已验证 · 未解决）",
        "blend_evidence": None,
        "notes": "A/B 三对渲染图在像素层逐位相同（0/512000 像素不同），"
                 "PNG 字节不同只是编码元数据差异 —— 两种事实都记下来。",
    },
]


def rel(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return os.path.relpath(path, REPO)
    except ValueError:
        return path


def exists_info(path: str | None) -> dict:
    if not path:
        return {"path": None, "exists": False, "bytes": None, "sha256": None}
    ok = os.path.isfile(path)
    return {
        "path": path,
        "exists": ok,
        "bytes": os.path.getsize(path) if ok else None,
        "sha256": diagnose.sha256_file(path) if ok else None,
    }


def pixel_digest(path: str):
    """返回 (像素摘要, 宽, 高)；没有 PIL 时返回 None。"""
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return None
    with Image.open(path) as img:
        arr = np.asarray(img.convert("RGB"), dtype=np.uint8)
    return hashlib.sha256(arr.tobytes()).hexdigest(), int(arr.shape[1]), int(arr.shape[0])


def build_ab_evidence() -> dict:
    """S8：真实 A/B 渲染图 → 两份测量 JSON → compare_ab。"""
    pairs = [(110, "A_before_110.png", "B_after_110.png"),
             (140, "A_before_140.png", "B_after_140.png"),
             (170, "A_before_170.png", "B_after_170.png")]
    left, right = {}, {}
    detail = []
    for frame, a_name, b_name in pairs:
        a_path, b_path = os.path.join(MASK_AB, a_name), os.path.join(MASK_AB, b_name)
        if not (os.path.isfile(a_path) and os.path.isfile(b_path)):
            return {"available": False, "reason": "A/B 渲染图缺失", "pairs": pairs}
        da, db = pixel_digest(a_path), pixel_digest(b_path)
        if da is None or db is None:
            return {"available": False, "reason": "缺少 PIL/numpy，无法做像素比较", "pairs": pairs}
        left["f%d" % frame] = {"pixels_sha256": da[0], "width": da[1], "height": da[2]}
        right["f%d" % frame] = {"pixels_sha256": db[0], "width": db[1], "height": db[2]}
        detail.append({"frame": frame, "pixels_identical": da[0] == db[0],
                       "bytes_identical": diagnose.sha256_file(a_path) == diagnose.sha256_file(b_path),
                       "a": rel(a_path), "b": rel(b_path)})
    a_doc = {"variable_changed": "collision_collections（A: 原始；B: 按 MMD 分组开双向掩码）",
             "render": left}
    b_doc = {"variable_changed": "collision_collections（A: 原始；B: 按 MMD 分组开双向掩码）",
             "render": right}
    ab_dir = os.path.join(EVID, "ab")
    os.makedirs(ab_dir, exist_ok=True)
    a_json, b_json = os.path.join(ab_dir, "S8_A_render.json"), os.path.join(ab_dir, "S8_B_render.json")
    diagnose.write_json(a_json, a_doc)
    diagnose.write_json(b_json, b_doc)
    ab = diagnose.compare_ab(a_doc, b_doc)
    ab["pixel_pairs"] = detail
    return {"available": True, "ab": ab, "a": rel(a_json), "b": rel(b_json), "pairs": detail}


def static_diagnosis(sample: dict, config: dict) -> dict:
    pmx = sample["pmx_path"]
    if not pmx or not os.path.isfile(pmx):
        return {"available": False, "reason": "PMX 缺失"}
    out = os.path.join(EVID, "static", "%s.json" % sample["id"])
    report = diagnose.diagnose_pmx(pmx, out, config=config)
    return {
        "available": True,
        "file": rel(out),
        "primary": report["primary"],
        "confidence": report["confidence"],
        "fingerprint": report["judgment_fingerprint"],
        "input_sha256": report["input_sha256"],
        "matched": {d["id"]: d["confidence"] for d in report["diagnostics"] if d["matched"]},
        "diagnostics": {d["id"]: d["confidence"] for d in report["diagnostics"]},
        "_evidence": report["evidence"],
    }


def blend_state(sample: dict) -> dict:
    name = sample.get("blend_evidence")
    if not name:
        return {"available": False, "reason": "未采集 Blender 证据"}
    path = os.path.join(EVID, "blend", name)
    if not os.path.isfile(path):
        return {"available": False, "reason": "证据文件 %s 不存在" % name}
    with open(path, encoding="utf-8") as fh:
        report = json.load(fh)
    b = report["evidence"].get("blender") or {}
    dyn = b.get("dynamic") or {}
    return {
        "available": True,
        "file": rel(path),
        "status": report.get("status"),
        "primary": report.get("primary"),
        "confidence": report.get("confidence"),
        "fingerprint": report.get("judgment_fingerprint"),
        "input_sha256": report.get("input_sha256"),
        "diagnostics": {d["id"]: d["confidence"] for d in report["diagnostics"]},
        "matched": {d["id"]: d["confidence"] for d in report["diagnostics"] if d["matched"]},
        "is_built": (b.get("mmd_root") or {}).get("is_built"),
        "constraints": b.get("constraints"),
        "cache": b.get("point_cache"),
        "frames_sampled": dyn.get("frames_sampled"),
        "evidence_mode": (report.get("frame_range") or {}).get("evidence_mode"),
        "_evidence": report.get("evidence") or {},
    }


def judge_sample(sample: dict, static: dict, blend: dict) -> dict:
    """expected vs 实际。

    判「命中」看的是 matched 集合，不是只看 primary —— 多故障共存时
    primary 只会是分最高的那个，F5/F4 仍然可以是真的命中。
    """
    expected = sample["expected_label"]
    observed = []
    for source, payload in (("static", static), ("blend", blend)):
        if not payload.get("available"):
            continue
        matched = payload.get("matched") or {}
        if expected in matched:
            level = matched[expected]
        elif payload.get("primary") in (diagnose.INSUFFICIENT_EVIDENCE, diagnose.UNKNOWN):
            level = "unverified"
        else:
            level = "absent"
        observed.append({
            "source": source,
            "primary": payload.get("primary"),
            "confidence": payload.get("confidence"),
            "expected_level": level,
            "file": payload.get("file"),
        })

    levels = [o["expected_level"] for o in observed]
    if diagnose.CONFIRMED in levels:
        outcome = "match_confirmed"
    elif diagnose.SUSPECTED in levels:
        outcome = "match_suspected"
    elif all(lv == "unverified" for lv in levels) or not levels:
        outcome = "unverified"
    else:
        outcome = "mismatch"

    note = {
        "match_confirmed": "期望 %s，实测 confirmed" % expected,
        "match_suspected": "期望 %s，实测只到 suspected" % expected,
        "unverified": "期望 %s，本轮证据不足，未验证" % expected,
        "mismatch": "期望 %s，实际读到 %s" % (expected, [o["primary"] for o in observed]),
    }[outcome]

    return {
        "expected": expected,
        "outcome": outcome,
        "observed": observed,
        "note": note,
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    config = diagnose.default_config()
    os.makedirs(os.path.join(EVID, "static"), exist_ok=True)

    ab_evidence = build_ab_evidence()

    manifest = []
    for sample in SAMPLES:
        pmx = exists_info(sample["pmx_path"])
        blend = exists_info(sample["blend_path"])
        aux = [exists_info(p) for p in sample["auxiliary_files"]]
        have = [pmx["exists"], blend["exists"]]
        path_status = "available" if all(have) else ("partial" if any(have) else "missing")

        static = static_diagnosis(sample, config)
        if sample["id"] == "S8" and ab_evidence.get("available"):
            # S8 用真实 A/B 再判一次，F6 才有证据
            out = os.path.join(EVID, "static", "S8_f6.json")
            report = diagnose.diagnose_pmx(sample["pmx_path"], out, ab=ab_evidence["ab"],
                                           config=config)
            static = {
                "available": True, "file": rel(out), "primary": report["primary"],
                "confidence": report["confidence"],
                "fingerprint": report["judgment_fingerprint"],
                "input_sha256": report["input_sha256"],
                "matched": {d["id"]: d["confidence"]
                            for d in report["diagnostics"] if d["matched"]},
                "diagnostics": {d["id"]: d["confidence"] for d in report["diagnostics"]},
                "with_ab": True,
                "_evidence": report["evidence"],
            }

        evidence_blend = blend_state(sample)

        present = {}
        for key in sample["required_evidence"]:
            present[key] = any(
                diagnose._get(p.get("_evidence") or {}, key) is not None
                for p in (static, evidence_blend))
        static.pop("_evidence", None)
        evidence_blend.pop("_evidence", None)

        verdict = judge_sample(sample, static, evidence_blend)

        manifest.append({
            "id": sample["id"],
            "expected_label": sample["expected_label"],
            "expected_detail": sample["expected_detail"],
            "taxonomy_version": diagnose.TAXONOMY_VERSION,
            "model": sample["model"],
            "symptom": sample["symptom"],
            "blend_path": blend["path"],
            "pmx_path": pmx["path"],
            "auxiliary_files": [a["path"] for a in aux],
            "path_status": path_status,
            "required_evidence": sample["required_evidence"],
            "known_numbers": sample["known_numbers"],
            "source": sample["source"],
            "availability": {
                "pmx": pmx["exists"],
                "blend": blend["exists"],
                "auxiliary_present": sum(1 for a in aux if a["exists"]),
                "auxiliary_total": len(aux),
                "static_diagnosis": static,
                "blend_diagnosis": evidence_blend,
            },
            "verdict": verdict,
            "required_evidence_present": present,
            "notes": sample["notes"],
        })

    coverage = build_coverage(manifest, ab_evidence)
    summary = build_summary(manifest, coverage, ab_evidence)

    diagnose.write_json(os.path.join(M03, "sample_manifest.json"),
                        {"schema_version": diagnose.SCHEMA_VERSION,
                         "taxonomy_version": diagnose.TAXONOMY_VERSION,
                         "generated_from": "m03_manifest.py",
                         "samples": manifest})
    diagnose.write_json(os.path.join(M03, "coverage.json"), coverage)
    diagnose.write_json(os.path.join(M03, "summary.json"), summary)

    print("%-4s %-16s %-30s %-16s %s" % ("id", "expected", "observed(matched)", "outcome", "note"))
    for item in manifest:
        v = item["verdict"]
        obs = "; ".join(
            "%s:%s[%s]" % (o["source"][0], o["primary"], o["expected_level"])
            for o in v["observed"]) or "-"
        print("%-4s %-16s %-30s %-16s %s" % (item["id"], v["expected"], obs, v["outcome"],
                                             v["note"][:50]))
    print("\ncoverage:", json.dumps(coverage["matrix"], ensure_ascii=False))
    print("summary:", json.dumps(summary["counts"], ensure_ascii=False))
    return 0


def build_coverage(manifest: list, ab_evidence: dict) -> dict:
    """真实样本 / 合成样本 / 缺口，分开数。

    按【不同的证据文件】计数，不按样本条数 —— 同一个飞霄 PMX 被 7 条样本复用，
    按样本数会把 F3/F4/F5 的「真实覆盖」放大 7 倍。
    """
    all_labels = list(diagnose.TAXONOMY_ORDER) + [
        diagnose.OUT_OF_TAXONOMY, diagnose.UNKNOWN, diagnose.INSUFFICIENT_EVIDENCE]
    per_label: dict[str, dict[str, dict]] = {label: {} for label in all_labels}
    rank = diagnose.CONFIDENCE_RANK

    for item in manifest:
        for source in ("static_diagnosis", "blend_diagnosis"):
            info = item["availability"].get(source) or {}
            evidence_file = info.get("input_sha256") or info.get("file") or                 "%s:%s" % (item["id"], source)
            for label, conf in (info.get("matched") or {}).items():
                if label not in per_label:
                    continue
                slot = per_label[label].setdefault(
                    evidence_file, {"confidence": conf, "samples": []})
                if rank.get(conf, 0) > rank.get(slot["confidence"], 0):
                    slot["confidence"] = conf
                if item["id"] not in slot["samples"]:
                    slot["samples"].append(item["id"])

    synthetic = {
        "F1": 1, "F2": 1, "F3": 1, "F4": 1, "F5": 1, "F6": 1,
        diagnose.OUT_OF_TAXONOMY: 1, diagnose.UNKNOWN: 1,
    }
    matrix = {}
    for label in all_labels:
        files = per_label[label]
        confirmed = sum(1 for v in files.values() if v["confidence"] == diagnose.CONFIRMED)
        suspected = sum(1 for v in files.values() if v["confidence"] == diagnose.SUSPECTED)
        matrix[label] = {
            "distinct_evidence_files": len(files),
            "evidence_files": {k: {"confidence": v["confidence"], "samples": v["samples"]}
                               for k, v in sorted(files.items())},
            "confirmed": confirmed,
            "suspected": suspected,
            "synthetic_fixture": synthetic.get(label, 0),
            "labelled_sample": any(m["expected_label"] == label for m in manifest),
            "gap": ("缺真实确认样本" if confirmed == 0 else ""),
        }

    return {
        "schema_version": diagnose.SCHEMA_VERSION,
        "taxonomy_version": diagnose.TAXONOMY_VERSION,
        "matrix": matrix,
        "labelled_samples": {m["id"]: m["expected_label"] for m in manifest},
        "notes": [
            "F2 没有独立的样本标签（项目书 8 条里没有一条标 F2），"
            "但本轮在 S1/S7 的文件上实测到 is_baked=False；合成 fixture 兜底。",
            "R0 没有真实测量文件（S1/S6 都缺逐帧穿透数据），只有合成 fixture 与 "
            "「known_numbers 历史基线」，不宣称 R0 有真实样本。",
            "S3 的胸口冻结只在 PMX 静态结构上命中；可用场景里没有胸口 COPY_ROTATION，"
            "动态证据 UNAVAILABLE。",
            "S4 的规范工程文件已不存在，覆盖缺口由 PMX 静态实测支撑。",
        ],
        "ab_available": bool(ab_evidence.get("available")),
        "ab_note": (ab_evidence.get("ab", {}).get("source") if ab_evidence.get("available")
                    else ab_evidence.get("reason")),
    }


def build_summary(manifest: list, coverage: dict, ab_evidence: dict) -> dict:
    counts = {
        "samples": len(manifest),
        "match_confirmed": 0,
        "match_suspected": 0,
        "mismatch": 0,
        "unverified": 0,
        "no_evidence": 0,
        "missing_files": 0,
        "out_of_taxonomy": 0,
        "evidence_insufficient": 0,
    }
    additional_findings, false_negatives = [], []
    for item in manifest:
        outcome = item["verdict"]["outcome"]
        counts[outcome] = counts.get(outcome, 0) + 1
        if item["path_status"] != "available":
            counts["missing_files"] += 1
        if item["verdict"]["expected"] == diagnose.OUT_OF_TAXONOMY:
            counts["out_of_taxonomy"] += 1
        for obs in item["verdict"]["observed"]:
            if obs["primary"] == diagnose.INSUFFICIENT_EVIDENCE:
                counts["evidence_insufficient"] += 1
            if obs["confidence"] == diagnose.CONFIRMED \
                    and obs["expected_level"] != diagnose.CONFIRMED:
                additional_findings.append({
                    "sample": item["id"], "source": obs["source"],
                    "primary": obs["primary"],
                    "note": "confirmed 了一个不是该样本 label 的故障；需确认它是新的真实发现",
                })
        if item["verdict"]["expected"] in tuple(diagnose.TAXONOMY_ORDER) + (
                diagnose.OUT_OF_TAXONOMY,) and outcome != "match_confirmed":
            false_negatives.append({
                "sample": item["id"], "expected": item["verdict"]["expected"],
                "outcome": outcome, "note": item["verdict"]["note"],
            })

    return {
        "schema_version": diagnose.SCHEMA_VERSION,
        "taxonomy_version": diagnose.TAXONOMY_VERSION,
        "counts": counts,
        "false_positives": 0,
        "false_positive_note": (
            "本轮没有「confirmed 了一个与该样本已知事实冲突的故障」；"
            "S1/S5 上多出来的 F2（未烘焙）是实测状态，不是误报，单列在 additional_findings。"),
        "false_negatives": false_negatives,
        "false_negative_note": (
            "漏报按「期望 label 没到 confirmed」统计：S2/S3/S4 只到 suspected（阈值未标定或缺动态证据），"
            "S1/S6 期望 R0 但本轮没有逐帧穿透测量。"),
        "additional_findings": additional_findings,
        "per_sample": {m["id"]: {"expected": m["expected_label"],
                                 "outcome": m["verdict"]["outcome"],
                                 "observed": m["verdict"]["observed"]} for m in manifest},
        "coverage_gaps": [k for k, v in coverage["matrix"].items() if v["gap"]],
        "ab": {"available": bool(ab_evidence.get("available")),
               "result_identical": (ab_evidence.get("ab") or {}).get("result_identical")},
        "honesty": [
            "没有「8/8 全部正确」这回事：本轮到 confirmed 的只有 S5(F3)、S7(F1)、S8(F6)。",
            "S1/S6 期望 R0，但这两轮没有可用的逐帧穿透测量，按 unverified/mismatch 记，不算通过。",
            "S2(F4)/S3(F3)/S4(F5) 都只到 suspected，阈值或动态证据缺失，已写进 missing_evidence。",
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
