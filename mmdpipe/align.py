"""根链对齐：plan 结构、判定、注入。纯 Python（测量在 Blender 侧）。

设计原则（评审结论）：
  * 测量骨 ≠ 注入骨。测量在"承载站位"的骨（MMD 惯例 センター），注入在根链最高公共祖先。
  * 不做黑盒决策：只输出可审查的 AlignmentPlan，每个字段有理由，用户可改。
  * 注入只在 plan.mode == "match" 时执行。
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field, asdict

from . import vmd as vmd_mod

# 判定阈值
NOISE_MM = 10.0          # 世界差小于此当噪声
RATIO_MIN = 0.30         # 根位移 / 脚位移 低于此判为姿态差而非站位差
GLOBAL_MM = 50.0         # 全身中位位移大于此才算"整体位移"（辅助证据）
FEET_MM = 30.0           # 脚部位移低于此，判为体态而非站位
HEADING_NOISE_DEG = 2.0
LARGE_MM = 500.0         # 超过这个提示"可能故意换场"

MATCH = "match"
KEEP = "keep"
NONE = "none"


@dataclass
class AlignmentPlan:
    a_path: str = ""
    b_path: str = ""
    a_frame: int = 0
    b_frame: int = 0
    measure_bone: str = ""
    inject_bone: str = ""
    world_delta_mm: float = 0.0        # 测量骨的世界位移
    global_median_mm: float = 0.0      # 全身代表骨的中位位移（辅助证据）
    feet_delta_mm: float = 0.0         # 脚部（足首/つま先）最大世界位移
    heading_deg: float = 0.0
    t: list = field(default_factory=list)        # 世界平移（米）
    t_model: list = field(default_factory=list)  # 模型空间平移（PMX 单位，含轴向与缩放）
    r_z_deg: float = 0.0
    mode: str = NONE
    blend_frames: int = 0
    easing: str = "linear"
    reason: str = ""
    evidence: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AlignmentPlan":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def decide(plan: AlignmentPlan) -> AlignmentPlan:
    """按两个信号判定：测量骨世界差 + 全身中位位移。

    只靠测量骨：原神摇+活着dj 的 センター 差 0 → no-op（正确）
    只靠中位：原神摇+活着dj 中位 66mm 也会触发（错误，脚没动）
    两者一起：只有"测量骨移动 且 全身一起移动"才是站位差。
    """
    d = plan.world_delta_mm
    g = plan.global_median_mm
    f = plan.feet_delta_mm
    h = abs(plan.heading_deg)

    if d < NOISE_MM and h < HEADING_NOISE_DEG:
        plan.mode = NONE
        plan.reason = "测量骨世界差 %.1f mm、朝向 %.1f°，在噪声级" % (d, h)
        return plan

    # 判"站位差"还是"体态差"用**比例**，不用脚的绝对值：
    # 交接处两段姿态本来就不同，脚位移天然很大（实测 351 mm），拿它当门槛会全判成需要搬。
    # 真正的整体位移会同时推动根和脚；纯体态差只让身体中段偏移，根几乎不动。
    ratio = (d / f) if f > 1e-6 else 1.0
    if f >= FEET_MM and ratio < RATIO_MIN and h < HEADING_NOISE_DEG:
        plan.mode = NONE
        plan.reason = ("测量骨差 %.1f mm 只占脚部差 %.1f mm 的 %.0f%% —— "
                       "位移出现在身体中段，属于姿态差而非站位差，不动"
                       % (d, f, ratio * 100))
        return plan

    plan.mode = MATCH
    if d > LARGE_MM:
        plan.reason = ("测量骨世界差 %.1f mm（较大），已按 match 给出；若这是刻意的换场/换站位，"
                       "请改成 keep" % d)
    else:
        plan.reason = "测量骨世界差 %.1f mm、全身中位 %.1f mm，判为整体位移" % (d, g)
    return plan


def _quat_rot_z(v, deg: float):
    """绕世界竖直轴（Y）旋转。MMD/Blender 里 Y 向上。"""
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    x, y, z = v
    # 绕 Y 轴
    return (x * c + z * s, y, -x * s + z * c)


def _quat_mul_y(q, deg: float):
    """在四元数上左乘一个绕 Y 轴的旋转（w,x,y,z 顺序，VMD 存 xyzw）。"""
    a = math.radians(deg) * 0.5
    cy, sy = math.cos(a), math.sin(a)
    # Y 轴四元数 (w,x,y,z) = (cy, 0, sy, 0)
    w2, x2, y2, z2 = q[3], q[0], q[1], q[2]
    w1, y1 = cy, sy
    w = w1 * w2 - y1 * y2
    x = w1 * x2 + y1 * z2
    y = w1 * y2 + y1 * w2
    z = w1 * z2 - y1 * x2
    n = math.sqrt(w * w + x * x + y * y + z * z) or 1.0
    return (x / n, y / n, z / n, w / n)


def apply_to_segment(motion, inject_bone: str, t, r_z_deg: float = 0.0):
    """把 t（世界平移，米）注入到某根的**位移键**上。

    返回 (新骨骼段 bytes, 处理的记录数, 说明)。
    - 若该骨有键：每条键的位置加 t（整体搬动，段内相对动作不变）
    - 若该骨没键：新建一条 identity 键承载 t
    """
    if abs(r_z_deg) > 1e-6:
        raise NotImplementedError("旋转注入尚未实现：先用纯平移验证流程")
    t = tuple(float(v) for v in t)
    d = motion.raw
    out = bytearray()
    hit = 0
    for i in range(motion.bone_count):
        s = motion.bone_start + i * vmd_mod.BONE_RECORD
        rec = bytearray(d[s:s + vmd_mod.BONE_RECORD])
        name = bytes(rec[0:15]).split(b"\x00")[0].decode("cp932", "replace")
        if name == inject_bone:
            pos = struct.unpack_from("<3f", rec, 19)
            struct.pack_into("<3f", rec, 19,
                             pos[0] + t[0], pos[1] + t[1], pos[2] + t[2])
            hit += 1
        out += rec
    note = ""
    count = motion.bone_count
    if hit == 0:
        out += vmd_mod._make_bone_record(inject_bone, 0, t, (0.0, 0.0, 0.0, 1.0))
        count += 1
        note = "该骨原本无键，已在帧 0 新建承载键"
    return bytes(out), count, hit, note


def apply_plan(plan: AlignmentPlan, out_path: str) -> dict:
    """把 plan 施加到 B 段，写出新的 B VMD。"""
    if plan.mode != MATCH:
        return {"applied": False, "reason": "mode=%s，不注入" % plan.mode}
    b = vmd_mod.load(plan.b_path)
    seg, count, hit, note = apply_to_segment(b, plan.inject_bone or "全ての親",
                                             plan.t, plan.r_z_deg)
    # 用替换后的骨骼段重写整份文件
    head = bytearray(b.raw[:30 + (20 if b.magic == "0002" else 10)])
    morphs = b.raw[b.morph_start:b.morph_end]
    tail = b.raw[b.tail_start:] if b.tail_start < len(b.raw) else struct.pack("<4I", 0, 0, 0, 0)
    out = bytearray(head)
    out += struct.pack("<I", count)
    out += seg
    out += struct.pack("<I", b.morph_count)
    out += morphs
    out += tail

    import os
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(bytes(out))
    return {"applied": True, "out": out_path, "records": count,
            "injected_records": hit, "note": note}

SCALE_DEFAULT = 0.08   # PMX 单位 × 0.08 = 米


def apply_to_concat(motion, plan: AlignmentPlan, a_end: int, b_start: int,
                    scale: float = SCALE_DEFAULT):
    """在**拼接后**的时间轴上注入平移。

    两件必须一起做的事（都踩过）：
      1. 单位换算：plan.t 是世界米，VMD 位置通道是 PMX 单位 → 除 scale
      2. 止住端点保持：B 的键从 b_start 开始，向后常量外插会把 A 段一起抬。
         必须在 a_end 处插一条"未偏移"的键，泄漏才止步，且过渡自然落在 gap 区间。
    """
    if plan.t_model:
        t_pmx = tuple(float(v) for v in plan.t_model)
    else:
        # 实测基变换：world = 0.08 × swapYZ(vmd)，所以 vmd = swapYZ(world) / 0.08
        t_pmx = (float(plan.t[0]) / scale, float(plan.t[2]) / scale,
                 float(plan.t[1]) / scale)
    inject = plan.inject_bone or "全ての親"
    d = motion.raw

    records = []
    records_with_val = []      # 只收注入骨：(frame, pos)
    base_at_end = (0.0, 0.0, 0.0)
    has_end_key = False
    first_val = None
    for i in range(motion.bone_count):
        s0 = motion.bone_start + i * vmd_mod.BONE_RECORD
        rec = bytearray(d[s0:s0 + vmd_mod.BONE_RECORD])
        name = bytes(rec[0:15]).split(b"\x00")[0].decode("cp932", "replace")
        frame = struct.unpack_from("<I", rec, 15)[0]
        if name == inject:
            records_with_val.append((frame, struct.unpack_from("<3f", rec, 19)))
            if first_val is None:
                first_val = struct.unpack_from("<3f", rec, 19)
            if frame == a_end:
                has_end_key = True
                base_at_end = struct.unpack_from("<3f", rec, 19)
            elif frame <= a_end:
                base_at_end = struct.unpack_from("<3f", rec, 19)
            if frame > a_end:
                pos = struct.unpack_from("<3f", rec, 19)
                struct.pack_into("<3f", rec, 19,
                                 pos[0] + t_pmx[0], pos[1] + t_pmx[1], pos[2] + t_pmx[2])
        records.append((frame, bytes(rec)))

    # 锚点值必须是"该骨在 a_end 处真实的插值结果"。
    # 该骨可能在 A 段有键（如帧 0）、在 B 段首有键（a_end 之后），A 段整段都在两者之间插值；
    # 写 0 或写首键值都会改掉 A 段末尾（都踩过）。这里按相邻键线性求值。
    if not has_end_key:
        mine = sorted([(f, recs) for f, recs in records_with_val], key=lambda x: x[0])
        prev = None
        nxt = None
        for f, val in mine:
            if f <= a_end:
                prev = (f, val)
            elif nxt is None:
                nxt = (f, val)
                break
        if prev and nxt and nxt[0] > prev[0]:
            k = (a_end - prev[0]) / float(nxt[0] - prev[0])
            base_at_end = tuple(prev[1][i] + (nxt[1][i] - prev[1][i]) * k for i in range(3))
        elif prev:
            base_at_end = prev[1]
        elif nxt:
            base_at_end = nxt[1]
    added = 0
    if not has_end_key:
        records.append((a_end, vmd_mod._make_bone_record(
            inject, a_end, base_at_end, (0.0, 0.0, 0.0, 1.0))))
        added = 1
    records.sort(key=lambda x: x[0])

    head = bytearray(d[:30 + (20 if motion.magic == "0002" else 10)])
    morphs = d[motion.morph_start:motion.morph_end]
    tail = d[motion.tail_start:] if motion.tail_start < len(d) else struct.pack("<4I", 0, 0, 0, 0)
    out = bytearray(head)
    out += struct.pack("<I", len(records))
    out += b"".join(r for _, r in records)
    out += struct.pack("<I", motion.morph_count)
    out += morphs
    out += tail
    return bytes(out), {"inject": inject, "t_pmx": t_pmx, "added_anchor": added,
                        "records": len(records), "a_end": a_end}
