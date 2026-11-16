"""归因判据引擎（F1–F6 + R0）—— 纯 Python，不 import bpy。

用途
----
把项目书第 5 章的「归因判据树」做成可测试的判定器：

    F1 没 build           结构存在但骨骼约束链缺失
    F2 没烘焙             point_cache.is_baked=False
    F3 硬约束冻结         焊接结构 + 运动父链下目标相对增量≈0
    F4 零弹簧宽限位       单元弹簧全 0 + 宽限位 + 大角度实测
    F5 骨无刚体           骨—刚体覆盖缺口 + 与局部穿模对应
    F6 改了不生效         A/B 唯一变量明确且结果逐位相同
    R0 Bullet 初始穿透    不在 F1–F6 内，显式 OUT_OF_TAXONOMY

设计约束（来自任务书 M03）
-------------------------
* 判据函数只吃结构化 evidence，不散落调用 bpy —— 这样能用合成数据测。
* 每个判据返回 matched / confidence / reason / evidence_keys / missing_evidence。
* 多故障共存：primary 按证据完整度选，其余进 secondary，不用 if 顺序掩盖。
* 缺证据输出 INSUFFICIENT_EVIDENCE，不能算 PASS。
* 阈值写进 config 并记录来源；F4 未标定时只出 suspected。

两个入口
--------
    python -m mmdpipe.diagnose --pmx "模型.pmx" --out "diagnosis.json"
    python -m mmdpipe.diagnose --pmx A.pmx --ab a.json b.json --out d.json

退出码
------
    0  JSON 已写盘（status=ok/partial 都算成功）
    1  只有显式 --fail-on-confirmed 时，且 primary 置信度为 confirmed
    2  命令行参数错误
    3  输入不可读 / PMX 解析失败（不写半成品 JSON）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

from . import physics
from . import pmx as pmx_mod

# ---------------------------------------------------------------- 契约常量
SCHEMA_VERSION = "diagnose/1"
TAXONOMY_VERSION = "F1-F6+R0/1"
TOOL = "mmdpipe.diagnose"
TOOL_VERSION = "0.1.0"

F1, F2, F3, F4, F5, F6 = "F1", "F2", "F3", "F4", "F5", "F6"
R0 = "R0"
OUT_OF_TAXONOMY = "OUT_OF_TAXONOMY"
UNKNOWN = "UNKNOWN"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

TAXONOMY_ORDER = (F1, F2, F3, F4, F5, F6)
ALLOWED_PRIMARY = TAXONOMY_ORDER + (OUT_OF_TAXONOMY, UNKNOWN, INSUFFICIENT_EVIDENCE)

CONFIRMED, SUSPECTED, INSUFFICIENT = "confirmed", "suspected", "insufficient"
CONFIDENCE_RANK = {CONFIRMED: 3, SUSPECTED: 2, INSUFFICIENT: 1}

EXIT_OK = 0
EXIT_CONFIRMED = 1
EXIT_USAGE = 2
EXIT_INPUT = 3

_CRITERION_TITLE = {
    F1: "没 build（约束链缺失）",
    F2: "没烘焙（point_cache 未烘焙）",
    F3: "硬约束冻结",
    F4: "零弹簧 + 宽限位",
    F5: "骨无刚体（覆盖缺口）",
    F6: "改了不生效",
    OUT_OF_TAXONOMY: "分类学外（Bullet 初始穿透 R0）",
}

# ---------------------------------------------------------------- 阈值配置
# 每个阈值都写「来源」，避免下次有人凭感觉改数字。
DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "thresholds": {
        # 焊接判据本身来自 pmx.py 的 limit_span==0 && spring_max==0，不在这里重复
        "spring_zero_eps": {
            "value": 1e-9,
            "unit": "rad",
            "source": "pmx.py Joint.springs_zero 同一口径",
        },
        # S3 证据①：烘焙增量 f1→f60 旋转变化 = 0.00000°；留 0.5° 容差吃浮点噪声
        "f3_frozen_deg": {
            "value": 0.5,
            "unit": "deg",
            "source": "项目书 S3 证据① baked_increment2 = 0.00000°",
        },
        # 未标定：5° 只是「父链确实在动」的下限，不是物理标定值
        "f3_parent_motion_deg": {
            "value": 5.0,
            "unit": "deg",
            "source": "未标定（保守下限），待 M04 用门禁数据复核",
            "calibrated": False,
        },
        # S2：根部 18 关节 X 限位 ±1.571 rad；1.2 rad ≈ 68.8° 以下不算「宽」
        "f4_wide_limit_rad": {
            "value": 1.2,
            "unit": "rad",
            "source": "项目书 S2 根部限位 ±1.5708 rad（±90°）",
        },
        # 「大角度实测」阈值：S2 布片近水平，未做逐帧角度标定
        "f4_angle_deg": {
            "value": 60.0,
            "unit": "deg",
            "source": "未标定（暂按『接近水平』的保守下限）；S3 正常舞蹈场景实测摆角 179.231°，"
                      "说明绝对值本身不足以区分正常与异常——真标定须等 M02 的 S2 真阳性样本，"
                      "在此之前 F4 只许 suspected（见 f4_calibrated）",
            "calibrated": False,
        },
        # 覆盖缺口：整行/整组缺失才算主缺口，零散缺 1 根只记为 sparse
        "f5_gap_ratio": {
            "value": 0.5,
            "unit": "row",
            "source": "S4 第 11 行 11/11 根骨无刚体（实测 ratio=1.0）",
        },
        # F6：A/B 数值逐位比较的容差
        "f6_numeric_eps": {
            "value": 1e-9,
            "unit": "raw",
            "source": "S8 A/B 逐位相同（两次结果完全一样）",
        },
    },
    "f4_calibrated": False,
    "f3_calibrated": False,
}


def default_config() -> dict:
    """深拷贝，避免调用方改到模块级默认值。"""
    return json.loads(json.dumps(DEFAULT_CONFIG))


def _threshold(config: dict, key: str) -> float:
    spec = (config.get("thresholds") or {}).get(key) or {}
    if isinstance(spec, dict):
        return float(spec.get("value"))
    return float(spec)


def _threshold_meta(config: dict, key: str) -> dict:
    return dict((config.get("thresholds") or {}).get(key) or {})


# ---------------------------------------------------------------- 小工具
def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _get(ev: dict, dotted: str, default=None):
    """按点号取嵌套字段；任一层缺失返回 default。"""
    cur: Any = ev
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _ev(key: str, value: Any, unit: str | None = None, compare: Any = None,
        frames: Any = None, source: str = "pmx") -> dict:
    """一条带字段名/实测值/比较对象/单位/帧范围/来源的证据。"""
    return {
        "key": key,
        "value": value,
        "unit": unit,
        "compare": compare,
        "frames": frames,
        "source": source,
    }


def _blank(cid: str) -> dict:
    return {
        "id": cid,
        "title": _CRITERION_TITLE.get(cid, cid),
        "matched": False,
        "confidence": INSUFFICIENT,
        "reason": "",
        "score": 0.0,
        "evidence": [],
        "evidence_keys": [],
        "missing_evidence": [],
    }


def _finish(diag: dict, matched: bool, confidence: str, reason: str,
            evidence: list | None = None, missing: list | None = None,
            score: float = 0.0) -> dict:
    diag["matched"] = bool(matched)
    diag["confidence"] = confidence
    diag["reason"] = reason
    diag["evidence"] = evidence or []
    diag["evidence_keys"] = [e["key"] for e in diag["evidence"]]
    diag["missing_evidence"] = sorted({str(m) for m in (missing or [])})
    diag["score"] = round(float(score), 3)
    return diag


# ============================================================ 静态采集（PMX）
def _family_of(name: str):
    """把 `下擺_11_7` 拆成 (family, [11, 7])；拆不出返回 (None, [])。"""
    parts = str(name).split("_")
    if len(parts) < 2:
        return None, []
    nums = []
    for p in parts[1:]:
        if p.isdigit():
            nums.append(int(p))
    return parts[0], nums


def _coverage(model, config: dict) -> dict:
    """骨—刚体覆盖：按「族 + 行」统计缺口，输出具体骨名而不是只有数量。"""
    gap_ratio = _threshold(config, "f5_gap_ratio")
    rigid_bones = {b.name for b in model.rigids}
    families: dict[str, list] = {}
    for b in model.bones:
        fam, nums = _family_of(b.name)
        if fam is None or len(nums) < 2:
            continue
        families.setdefault(fam, []).append((b.name, nums))

    gaps: list[dict] = []
    sparse: list[dict] = []
    whole_missing: list[dict] = []
    summary = []
    for fam, members in sorted(families.items()):
        if len(members) < 6:
            continue
        rows: dict[int, list] = {}
        for name, nums in members:
            rows.setdefault(nums[0], []).append(name)
        covered = 0
        fam_gaps = []
        for row in sorted(rows):
            bones = sorted(rows[row])
            miss = [n for n in bones if n not in rigid_bones]
            hit = len(bones) - len(miss)
            covered += hit
            if not miss:
                continue
            ratio = len(miss) / len(bones)
            item = {
                "family": fam,
                "row": row,
                "bones_total": len(bones),
                "bones_missing": miss,
                "missing_count": len(miss),
                "missing_ratio": round(ratio, 3),
            }
            if hit == 0:
                whole_missing.append(item)
                fam_gaps.append(item)
            elif ratio >= gap_ratio:
                fam_gaps.append(item)
            else:
                sparse.append(item)
        gaps.extend(fam_gaps)
        summary.append({
            "family": fam,
            "bones": len(members),
            "rows": len(rows),
            "bones_with_rigid": covered,
            "bones_without_rigid": len(members) - covered,
        })

    # 整族一个刚体都没有（≥6 根骨）也是缺口
    for entry in summary:
        if entry["bones_with_rigid"] == 0:
            whole_missing.append({
                "family": entry["family"],
                "row": None,
                "bones_total": entry["bones"],
                "bones_missing": [],
                "missing_count": entry["bones"],
                "missing_ratio": 1.0,
            })

    return {
        "bones_total": len(model.bones),
        "bones_with_any_rigid": len({b.name for b in model.rigids} & {b.name for b in model.bones}),
        "families": summary,
        "gaps": gaps,
        "whole_missing": whole_missing,
        "sparse_gaps": sparse,
        "gap_ratio_threshold": gap_ratio,
        "method": "骨名按『族_行_列』拆分，逐行统计无刚体的骨；≥阈值算 gap，零散缺算 sparse",
    }


def _frozen_roots(model) -> list:
    """F3 静态命中：焊接关节把「会回填骨骼的刚体」钉在另一个刚体上。

    判据（不含名字）：joint 限位全 0 且弹簧全 0 → 两侧刚体刚性耦合；
    其中一侧是 mode1/2（会回填骨骼）、另一侧是 mode0（跟骨、本身不参与解算）
    → 那一侧的回填体被冻结在世界空间。
    """
    out = []
    for j in model.joints:
        if not j.welded:
            continue
        a = model.rigids[j.rigid_a] if 0 <= j.rigid_a < len(model.rigids) else None
        b = model.rigids[j.rigid_b] if 0 <= j.rigid_b < len(model.rigids) else None
        if a is None or b is None:
            continue
        a_fb, b_fb = a.mode in physics.FEEDBACK_MODES, b.mode in physics.FEEDBACK_MODES
        if a_fb and not b_fb:
            target, anchor = a, b
        elif b_fb and not a_fb:
            target, anchor = b, a
        else:
            continue
        target_bone = _bone_name(model, target.bone)
        out.append({
            "joint": j.index,
            "joint_name": j.name,
            "target_body": target.index,
            "target_bone": target_bone,
            "bone_bound": bool(target_bone),
            "anchor_body": anchor.index,
            "anchor_bone": _bone_name(model, anchor.bone),
            "target_mode": target.mode,
            "limit_span_rad": round(j.limit_span, 6),
            "spring_max": round(j.spring_max, 6),
        })
    return out


def _bone_name(model, idx: int) -> str:
    if 0 <= idx < len(model.bones):
        return model.bones[idx].name
    return ""


def _frozen_chains(model, roots: list) -> list:
    """从冻结根只沿「焊接关节」扩张，给出被刚性焊在一起的那一块。

    不跨带限位的柔性关节：胸口 6 体里 `右胸１/右胸２` 限位 0.5236 rad 仍能弯，
    把整条链都算成「冻死」会夸大结论。焊死只到哪、就只报到哪。
    """
    if not roots:
        return []
    by_body: dict[int, list] = {}
    for j in model.joints:
        if not j.welded:
            continue
        for rid in (j.rigid_a, j.rigid_b):
            if 0 <= rid < len(model.rigids):
                by_body.setdefault(rid, []).append(j)
    chains = []
    for root in roots:
        seen = {root["target_body"]}
        queue = [root["target_body"]]
        while queue:
            rid = queue.pop()
            for j in by_body.get(rid, []):
                other = j.rigid_b if j.rigid_a == rid else j.rigid_a
                if other in seen or not (0 <= other < len(model.rigids)):
                    continue
                seen.add(other)
                queue.append(other)
        bodies = sorted(seen)
        chains.append({
            "anchor_bone": root["anchor_bone"],
            "root_body": root["target_body"],
            "bodies": bodies,
            "bones": [_bone_name(model, model.rigids[i].bone) for i in bodies],
            "body_count": len(bodies),
            "expansion": "welded_joints_only",
        })
    return chains


def _units_static(model, rep, config: dict) -> list:
    spring_eps = _threshold(config, "spring_zero_eps")
    wide_rad = _threshold(config, "f4_wide_limit_rad")
    units = []
    for u in rep.units:
        js = [model.joints[i] for i in u.joint_ids if 0 <= i < len(model.joints)]
        span = max((j.limit_span for j in js), default=0.0)
        spring = max((j.spring_max for j in js), default=0.0)
        feedback = sum(c for m, c in u.modes.items() if m in physics.FEEDBACK_MODES)
        units.append({
            "uid": u.uid,
            "anchor_bone": u.anchor_bone,
            "bodies": len(u.bodies),
            "joints": len(u.joint_ids),
            "modes": {str(k): v for k, v in sorted(u.modes.items())},
            "feedback_bodies": feedback,
            "spring_max": round(spring, 6),
            "limit_span_rad": round(span, 6),
            "welded_joints": u.welded_joints,
            "flex_joints": u.flex_joints,
            "cycle_rank": u.cycle_rank,
            "zero_spring": spring <= spring_eps,
            "wide_limit": span >= wide_rad,
        })
    return units


def collect_pmx(path: str, config: dict | None = None) -> dict:
    """PMX 静态结构证据。只读，不写回。"""
    config = config or default_config()
    model = pmx_mod.load(path)
    rep = physics.classify(model)
    modes: dict[str, int] = {}
    for r in model.rigids:
        modes[str(r.mode)] = modes.get(str(r.mode), 0) + 1
    feedback = sum(c for m, c in modes.items() if int(m) in physics.FEEDBACK_MODES)
    roots = _frozen_roots(model)
    units = _units_static(model, rep, config)

    return {
        "source": {
            "type": "pmx",
            "path": os.path.abspath(path),
            "sha256": sha256_file(path),
            "bytes": os.path.getsize(path),
        },
        "model": {
            "name": model.name,
            "version": model.version,
            "encoding": model.encoding,
            "vertices": model.vertex_count,
            "materials": len(model.materials),
            "morphs": len(model.morphs),
            "bones": len(model.bones),
            "rigids": len(model.rigids),
            "joints": len(model.joints),
        },
        "structure": {
            "rigid_modes": modes,
            "feedback_rigids": feedback,
            "joints_total": len(model.joints),
            "joints_zero_spring": sum(1 for j in model.joints if j.springs_zero),
            "joints_zero_limit": sum(1 for j in model.joints if j.limits_zero),
            "welded_joints": sum(1 for j in model.joints if j.welded),
            "max_limit_span_rad": round(max((j.limit_span for j in model.joints), default=0.0), 6),
            "wide_limit_joints": sum(
                1 for j in model.joints
                if j.limit_span >= _threshold(config, "f4_wide_limit_rad")),
            "frozen_roots": roots,
            "frozen_chains": _frozen_chains(model, roots),
            "mass_available": False,  # pmx.py 未解析质量字段，见 known_limits
            "units": units,
            "wide_limit_units": [u for u in units if u["zero_spring"] and u["wide_limit"]],
            "welded_bones": rep.mute_bones,
            "suspect_units": rep.suspect_units,
            "accessory": rep.accessory,
        },
        "coverage": _coverage(model, config),
    }


# ============================================================ A/B 比较（F6）
def compare_ab(a: dict, b: dict, config: dict | None = None) -> dict:
    """比较两份测量 JSON，产出 F6 证据。

    只比较数值/字符串叶子；键路径相同的按 f6_numeric_eps 判等。
    不比较 generated_at / 路径 / 时间这类元数据。
    """
    config = config or default_config()
    eps = _threshold(config, "f6_numeric_eps")
    skip = {"generated_at", "timestamp", "time", "elapsed", "elapsed_s", "wall_s", "sha256",
            "path", "blend", "input_path", "output", "out", "experiment_id"}

    def walk(node, prefix=""):
        if isinstance(node, dict):
            for k in sorted(node):
                if k in skip:
                    continue
                yield from walk(node[k], "%s.%s" % (prefix, k) if prefix else str(k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                yield from walk(v, "%s[%d]" % (prefix, i))
        else:
            yield prefix, node

    left = dict(walk(a))
    right = dict(walk(b))
    fields = sorted(set(left) | set(right))
    identical, differing = [], []
    for f in fields:
        if f not in left or f not in right:
            differing.append(f)
            continue
        x, y = left[f], right[f]
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            same = abs(float(x) - float(y)) <= eps
        else:
            same = x == y
        (identical if same else differing).append(f)

    return {
        "fields_compared": fields,
        "identical_fields": identical,
        "differing_fields": differing,
        "result_identical": not differing,
        "variable_changed": a.get("variable_changed") or b.get("variable_changed") or "unknown",
        "source": "compare_ab",
    }


# ============================================================ 判据
def _f1(ev, cfg):
    d = _blank(F1)
    is_built = _get(ev, "blender.mmd_root.is_built")
    hist = _get(ev, "blender.constraints")
    feedback = _get(ev, "structure.feedback_rigids")
    evid, missing = [], []
    if is_built is not None:
        evid.append(_ev("blender.mmd_root.is_built", is_built, unit="bool",
                        compare="应为 True 才算已建链", source="blend"))
    if hist is not None:
        chain = int(hist.get("COPY_ROTATION", 0)) + int(hist.get("COPY_TRANSFORMS", 0))
        evid.append(_ev("blender.constraints", chain, unit="constraint",
                        compare=">0 表示约束链存在", source="blend"))
    if feedback is not None:
        evid.append(_ev("structure.feedback_rigids", feedback, unit="body",
                        compare="mode1/2 会回填骨骼的刚体数", source="pmx"))

    if is_built is False:
        return _finish(d, True, CONFIRMED,
                       "mmd_root.is_built=False：模型没有 build，骨骼上不会有物理约束链",
                       evid, missing, score=3.0)
    if hist is not None:
        chain = int(hist.get("COPY_ROTATION", 0)) + int(hist.get("COPY_TRANSFORMS", 0))
        if chain == 0 and (feedback or 0) > 0:
            return _finish(d, True, CONFIRMED,
                           "存在 %d 个回填刚体但骨骼约束数为 0：刚体有、约束链缺失" % feedback,
                           evid, missing, score=3.0)
        if chain > 0:
            return _finish(d, False, INSUFFICIENT,
                           "骨骼上已有 %d 条 COPY_ROTATION/COPY_TRANSFORMS，排除 F1" % chain,
                           evid, missing, score=0.0)
    if is_built is None and hist is None:
        missing = ["blender.mmd_root.is_built", "blender.constraints"]
        return _finish(d, False, INSUFFICIENT,
                       "缺少 Blender 运行期证据，静态 PMX 无法判断是否 build", evid, missing)
    return _finish(d, False, INSUFFICIENT, "证据不足以判定 F1", evid, missing)


def _f2(ev, cfg):
    d = _blank(F2)
    baked = _get(ev, "blender.point_cache.is_baked")
    start = _get(ev, "blender.point_cache.frame_start")
    end = _get(ev, "blender.point_cache.frame_end")
    evid, missing = [], []
    if baked is not None:
        evid.append(_ev("blender.point_cache.is_baked", baked, unit="bool",
                        compare="False = 未烘焙", source="blend"))
    if start is not None and end is not None:
        evid.append(_ev("blender.point_cache.frame_range", [start, end], unit="frame",
                        frames={"start": start, "end": end}, source="blend"))
    if baked is None:
        missing = ["blender.point_cache.is_baked", "blender.point_cache.frame_start/end"]
        return _finish(d, False, INSUFFICIENT,
                       "没有读取到 point_cache 状态，无法判断是否烘焙", evid, missing)
    if baked is True:
        return _finish(d, False, INSUFFICIENT,
                       "point_cache.is_baked=True，排除 F2", evid, missing)
    if start is None or end is None:
        missing = ["blender.point_cache.frame_start", "blender.point_cache.frame_end"]
        return _finish(d, True, SUSPECTED,
                       "is_baked=False，但缺缓存帧范围，不能确认范围覆盖了动作区间",
                       evid, missing, score=1.0)
    return _finish(d, True, CONFIRMED,
                   "point_cache.is_baked=False，缓存范围 f%s–f%s 未烘焙：拖时间轴不动、播放才动" % (start, end),
                   evid, missing, score=3.0)


def _f3(ev, cfg):
    d = _blank(F3)
    frozen_deg = _threshold(cfg, "f3_frozen_deg")
    parent_deg = _threshold(cfg, "f3_parent_motion_deg")
    roots = _get(ev, "structure.frozen_roots")
    chains = _get(ev, "structure.frozen_chains")
    pairs = _get(ev, "blender.frozen_pairs")
    mute = _get(ev, "blender.mute_world_delta_m")
    evid, missing = [], []

    if roots is not None:
        evid.append(_ev("structure.frozen_roots", len(roots), unit="joint",
                        compare="焊接关节且一侧会回填骨骼", source="pmx"))
        if roots:
            evid.append(_ev("structure.frozen_roots.detail", roots[:8], unit="joint",
                            compare="6 自由度全锁 lower=upper=0", source="pmx"))
    if chains:
        evid.append(_ev("structure.frozen_chains",
                        [{"anchor": c["anchor_bone"], "bodies": c["body_count"]} for c in chains],
                        unit="body", compare="被钉住的物理链规模", source="pmx"))
    if pairs is not None:
        evid.append(_ev("blender.frozen_pairs", len(pairs), unit="bone",
                        compare="目标相对父链的旋转增量", source="blend"))
    if mute is not None:
        evid.append(_ev("blender.mute_world_delta_m", mute, unit="m",
                        compare="mute 约束前后世界顶点位移", source="blend"))

    static_hit = bool(roots)
    # 焊接结构里可能夹着「没有绑定骨骼」的纯碰撞体：它冻不冻都不影响任何骨，
    # 不能算 F3 命中（卡芙卡 PMX 就有 6 个这样的根，target_bone 为空）。
    bound_roots = [r for r in (roots or []) if r.get("bone_bound", True)]
    unbound = len(roots or []) - len(bound_roots)
    if unbound:
        evid.append(_ev("structure.frozen_roots.unbound", unbound, unit="joint",
                        compare="焊接但没绑骨的碰撞体，不参与 F3", source="pmx"))
    if roots and not bound_roots:
        return _finish(d, False, INSUFFICIENT,
                       "焊接冻结根都没有绑定骨骼（纯碰撞体），不构成硬约束冻结",
                       evid, missing)
    static_hit = bool(bound_roots)
    if pairs is None:
        missing.append("blender.frozen_pairs")
        if static_hit:
            return _finish(d, True, SUSPECTED,
                           "存在 %d 个绑定骨骼的焊接冻结根，但缺运动父链下的相对增量，动态未确认"
                           % len(bound_roots), evid, missing, score=2.0)
        missing.append("structure.frozen_roots")
        return _finish(d, False, INSUFFICIENT,
                       "缺冻结结构与动态增量两类证据，无法判定 F3", evid, missing)

    usable = [p for p in pairs
              if p.get("rot_delta_deg") is not None and p.get("parent_rot_delta_deg") is not None]
    # 只有「PMX 焊接冻结根的目标骨」才能进 F3 对照。
    # 否则一根没有刚体的普通骨会因为「跟着父骨转」也呈现 0 增量 —— 那是骨架父子关系，
    # 不是硬约束冻结（实测 feixiao_v2_hsr 的下擺_10_7 就是这样，0.48° 对 65.8°）。
    marked = [p for p in usable if "is_frozen_candidate" in p]
    if marked:
        usable = [p for p in marked if p.get("is_frozen_candidate")]
        if not usable:
            missing.append("structure.frozen_root_target_bones")
            if static_hit:
                return _finish(d, True, SUSPECTED,
                               "PMX 有 %d 个焊接冻结根，但它们的骨名在场景里对不上（改过名或未导入），动态未确认"
                               % len(bound_roots), evid, missing, score=2.0)
            return _finish(d, False, INSUFFICIENT,
                           "场景里没有焊接冻结根的候选骨，无法做 F3 对照", evid, missing)
    frozen = [p for p in usable
              if float(p["rot_delta_deg"]) <= frozen_deg
              and float(p["parent_rot_delta_deg"]) >= parent_deg]
    still = [p for p in usable if float(p["parent_rot_delta_deg"]) < parent_deg]

    if frozen:
        evid.append(_ev("blender.frozen_pairs.frozen", frozen[:8], unit="deg",
                        compare="目标≤%.2f° 而父链≥%.1f°" % (frozen_deg, parent_deg), source="blend"))
        if static_hit:
            return _finish(d, True, CONFIRMED,
                           "%d 根骨在父链明显运动（≥%.1f°）时相对增量≈0（≤%.2f°），且 PMX 有焊接冻结根：硬约束冻结"
                           % (len(frozen), parent_deg, frozen_deg),
                           evid, missing, score=3.5)
        missing.append("structure.frozen_roots")
        return _finish(d, True, SUSPECTED,
                       "%d 根骨相对增量≈0 而父链在动；但没有 PMX 焊接结构佐证" % len(frozen),
                       evid, missing, score=2.0)
    if still and len(still) == len(usable):
        if static_hit:
            return _finish(d, True, SUSPECTED,
                           "焊接冻结根存在，但采样区间父链本身只动 ≤%.1f°：这段动作本来就动得少，不能据此确认冻结"
                           % parent_deg, evid, missing, score=1.5)
        return _finish(d, False, INSUFFICIENT,
                       "采样区间父链几乎不动（≤%.1f°），低增量不构成 F3" % parent_deg,
                       evid, missing)
    if static_hit:
        return _finish(d, True, SUSPECTED,
                       "有焊接冻结根，但采样区间未捕捉到「父链动、目标不动」的帧对", evid, missing, score=1.5)
    return _finish(d, False, INSUFFICIENT, "动态增量未呈现冻结特征，排除 F3", evid, missing)


def _f4(ev, cfg):
    d = _blank(F4)
    wide_rad = _threshold(cfg, "f4_wide_limit_rad")
    angle_deg = _threshold(cfg, "f4_angle_deg")
    calibrated = bool(cfg.get("f4_calibrated")) and bool(
        _threshold_meta(cfg, "f4_angle_deg").get("calibrated"))
    units = _get(ev, "structure.wide_limit_units")
    angles = _get(ev, "blender.unit_angles")
    mass = _get(ev, "blender.rigid_mass_max_kg")
    evid, missing = [], []

    if units is not None:
        evid.append(_ev("structure.wide_limit_units", len(units), unit="unit",
                        compare="弹簧≤eps 且限位≥%.2f rad" % wide_rad, source="pmx"))
        if units:
            evid.append(_ev("structure.wide_limit_units.detail", units[:6], unit="unit",
                            compare="零弹簧 + 宽限位", source="pmx"))
    if angles is not None:
        evid.append(_ev("blender.unit_angles", len(angles), unit="unit",
                        compare="实测最大摆角", source="blend"))
    if mass is not None:
        evid.append(_ev("blender.rigid_mass_max_kg", mass, unit="kg",
                        compare="根部质量作为辅助证据（非判据）", source="blend"))

    static_hit = bool(units)
    if angles is None:
        missing.append("blender.unit_angles")
        if static_hit:
            return _finish(d, True, SUSPECTED,
                           "存在 %d 个零弹簧宽限位单元，但没有实测摆角，不能确认「大角度」" % len(units),
                           evid, missing, score=2.0)
        missing.append("structure.wide_limit_units")
        return _finish(d, False, INSUFFICIENT,
                       "缺单元弹簧/限位与实测摆角两类证据，无法判定 F4", evid, missing)

    big = [a for a in angles if a.get("max_angle_deg") is not None
           and float(a["max_angle_deg"]) >= angle_deg]
    if big:
        evid.append(_ev("blender.unit_angles.max", big[:6], unit="deg",
                        compare="≥%.1f° 算大角度" % angle_deg, source="blend"))
    if big and static_hit:
        if not calibrated:
            missing.append("config.thresholds.f4_angle_deg.calibrated")
            return _finish(d, True, SUSPECTED,
                           "零弹簧宽限位（≥%.2f rad）+ 实测摆角 ≥%.1f°；但「大角度」阈值未标定，只能 suspected"
                           % (wide_rad, angle_deg), evid, missing, score=2.5)
        return _finish(d, True, CONFIRMED,
                       "零弹簧 + 限位 ≥%.2f rad + 实测摆角 ≥%.1f°：宽限位导致甩到异常角度"
                       % (wide_rad, angle_deg), evid, missing, score=3.0)
    if static_hit:
        return _finish(d, True, SUSPECTED,
                       "存在零弹簧宽限位单元，但实测摆角未达 %.1f°" % angle_deg, evid, missing, score=1.5)
    if big:
        return _finish(d, False, INSUFFICIENT,
                       "有大角度实测但缺单元弹簧/限位结构证据，不能归因到零弹簧宽限位", evid, missing)
    return _finish(d, False, INSUFFICIENT, "无零弹簧宽限位单元，排除 F4", evid, missing)


def _f5(ev, cfg):
    d = _blank(F5)
    cov = _get(ev, "coverage")
    pen = _get(ev, "blender.penetration")
    evid, missing = [], []
    gaps = _get(ev, "coverage.gaps") if cov else None
    sparse = _get(ev, "coverage.sparse_gaps") if cov else None

    if gaps is not None:
        bones = sorted({b for g in gaps for b in (g.get("bones_missing") or [])})
        evid.append(_ev("coverage.gaps", gaps[:12], unit="row",
                        compare="整行/整组无刚体的骨", source="pmx"))
        evid.append(_ev("coverage.gap_bones", bones, unit="bone",
                        compare="具体缺失骨名单", source="pmx"))
    if sparse is not None and sparse:
        evid.append(_ev("coverage.sparse_gaps", sparse[:12], unit="row",
                        compare="零散缺口，低置信", source="pmx"))
    if pen is not None:
        evid.append(_ev("blender.penetration", pen[:12], unit="m",
                        compare="逐帧穿入深度与穿入骨", source="blend"))

    if gaps is None:
        missing = ["coverage.gaps"]
        return _finish(d, False, INSUFFICIENT, "缺骨—刚体覆盖统计，无法判定 F5", evid, missing)
    if not gaps:
        if sparse:
            return _finish(d, True, SUSPECTED,
                           "只有零散缺口（%d 行），未达到整行缺失阈值" % len(sparse),
                           evid, missing, score=1.0)
        return _finish(d, False, INSUFFICIENT, "该模型骨—刚体覆盖完整，排除 F5", evid, missing)

    if pen is None:
        missing.append("blender.penetration")
        return _finish(d, True, SUSPECTED,
                       "%d 处整行骨无刚体，但没有局部穿模证据与之对应" % len(gaps),
                       evid, missing, score=2.0)

    fams = {g.get("family") for g in gaps}
    gap_bones = {b for g in gaps for b in (g.get("bones_missing") or [])}
    hits = []
    for item in pen:
        try:
            depth = float(item.get("max_depth_m"))
        except (TypeError, ValueError):
            continue
        if depth >= 0:
            continue
        item_fams = set(item.get("families") or [])
        item_bones = set(item.get("bones") or [])
        if (item_fams & fams) or (item_bones & gap_bones):
            hits.append(item)
    if hits:
        evid.append(_ev("blender.penetration.correlated", hits[:6], unit="m",
                        compare="与缺口族/骨重叠的穿入", source="blend"))
        return _finish(d, True, CONFIRMED,
                       "%d 处整行骨无刚体，且同族穿入实测最深 %.3f m：局部穿模归因到覆盖缺口"
                       % (len(gaps), min(float(h["max_depth_m"]) for h in hits)),
                       evid, missing, score=3.0)
    return _finish(d, True, SUSPECTED,
                   "%d 处整行骨无刚体，但穿模证据未与缺口区域对齐" % len(gaps),
                   evid, missing, score=1.5)


def _f6(ev, cfg):
    d = _blank(F6)
    ab = _get(ev, "ab")
    evid, missing = [], []
    if not ab:
        missing = ["ab.variable_changed", "ab.fields_compared", "ab.differing_fields",
                   "ab.result_identical"]
        return _finish(d, False, INSUFFICIENT,
                       "没有 A/B 测量文件：F6 固定返回证据不足（需要两次唯一变量对比）",
                       evid, missing)
    for key in ("variable_changed", "fields_compared", "differing_fields", "result_identical"):
        if ab.get(key) is None:
            missing.append("ab.%s" % key)
    if missing:
        return _finish(d, False, INSUFFICIENT, "A/B 文件缺字段：%s" % ", ".join(missing),
                       evid, missing)
    evid.append(_ev("ab.variable_changed", ab.get("variable_changed"), unit="string",
                    compare="A/B 唯一变量", source="ab"))
    evid.append(_ev("ab.fields_compared", len(ab["fields_compared"]), unit="field",
                    compare="参与逐位比较的字段数", source="ab"))
    evid.append(_ev("ab.identical_fields", ab.get("identical_fields") or [], unit="field",
                    compare="两次结果相同", source="ab"))
    evid.append(_ev("ab.differing_fields", ab.get("differing_fields") or [], unit="field",
                    compare="两次结果不同", source="ab"))
    evid.append(_ev("ab.result_identical", ab.get("result_identical"), unit="bool",
                    compare="结果逐位相同 = 改动无效", source="ab"))
    if ab.get("result_identical") and not ab.get("differing_fields"):
        return _finish(d, True, CONFIRMED,
                       "唯一变量=%s，%d 个字段逐位相同、结果一致：改动没有生效"
                       % (ab.get("variable_changed"), len(ab["fields_compared"])),
                       evid, missing, score=3.0)
    return _finish(d, False, INSUFFICIENT,
                   "A/B 存在差异（%d 个字段不同），改动生效，排除 F6"
                   % len(ab.get("differing_fields") or []), evid, missing)


def _r0(ev, cfg):
    d = _blank(OUT_OF_TAXONOMY)
    r0 = _get(ev, "r0")
    pen = _get(ev, "blender.penetration")
    evid, missing = [], []
    if r0:
        evid.append(_ev("r0", r0, unit="m",
                        compare="首帧初始穿透，不属于 F1–F6", source="probe"))
        if r0.get("detected"):
            return _finish(d, True, r0.get("confidence") or SUSPECTED,
                           "Bullet 初始穿透 R0：%s" % (r0.get("reason") or "首帧即存在重叠"),
                           evid, missing, score=2.5)
    if pen:
        first = [p for p in pen
                 if p.get("frame") is not None and int(p["frame"]) <= 1
                 and p.get("max_depth_m") is not None and float(p["max_depth_m"]) < 0]
        if first:
            evid.append(_ev("blender.penetration.frame1", first[:6], unit="m",
                            compare="f1 即穿入 = 初始状态重叠", source="blend"))
            return _finish(d, True, SUSPECTED,
                           "第 1 帧已存在 %.3f m 穿入：属于 Bullet 初始穿透 R0，不在 F1–F6 内"
                           % min(float(p["max_depth_m"]) for p in first),
                           evid, missing, score=2.0)
    return _finish(d, False, INSUFFICIENT, "没有初始穿透证据", evid, missing)


_CRITERIA = (_f1, _f2, _f3, _f4, _f5, _f6, _r0)


# ============================================================ 汇总
def judge(evidence: dict, config: dict | None = None) -> dict:
    """跑全部判据并按证据完整度选 primary。"""
    config = config or default_config()
    diags = [fn(evidence, config) for fn in _CRITERIA]
    matched = [d for d in diags if d["matched"]]
    ranked = sorted(
        matched,
        key=lambda d: (-CONFIDENCE_RANK[d["confidence"]], -d["score"],
                       TAXONOMY_ORDER.index(d["id"]) if d["id"] in TAXONOMY_ORDER else 99),
    )
    primary_diag = ranked[0] if ranked else None
    secondary = [
        {"id": d["id"], "confidence": d["confidence"], "reason": d["reason"]}
        for d in ranked[1:]
    ]
    missing = sorted({m for d in diags for m in d["missing_evidence"]})

    if primary_diag is None:
        r0 = next(d for d in diags if d["id"] == OUT_OF_TAXONOMY)
        if r0["matched"]:
            primary, confidence = OUT_OF_TAXONOMY, r0["confidence"]
        elif missing:
            primary, confidence = INSUFFICIENT_EVIDENCE, INSUFFICIENT
        else:
            primary, confidence = UNKNOWN, INSUFFICIENT
    else:
        primary, confidence = primary_diag["id"], primary_diag["confidence"]
        if primary_diag["id"] == OUT_OF_TAXONOMY:
            # R0 被显式标成分类学外，不塞进 F1–F6
            primary = OUT_OF_TAXONOMY

    return {
        "primary": primary,
        "secondary": secondary,
        "confidence": confidence,
        "diagnostics": diags,
        "missing_evidence": missing,
    }


def _judgment_payload(report: dict) -> dict:
    """指纹用：只留判定本身，去掉时间戳/路径。"""
    return {
        "schema_version": report["schema_version"],
        "taxonomy_version": report["taxonomy_version"],
        "primary": report["primary"],
        "secondary": report["secondary"],
        "confidence": report["confidence"],
        "diagnostics": [
            {k: d[k] for k in ("id", "matched", "confidence", "reason", "score",
                               "evidence_keys", "missing_evidence")}
            for d in report["diagnostics"]
        ],
        "config": report["config"],
    }


def judgment_fingerprint(report: dict) -> str:
    blob = json.dumps(_judgment_payload(report), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_report(evidence: dict, *, source_type: str, input_path: str,
                 input_sha256: str, config: dict | None = None,
                 frame_range: dict | None = None, experiment_id: str | None = None,
                 status: str = "ok", warnings: list | None = None) -> dict:
    """把 evidence 判成一个版本化 DiagnosisReport。"""
    config = config or default_config()
    verdict = judge(evidence, config)
    model = evidence.get("model") or {}
    cache = evidence.get("cache") or (evidence.get("blender") or {}).get("point_cache") or {}
    warnings = list(warnings or [])
    for key in ("f3_parent_motion_deg", "f4_angle_deg"):
        meta = _threshold_meta(config, key)
        if meta.get("calibrated") is False:
            warnings.append("阈值 %s=%.3f 未标定，相关判据最高只能给 suspected" % (key, _threshold(config, key)))
    if not evidence.get("blender"):
        warnings.append("纯静态（PMX）输入：F1/F2/F3/F6 缺运行期证据，不会 confirmed")
    if _get(evidence, "structure.mass_available") is False:
        warnings.append("pmx.py 未解析刚体质量，F4 的『根部质量』只作辅助、未参与判分")
    roots = _get(evidence, "structure.frozen_roots")
    if roots and len(roots) >= 5:
        warnings.append(
            "检出 %d 个焊接冻结根；发根/耳饰这类『本来就应该刚接』的根也长这样，"
            "要靠动态增量区分「设计如此」与「F3 冻结」" % len(roots))

    report = {
        "schema_version": SCHEMA_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "tool": TOOL,
        "tool_version": TOOL_VERSION,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "experiment_id": experiment_id or ("diag-" + hashlib.sha1(
            (input_sha256 + SCHEMA_VERSION).encode("utf-8")).hexdigest()[:12]),
        "input_path": os.path.abspath(input_path) if input_path else "",
        "input_sha256": input_sha256,
        "source_type": source_type,
        "status": status,
        "model": {
            "name": model.get("name"),
            "version": model.get("version"),
            "encoding": model.get("encoding"),
            "bones": model.get("bones"),
            "rigids": model.get("rigids"),
            "joints": model.get("joints"),
        },
        "frame_range": frame_range or {},
        "cache": {
            "is_baked": cache.get("is_baked"),
            "frame_start": cache.get("frame_start"),
            "frame_end": cache.get("frame_end"),
        },
        "primary": verdict["primary"],
        "secondary": verdict["secondary"],
        "confidence": verdict["confidence"],
        "status_detail": {
            "taxonomy_order": list(TAXONOMY_ORDER),
            "r0_label": R0,
            "out_of_taxonomy": OUT_OF_TAXONOMY,
            "confidence_values": list(CONFIDENCE_RANK),
        },
        "diagnostics": verdict["diagnostics"],
        "evidence": evidence,
        "missing_evidence": verdict["missing_evidence"],
        "warnings": warnings,
        "config": config,
    }
    report["judgment_fingerprint"] = judgment_fingerprint(report)
    return report


# ============================================================ 入口
def diagnose_pmx(pmx_path: str, out_path: str | None = None,
                 ab: dict | None = None, config: dict | None = None,
                 extra_evidence: dict | None = None) -> dict:
    """静态 PMX 归因。out_path 给了就写盘（UTF-8、不转义中文）。"""
    config = config or default_config()
    sha = sha256_file(pmx_path)
    evidence = collect_pmx(pmx_path, config)
    if extra_evidence:
        _merge(evidence, extra_evidence)
    if ab:
        evidence["ab"] = ab
    warnings = []
    if ab:
        warnings.append("A/B 输入按 f6_numeric_eps 比较，元数据字段（路径/时间）已排除")
    report = build_report(
        evidence,
        source_type="pmx",
        input_path=pmx_path,
        input_sha256=sha,
        config=config,
        warnings=warnings,
    )
    if out_path:
        write_json(out_path, report)
    return report


def _merge(base: dict, extra: dict) -> None:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value


# 公开别名：Blender 适配器 / M04 / M07 用这两个，不必摸私有名
merge_evidence = _merge


def write_json(path: str, payload: dict) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_config(path: str | None) -> dict:
    if not path:
        return default_config()
    cfg = default_config()
    _merge(cfg, load_json(path))
    return cfg


def _summary_line(report: dict) -> str:
    sec = ", ".join("%s(%s)" % (s["id"], s["confidence"]) for s in report["secondary"]) or "-"
    return "primary=%s [%s]  secondary=%s  fingerprint=%s" % (
        report["primary"], report["confidence"], sec, report["judgment_fingerprint"][:12])


summary_line = _summary_line


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m mmdpipe.diagnose",
        description="F1–F6 归因判据引擎（静态 PMX + 可选 A/B 证据）",
    )
    p.add_argument("--pmx", required=True, help="输入 PMX（只读，不改写）")
    p.add_argument("--out", help="输出 diagnosis JSON（UTF-8）")
    p.add_argument("--ab", nargs=2, metavar=("A_JSON", "B_JSON"),
                   help="F6 用：两份唯一变量不同的测量 JSON")
    p.add_argument("--config", help="阈值配置 JSON（覆盖 DEFAULT_CONFIG）")
    p.add_argument("--strict", action="store_true", help="同时把 JSON 打到 stdout")
    p.add_argument("--fail-on-confirmed", action="store_true",
                   help="primary 置信度为 confirmed 时退出码 1")
    return p


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # --help / -h 走的是 SystemExit(0)：那是成功路径，不是用法错误。
        # 实测修前 `python -m mmdpipe.diagnose --help` 退出码 2，被当成参数错误。
        return EXIT_OK if exc.code in (0, None) else EXIT_USAGE

    if not os.path.isfile(args.pmx):
        sys.stderr.write("输入文件不存在：%s\n" % args.pmx)
        return EXIT_INPUT
    try:
        config = _load_config(args.config)
    except (OSError, ValueError) as exc:
        sys.stderr.write("配置读取失败：%s\n" % exc)
        return EXIT_INPUT

    ab = None
    if args.ab:
        try:
            ab = compare_ab(load_json(args.ab[0]), load_json(args.ab[1]), config)
            ab["a_path"], ab["b_path"] = os.path.abspath(args.ab[0]), os.path.abspath(args.ab[1])
        except (OSError, ValueError) as exc:
            sys.stderr.write("A/B 文件读取失败：%s\n" % exc)
            return EXIT_INPUT

    try:
        report = diagnose_pmx(args.pmx, args.out, ab=ab, config=config)
    except pmx_mod.PMXError as exc:
        sys.stderr.write("PMX 解析失败：%s\n" % exc)
        return EXIT_INPUT
    except OSError as exc:
        sys.stderr.write("读取失败：%s\n" % exc)
        return EXIT_INPUT

    line = _summary_line(report)
    sys.stdout.write(line + "\n")
    if args.strict:
        sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if args.fail_on_confirmed and report["confidence"] == CONFIRMED:
        return EXIT_CONFIRMED
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
