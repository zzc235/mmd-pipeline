"""VMD × PMX 命名匹配报告 —— 纯 Python。

"自动检测该用哪种方法套 VMD"的可执行版本：覆盖率是数字，不是感觉。
两条静默失败在这里合流——骨骼名对不上、材质名对不上，都是命名问题。
"""
from __future__ import annotations

from dataclasses import dataclass, field

PASS_THRESHOLD = 0.95
WARN_THRESHOLD = 0.80


@dataclass
class MatchReport:
    pmx_name: str
    vmd_name: str
    vmd_model_name: str
    bone_names_total: int = 0
    bone_hit: list = field(default_factory=list)
    bone_miss: list = field(default_factory=list)
    coverage_frames: float = 0.0     # 按关键帧条数加权
    coverage_names: float = 0.0
    orphan_miss_detail: list = field(default_factory=list)
    morph_total: int = 0
    morph_hit: int = 0
    morph_miss: list = field(default_factory=list)
    morph_coverage: float = 1.0
    ik_tracks: list = field(default_factory=list)
    ik_bones: list = field(default_factory=list)
    ik_gap: list = field(default_factory=list)
    additional_uvs: int = 0
    frame_range: tuple = (0, 0)
    keyframes: int = 0
    verdict: str = "pass"
    suggested: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["frame_range"] = list(self.frame_range)
        return d


def build(pmx, vmd) -> MatchReport:
    rep = MatchReport(
        pmx_name=pmx.name,
        vmd_name=str(getattr(vmd, "path", "")),
        vmd_model_name=vmd.model_name,
        additional_uvs=pmx.additional_uvs,
        frame_range=vmd.frame_range,
        keyframes=vmd.keyframes,
    )

    pmx_bones = pmx.bone_names
    tracks = dict(vmd.bone_tracks)
    rep.bone_names_total = len(tracks)

    total_weight = 0
    hit_weight = 0
    for name, count in sorted(tracks.items()):
        total_weight += count
        if name in pmx_bones:
            rep.bone_hit.append(name)
            hit_weight += count
        else:
            rep.bone_miss.append(name)
            rep.orphan_miss_detail.append({"bone": name, "keys": count})

    rep.coverage_frames = (hit_weight / total_weight) if total_weight else 0.0
    rep.coverage_names = (len(rep.bone_hit) / rep.bone_names_total) if rep.bone_names_total else 0.0

    # 表情
    pmx_morphs = pmx.morph_names
    rep.morph_total = len(vmd.morph_tracks)
    rep.morph_hit = sum(1 for n in vmd.morph_tracks if n in pmx_morphs)
    rep.morph_miss = sorted(n for n in vmd.morph_tracks if n not in pmx_morphs)
    rep.morph_coverage = (rep.morph_hit / rep.morph_total) if rep.morph_total else 1.0

    # IK：VMD 有 IK 轨但模型没有对应 IK 骨 → 脚滑的根源
    rep.ik_tracks = sorted(n for n in tracks if "IK" in n.upper())
    rep.ik_bones = sorted(b.name for b in pmx.bones if b.is_ik)
    ik_bone_set = set(rep.ik_bones)
    rep.ik_gap = [n for n in rep.ik_tracks if n not in ik_bone_set]

    # 判定
    cov = rep.coverage_frames
    if cov >= PASS_THRESHOLD:
        rep.verdict = "pass"
    elif cov >= WARN_THRESHOLD:
        rep.verdict = "warn"
    else:
        rep.verdict = "block"

    rep.suggested = {
        "bone_mapper": "PMX",
        "rename_bones": True,
        "use_underscore": False,
        "scale": 0.08,
    }

    if vmd.model_name and pmx.name and vmd.model_name != pmx.name:
        rep.notes.append("VMD 记录模型=%s / PMX 模型=%s（跨模型套动作，属正常，但要确认骨骼体系一致）"
                         % (vmd.model_name, pmx.name))
    if rep.ik_gap:
        rep.notes.append("VMD 有 IK 轨但模型无对应 IK 骨，脚会滑：%s" % ", ".join(rep.ik_gap))
    if rep.bone_miss:
        rep.notes.append("有 %d 根骨的曲线会丢失：%s"
                         % (len(rep.bone_miss), ", ".join(rep.bone_miss[:8])))
    if pmx.additional_uvs != 2:
        rep.notes.append("附加 UV 数 = %d（两个样本都是 2，写回 PMX 必须带这个数）"
                         % pmx.additional_uvs)
    return rep


def render_text(rep: MatchReport) -> str:
    lines = []
    lines.append("VMD × PMX 匹配报告")
    lines.append("  PMX   %s" % rep.pmx_name)
    lines.append("  VMD   %s  (记录模型 %s)" % (rep.vmd_name, rep.vmd_model_name))
    lines.append("  帧范围 %d..%d   关键帧 %d" % (rep.frame_range[0], rep.frame_range[1], rep.keyframes))
    lines.append("  骨骼名 %d 条 | 命中 %d | 覆盖 %.1f%%（按曲线） %.1f%%（按骨数）"
                 % (rep.bone_names_total, len(rep.bone_hit),
                    rep.coverage_frames * 100, rep.coverage_names * 100))
    if rep.bone_miss:
        lines.append("  缺失骨 %s" % ", ".join(rep.bone_miss))
    lines.append("  表情 %d 条 | 命中 %d | 覆盖 %.1f%%"
                 % (rep.morph_total, rep.morph_hit, rep.morph_coverage * 100))
    if rep.morph_miss:
        lines.append("  缺失表情 %s" % ", ".join(rep.morph_miss[:10]))
    lines.append("  IK 轨 %d | 模型 IK 骨 %d | 缺口 %s"
                 % (len(rep.ik_tracks), len(rep.ik_bones),
                    ", ".join(rep.ik_gap) if rep.ik_gap else "无"))
    lines.append("  附加 UV %d" % rep.additional_uvs)
    lines.append("  判定  %s" % rep.verdict.upper())
    for n in rep.notes:
        lines.append("  · %s" % n)
    return "\n".join(lines)
