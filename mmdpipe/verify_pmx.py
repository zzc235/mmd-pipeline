"""PMX 净空修复的验证套件（通用版，对齐工程报告 §2.2 的 C1–C8）。

输入原模型 + 修复后模型，逐条断言，不依赖任何模型专属索引。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import clearance as C
from . import pmx as pmx_mod

EPS_MM = 0.01          # 位置核对容差（世界毫米）


@dataclass
class Check:
    code: str
    ok: bool
    detail: str


@dataclass
class VerifyResult:
    checks: list = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.ok)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def text(self) -> str:
        rows = ["PMX 净空修复验证  %d/%d" % (self.passed, self.total)]
        for c in self.checks:
            rows.append("  %s %s  %s" % ("PASS" if c.ok else "FAIL", c.code, c.detail))
        return "\n".join(rows)


def _all_pairs_overlap(model, only=None):
    """全体刚体两两重叠（>0），可选只测与 only 集合相关的对。"""
    out = {}
    rigs = model.rigids
    for i in range(len(rigs)):
        for j in range(i + 1, len(rigs)):
            if only is not None and i not in only and j not in only:
                continue
            depth, _ = C.penetration(rigs[i], rigs[j])
            if depth > 0:
                out[(i, j)] = depth
    return out


def verify(orig, fixed, plan, scale=0.08) -> VerifyResult:
    res = VerifyResult()

    # C1 结构数量一致
    ok = (len(orig.rigids) == len(fixed.rigids)
          and len(orig.joints) == len(fixed.joints))
    res.checks.append(Check("C1", ok,
                            "刚体 %d/%d 关节 %d/%d"
                            % (len(orig.rigids), len(fixed.rigids),
                               len(orig.joints), len(fixed.joints))))

    # C2 关节索引全部有效
    bad = [j.index for j in fixed.joints
           if not (0 <= j.rigid_a < len(fixed.rigids)
                   and 0 <= j.rigid_b < len(fixed.rigids))]
    res.checks.append(Check("C2", not bad, "非法关节索引 %d 个" % len(bad)))

    # C4 位移集合 == 可真侵入集合（真侵入 = 移了 + 明确跳过的）
    rep = C.scan(orig)
    truth = sorted({h.body for h in rep.collidable_penetrating})
    moved = sorted(plan.get("moved", []))
    skipped_ids = sorted({s["body"] for s in plan.get("skipped", [])})
    accounted = sorted(set(moved) | set(skipped_ids))
    overlap = set(moved) & set(skipped_ids)
    res.checks.append(Check("C4", truth == accounted and not overlap,
                            "真侵入 %d / 已修 %d / 跳过 %d（漏账 %d，重复 %d）"
                            % (len(truth), len(moved), len(skipped_ids),
                               len(set(truth) - set(accounted)), len(overlap))))

    # C4b 每个跳过项都要有原因（不许静默漏修）
    bad_reason = [s for s in plan.get("skipped", []) if not s.get("reason")]
    res.checks.append(Check("C4b", not bad_reason,
                            "跳过 %d 项，其中无原因 %d 项"
                            % (len(plan.get("skipped", [])), len(bad_reason))))

    # C5 残留只允许出现在"已判定为不可修"的刚体上
    rep2 = C.scan(fixed)
    left = rep2.collidable_penetrating
    left_ids = {h.body for h in left}
    unexpected = left_ids - set(skipped_ids)
    tight = min((C.to_mm(-h.depth, scale) for h in rep2.hits if h.collidable), default=0.0)
    res.checks.append(Check("C5", not unexpected,
                            "残留 %d 处（都在跳过名单内=%s），最紧余量 %.2f mm"
                            % (len(left), not unexpected, tight)))

    # C6 关节锚点同步：两端都动取均值，单端取一半
    base = {r.index: r.position for r in orig.rigids}
    moved_delta = {i: tuple(fixed.rigids[i].position[k] - base[i][k] for k in range(3))
                   for i in moved}
    bad = []
    for j in orig.joints:
        da = moved_delta.get(j.rigid_a)
        db = moved_delta.get(j.rigid_b)
        if da is None and db is None:
            continue
        if da is not None and db is not None:
            expect = tuple((da[k] + db[k]) / 2.0 for k in range(3))
        else:
            src = da if da is not None else db
            expect = tuple(v / 2.0 for v in src)
        nf = fixed.joints[j.index].position
        err = max(abs(nf[k] - (j.position[k] + expect[k])) for k in range(3))
        if err * scale * 1000 > EPS_MM:
            bad.append((j.index, err))
    res.checks.append(Check("C6", not bad,
                            "失配 %d，误差 %.4f mm"
                            % (len(bad), max((e for _, e in bad), default=0.0) * scale * 1000)))

    # C7 无新增重叠（只测与被移动刚体相关的对）
    only = set(moved)
    before = _all_pairs_overlap(orig, only)
    after = _all_pairs_overlap(fixed, only)
    new = sorted(set(after) - set(before))
    res.checks.append(Check("C7", not new,
                            "被移动刚体 × 全部：新增重叠 %d" % len(new)))

    # C8 反向对照：原版必须有侵入，否则这套判据对这次样本无效
    res.checks.append(Check("C8", bool(truth),
                            "原版可碰撞侵入 %d 个（为 0 则判据对本次无效）" % len(truth)))
    return res
