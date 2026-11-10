"""物理资格判断器 —— 纯 Python，不依赖 bpy。

为什么要它
----------
默认让全部刚体参与物理解算，会把「在 PMX 里被焊死」的部位变成一块僵在
A-Pose 上的硬板。卡芙卡的袖子就是这样：关节 min=max=0、弹簧 0，焊死角度是
PMX 的 A-Pose，而 VMD 第一帧手臂已经垂下，于是袖子永远横着伸出去。

判据不能靠名字
--------------
卡芙卡叫 `HairA1_JNT`，飞霄叫中文，赛飞儿又是另一套。名字识别每次换模型都会漏。
所以判据只看关节数值：

    一个刚体参与的所有关节，若「限位全 0 且 弹簧全 0」→ 焊接 → 不做物理
    只要有一个关节带限位或弹簧        → 有独立运动能力 → 做物理

三步：判断（关节数值）→ 匹配（关节连通分量＝物理单元，再回填它驱动的骨骼）
     → 修理（静音那根骨上的 COPY_ROTATION / COPY_TRANSFORMS）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import pmx as pmx_mod

PHYSICS = "physics"
WELDED = "welded"                  # 焊死，且会回填骨骼 → 需要修
WELDED_COLLIDER = "welded_collider"  # 焊死，但不回填骨骼（纯碰撞体）→ 不修
COLLIDER = "collider"              # 无关节 + mode0：骨骼跟随的碰撞胶囊（实测正常）
FREE = "free"                      # 无关节 + mode1/2：动态体却没有约束 → 可疑

# 只有这两种 mode 会把变换回填给骨骼（mode2→COPY_ROTATION，mode1→COPY_TRANSFORMS）
FEEDBACK_MODES = (1, 2)


@dataclass
class BodyVerdict:
    index: int
    name: str
    bone: str
    mode: int
    joint_ids: list = field(default_factory=list)
    welded: bool = False
    spring_max: float = 0.0
    limit_span: float = 0.0
    verdict: str = PHYSICS
    unit: int = -1


@dataclass
class Unit:
    uid: int
    bodies: list
    joint_ids: list
    welded: bool
    anchor_bone: str
    modes: dict
    spring_max: float
    welded_joints: int = 0
    flex_joints: int = 0

    @property
    def cycle_rank(self) -> int:
        """E - V + 1：0=树（能自由弯折），≥1=有闭环（过约束，折不动）。"""
        return max(0, len(self.joint_ids) - len(self.bodies) + 1)

    @property
    def welded_ratio(self) -> float:
        return self.welded_joints / len(self.joint_ids) if self.joint_ids else 0.0


@dataclass
class PhysicsReport:
    model_name: str
    bones: int
    bodies: list
    units: list
    counts: dict
    mute_bones: list
    accessory: bool
    notes: list = field(default_factory=list)
    suspect_units: list = field(default_factory=list)
    suspect_bones: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "model_name": self.model_name,
            "bones": self.bones,
            "accessory": self.accessory,
            "counts": self.counts,
            "mute_bones": self.mute_bones,
            "suspect_units": self.suspect_units,
            "suspect_bones": self.suspect_bones,
            "notes": self.notes,
            "units": [
                {"uid": u.uid, "bodies": len(u.bodies), "welded": u.welded,
                 "anchor_bone": u.anchor_bone, "modes": u.modes,
                 "spring_max": round(u.spring_max, 6),
                 "edges": len(u.joint_ids), "cycle_rank": u.cycle_rank,
                 "welded_ratio": round(u.welded_ratio, 3)}
                for u in self.units
            ],
            "bodies": [
                {"index": b.index, "name": b.name, "bone": b.bone, "mode": b.mode,
                 "verdict": b.verdict, "welded": b.welded, "unit": b.unit,
                 "spring_max": round(b.spring_max, 6),
                 "limit_span": round(b.limit_span, 6)}
                for b in self.bodies
            ],
        }


def _bone_depths(model) -> list:
    """骨深（离根几步）。用父链推，不靠名字。"""
    depth = {}
    bones = model.bones

    def walk(i, seen=0):
        if i in depth:
            return depth[i]
        b = bones[i]
        parent = b.parent
        if parent < 0 or parent >= len(bones) or parent == i or seen > len(bones):
            depth[i] = 0
        else:
            depth[i] = walk(parent, seen + 1) + 1
        return depth[i]

    return [walk(i) for i in range(len(bones))]


def classify(model) -> PhysicsReport:
    rigids = model.rigids
    joints = model.joints
    depths = _bone_depths(model)

    def bone_name(idx: int) -> str:
        if 0 <= idx < len(model.bones):
            return model.bones[idx].name
        return ""

    # 关节 → 刚体
    body_joints = {r.index: [] for r in rigids}
    for j in joints:
        for rid in (j.rigid_a, j.rigid_b):
            if rid in body_joints:
                body_joints[rid].append(j.index)

    # 并查集：关节连通分量 = 物理单元
    parent = {r.index: r.index for r in rigids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for j in joints:
        if j.rigid_a in parent and j.rigid_b in parent:
            union(j.rigid_a, j.rigid_b)

    verdicts = []
    for r in rigids:
        jids = body_joints[r.index]
        js = [joints[i] for i in jids]
        welded = bool(js) and all(j.welded for j in js)
        spring = max((j.spring_max for j in js), default=0.0)
        span = max((j.limit_span for j in js), default=0.0)
        if not js:
            # 实测：mode0 的无关节刚体在 mmd_tools 里跟随骨骼（f60 与骨差 2 mm），是正常的碰撞胶囊。
            # 只有无关节却又是 mode1/2 的，才是真可疑。
            v = COLLIDER if r.mode == 0 else FREE
        elif welded and r.mode in FEEDBACK_MODES:
            v = WELDED
        elif welded:
            v = WELDED_COLLIDER
        else:
            v = PHYSICS
        verdicts.append(BodyVerdict(
            index=r.index, name=r.name, bone=bone_name(r.bone), mode=r.mode,
            joint_ids=jids, welded=welded, spring_max=spring, limit_span=span,
            verdict=v, unit=find(r.index),
        ))

    # 单元汇总
    name_to_idx = {}
    for i, bn in enumerate(model.bones):
        name_to_idx.setdefault(bn.name, i)
    by_unit = {}
    for bv in verdicts:
        by_unit.setdefault(bv.unit, []).append(bv)
    units = []
    for uid, members in sorted(by_unit.items()):
        jids = sorted({j for m in members for j in m.joint_ids})
        js = [joints[i] for i in jids]
        anchored = [(depths[name_to_idx[m.bone]], m.bone)
                    for m in members if m.bone in name_to_idx]
        anchor = min(anchored)[1] if anchored else ""
        modes = {}
        for m in members:
            modes[m.mode] = modes.get(m.mode, 0) + 1
        units.append(Unit(
            uid=uid, bodies=[m.index for m in members], joint_ids=jids,
            welded=all(j.welded for j in js) if js else False,
            anchor_bone=anchor, modes=modes,
            spring_max=max((j.spring_max for j in js), default=0.0),
            welded_joints=sum(1 for j in js if j.welded),
            flex_joints=sum(1 for j in js if not j.welded),
        ))

    counts = {PHYSICS: 0, WELDED: 0, WELDED_COLLIDER: 0, COLLIDER: 0, FREE: 0}
    for bv in verdicts:
        counts[bv.verdict] = counts.get(bv.verdict, 0) + 1

    mute_bones = sorted({bv.bone for bv in verdicts if bv.verdict == WELDED and bv.bone})

    # 第二档：结构僵死嫌疑。
    # 卡芙卡的袖子不属于"全焊死"，但它是一个 25 体 / 48 关节 / 环 24 的闭环，其中一半关节焊接，
    # 且整个单元里没有任何 mode2（不跟骨骼）。对比绯英的裙子：同为闭环，焊占比只有 8%，能正常摆动。
    # 所以用「无 mode2 + 焊占比高 + 环多 + 成规模」四条一起判，而不是单看焊死。
    suspect_units = []
    suspect_bones = set()
    for u in units:
        if len(u.bodies) < 3:
            continue
        if u.modes.get(2, 0) > 0:
            continue
        if u.welded_ratio < 0.4:
            continue
        if u.cycle_rank < 1:
            continue
        suspect_units.append({
            "uid": u.uid, "bodies": len(u.bodies), "joints": len(u.joint_ids),
            "cycle_rank": u.cycle_rank, "welded_ratio": round(u.welded_ratio, 3),
            "anchor_bone": u.anchor_bone, "modes": u.modes,
        })
        for bv in verdicts:
            if bv.unit == u.uid and bv.mode in FEEDBACK_MODES and bv.bone:
                suspect_bones.add(bv.bone)
    suspect_bones = sorted(suspect_bones)

    notes = []
    if counts[FREE]:
        notes.append("%d 个刚体无关节却是 mode1/2：动态体没有约束，行为可疑" % counts[FREE])
    if counts[WELDED]:
        notes.append("%d 个刚体被焊死且会回填骨骼，静音 %d 根骨可让它们回到骨架层级"
                     % (counts[WELDED], len(mute_bones)))
    if counts[WELDED_COLLIDER]:
        notes.append("%d 个刚体被焊死但只作碰撞体（mode 0），不动它们" % counts[WELDED_COLLIDER])
    if suspect_units:
        notes.append("%d 个单元结构僵死嫌疑（无 mode2 + 焊占比≥40%% + 有闭环），"
                     "涉及 %d 根骨——是否静音需要看画面确认"
                     % (len(suspect_units), len(suspect_bones)))

    accessory = len(rigids) == 0 and len(model.bones) < 40
    if accessory:
        notes.append("刚体 0 / 骨 %d：判定为道具，不参与物理流水线" % len(model.bones))

    return PhysicsReport(
        model_name=model.name, bones=len(model.bones), bodies=verdicts,
        units=units, counts=counts, mute_bones=mute_bones,
        accessory=accessory, notes=notes,
        suspect_units=suspect_units, suspect_bones=suspect_bones,
    )


def render_text(rep: PhysicsReport, max_units: int = 8) -> str:
    lines = ["物理资格判断 · %s" % rep.model_name]
    lines.append("  骨 %d | 物理 %d | 焊死(需修) %d | 焊死(碰撞体) %d | 跟随碰撞体 %d | 可疑无约束 %d"
                 % (rep.bones, rep.counts.get(PHYSICS, 0), rep.counts.get(WELDED, 0),
                    rep.counts.get(WELDED_COLLIDER, 0), rep.counts.get(COLLIDER, 0),
                    rep.counts.get(FREE, 0)))
    if rep.accessory:
        lines.append("  判定：道具（不参与物理流水线）")
    lines.append("  物理单元 %d 个" % len(rep.units))
    for u in sorted(rep.units, key=lambda x: -len(x.bodies))[:max_units]:
        tag = "全焊死" if u.welded else "可动"
        lines.append("    · %-24s %2d刚体 %2d关节 环%2d %s mode%s 焊占比%.0f%%"
                     % (u.anchor_bone[:24], len(u.bodies), len(u.joint_ids),
                        u.cycle_rank, tag, u.modes, u.welded_ratio * 100))
    if len(rep.units) > max_units:
        lines.append("    · …另 %d 个单元" % (len(rep.units) - max_units))
    if rep.mute_bones:
        lines.append("  待静音骨骼 %d 根：%s%s"
                     % (len(rep.mute_bones), ", ".join(rep.mute_bones[:8]),
                        " …" if len(rep.mute_bones) > 8 else ""))
    if rep.suspect_units:
        lines.append("  结构僵死嫌疑 %d 个单元（需看图确认）：" % len(rep.suspect_units))
        for s in sorted(rep.suspect_units, key=lambda x: -x["bodies"])[:4]:
            lines.append("    · %-22s %2d刚体 环%2d 焊占比%.0f%%"
                         % (s["anchor_bone"][:22], s["bodies"],
                            s["cycle_rank"], s["welded_ratio"] * 100))
    for n in rep.notes:
        lines.append("  · %s" % n)
    return "\n".join(lines)


def bones_by_pattern(model, patterns) -> list:
    """按子串匹配刚体名或骨名，返回对应骨骼名（供 force_static / force_physics 用）。"""
    pats = [p.lower() for p in patterns if p]
    out = []
    for rb in model.rigids:
        names = [rb.name]
        if 0 <= rb.bone < len(model.bones):
            names.append(model.bones[rb.bone].name)
        low = " ".join(names).lower()
        if any(p in low for p in pats) and 0 <= rb.bone < len(model.bones):
            out.append(model.bones[rb.bone].name)
    return sorted(set(out))


def bones_for_policy(rep: PhysicsReport, policy: str) -> list:
    """policy: off / welded / strict。

    welded —— 只静音"全焊死且会回填骨骼"的（你的判据）
    strict —— 再加上"结构僵死嫌疑"单元（卡芙卡袖子那一类）
    """
    if policy in ("off", "report"):
        return []
    if policy == "welded":
        return list(rep.mute_bones)
    if policy == "strict":
        return sorted(set(rep.mute_bones) | set(rep.suspect_bones))
    raise ValueError("未知 physics policy: %s" % policy)
