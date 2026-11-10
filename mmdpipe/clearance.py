"""净空检测与修复 —— 纯 Python，不依赖 bpy。

几何口径 + 可碰撞口径并列，修复只动"真侵入"的刚体，并同步关节锚点。

判据（来自工程报告 §3.1）：
  穿透必须带「双向掩码 + 非关节连」过滤；纯几何口径只能用来找嫌疑。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import pmx as pmx_mod

SHAPE_SPHERE = 0
SHAPE_BOX = 1
SHAPE_CAPSULE = 2

# 头部胶囊识别（唯一还依赖名字的地方，保留兜底）
HEAD_KEYS = ("頭", "头", "head")


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _len(a):
    return math.sqrt(_dot(a, a))


def _norm(a):
    n = _len(a)
    return (a[0] / n, a[1] / n, a[2] / n) if n > 1e-12 else (0.0, 0.0, 0.0)


def _rot(v, rot):
    """XYZ 欧拉（弧度），与 Blender rotation_euler 默认序一致：Rx→Ry→Rz。"""
    x, y, z = rot
    cx, sx = math.cos(x), math.sin(x)
    cy, sy = math.cos(y), math.sin(y)
    cz, sz = math.cos(z), math.sin(z)
    # Rx
    ax = v[0]
    ay = v[1] * cx - v[2] * sx
    az = v[1] * sx + v[2] * cx
    # Ry
    bx = ax * cy + az * sy
    by = ay
    bz = -ax * sy + az * cy
    # Rz
    return (bx * cz - by * sz, bx * sz + by * cz, bz)


def capsule_ends(rb):
    radius = rb.size[0]
    half = rb.size[1] / 2.0
    axis = _rot((0.0, half, 0.0), rb.rotation)
    return _sub(rb.position, axis), _add(rb.position, axis), radius


def closest_on_segment(p, a, b):
    ab = _sub(b, a)
    denom = _dot(ab, ab)
    if denom < 1e-12:
        return a
    t = max(0.0, min(1.0, _dot(_sub(p, a), ab) / denom))
    return _add(a, _mul(ab, t))


def axis_of(rb):
    """球/胶囊 → (a, b, radius)。胶囊轴沿局部 Y，半长 = size[1]/2。

    与 mmd-physics 的 pmx_geom.axis_of 一致（已用报告里的 -5.9/-3.2/-7.2 mm 对过）。
    """
    rad = float(rb.size[0])
    if rb.shape == SHAPE_SPHERE:
        return rb.position, rb.position, rad
    half = float(rb.size[1]) / 2.0
    ax = _rot((0.0, 1.0, 0.0), rb.rotation)
    return (_sub(rb.position, _mul(ax, half)),
            _add(rb.position, _mul(ax, half)), rad)


def _clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else (hi if x > hi else x)


def seg_seg_closest(p1, q1, p2, q2):
    """两线段最近点对，返回 (点1, 点2, 距离)。标准 Ericson 解法。"""
    d1 = _sub(q1, p1)
    d2 = _sub(q2, p2)
    r = _sub(p1, p2)
    a = _dot(d1, d1)
    e = _dot(d2, d2)
    f = _dot(d2, r)
    eps = 1e-12

    if a <= eps and e <= eps:
        return p1, p2, _len(r)

    if a <= eps:
        s = 0.0
        t = _clamp(f / e)
    else:
        c = _dot(d1, r)
        if e <= eps:
            t = 0.0
            s = _clamp(-c / a)
        else:
            b = _dot(d1, d2)
            denom = a * e - b * b
            s = _clamp((b * f - c * e) / denom) if denom > eps else 0.0
            t = (b * s + f) / e
            if t < 0.0:
                t = 0.0
                s = _clamp(-c / a)
            elif t > 1.0:
                t = 1.0
                s = _clamp((b - c) / a)

    c1 = _add(p1, _mul(d1, s))
    c2 = _add(p2, _mul(d2, t))
    return c1, c2, _len(_sub(c1, c2))


def penetration(a_rb, b_rb):
    """返回 (重叠深度, (a 侧最近点, b 侧最近点))。深度用 PMX 单位；>0 表示重叠。"""
    a1, b1, r1 = axis_of(a_rb)
    a2, b2, r2 = axis_of(b_rb)
    c1, c2, d = seg_seg_closest(a1, b1, a2, b2)
    return (r1 + r2) - d, (c1, c2)


def to_mm(depth, scale=0.08):
    return depth * scale * 1000.0


def head_capsules(model, min_radius=0.03):
    """头部胶囊：capsule + 名字含 頭/头/head。找不到就退回半径最大的胶囊。"""
    caps = [rb for rb in model.rigids if rb.shape == SHAPE_CAPSULE]
    named = []
    for rb in caps:
        if 0 <= rb.bone < len(model.bones):
            nm = model.bones[rb.bone].name.lower()
            if any(k in nm for k in HEAD_KEYS):
                named.append(rb)
    if named:
        return named, "name"
    big = [rb for rb in caps if rb.size[0] >= min_radius]
    big.sort(key=lambda r: -r.size[0])
    return big[:2], "largest"


def _collide(a, b) -> bool:
    return bool((a.mask >> b.group) & 1) and bool((b.mask >> a.group) & 1)


@dataclass
class Hit:
    body: int
    body_name: str
    capsule: int
    capsule_name: str
    depth: float            # >0 侵入
    collidable: bool        # 可碰撞口径（双向掩码 + 非关节连）
    jointed: bool


@dataclass
class ClearanceReport:
    hits: list = field(default_factory=list)
    head_source: str = ""
    notes: list = field(default_factory=list)

    @property
    def penetrating(self):
        return [h for h in self.hits if h.depth > 0]

    @property
    def collidable_penetrating(self):
        return [h for h in self.hits if h.depth > 0 and h.collidable and not h.jointed]


def scan(model, extra_capsules=None) -> ClearanceReport:
    caps, source = head_capsules(model)
    if extra_capsules:
        caps = caps + list(extra_capsules)
    rep = ClearanceReport(head_source=source)

    jointed = set()
    for j in model.joints:
        if j.rigid_a >= 0 and j.rigid_b >= 0:
            jointed.add((min(j.rigid_a, j.rigid_b), max(j.rigid_a, j.rigid_b)))

    cap_ids = {c.index for c in caps}
    capsule_overlaps = []
    for cap in caps:
        for rb in model.rigids:
            if rb.index == cap.index:
                continue
            if rb.index in cap_ids:
                # 头部胶囊彼此互叠是模型自带问题（飞霄 5 个胶囊两两全叠），
                # 不属于"头发穿头"，单独统计。
                depth, _ = penetration(rb, cap)
                if depth > 0:
                    capsule_overlaps.append((rb.name, cap.name, depth))
                continue
            depth, cp = penetration(rb, cap)
            # 只有 mode1/2 会把变换回填给骨骼 → 只有它们能造成可见的穿模。
            # mode0 是纯碰撞胶囊，彼此堆叠是正常设计（首/頭 胶囊本来就插在一起）。
            if rb.mode == 0:
                if depth > 0:
                    rep.notes.append("%s(mode0) 与 %s 重叠 %.1f mm —— 纯碰撞体，不修"
                                     % (rb.name, cap.name, to_mm(depth)))
                continue
            j = (min(rb.index, cap.index), max(rb.index, cap.index)) in jointed
            rep.hits.append(Hit(
                body=rb.index, body_name=rb.name,
                capsule=cap.index, capsule_name=cap.name,
                depth=depth, collidable=_collide(rb, cap), jointed=j,
            ))
    if capsule_overlaps:
        worst = max(capsule_overlaps, key=lambda x: x[2])
        rep.notes.append("头部胶囊互叠 %d 对，最深 %s vs %s = %.1f mm（模型自带，不是头发穿头）"
                         % (len(capsule_overlaps), worst[0], worst[1], to_mm(worst[2])))
    rep.hits.sort(key=lambda h: -h.depth)
    return rep


def _candidate_dirs(c_hair, c_head, cap):
    """候选外移方向：先试"远离头部最近点"，再试沿头胶囊轴 ±、以及绕轴四个径向。"""
    dirs = [_norm(_sub(c_hair, c_head))]
    ca, cb, _r = axis_of(cap)
    axis = _norm(_sub(cb, ca))
    if axis != (0.0, 0.0, 0.0):
        dirs.append(axis)
        dirs.append(_mul(axis, -1.0))
        for seed in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
            perp = _sub(seed, _mul(axis, _dot(seed, axis)))
            n = _norm(perp)
            if n != (0.0, 0.0, 0.0):
                dirs.append(n)
                dirs.append(_mul(n, -1.0))
    out = []
    for d in dirs:
        if d != (0.0, 0.0, 0.0) and d not in out:
            out.append(d)
    return out


def _pair_depths(model, idx):
    """某个刚体与其余刚体的全部重叠深度。"""
    rb = model.rigids[idx]
    out = {}
    for other in model.rigids:
        if other.index == idx:
            continue
        d, _ = penetration(rb, other)
        if d > 0:
            out[other.index] = d
    return out


def _component(model, idx):
    """关节连通的刚体组（含自身）。"""
    parent = {r.index: r.index for r in model.rigids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for j in model.joints:
        a, b = j.rigid_a, j.rigid_b
        if a in parent and b in parent:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra
    root = find(idx)
    return [i for i in parent if find(i) == root]


def _component_ok(model, comp, delta, before_all, target_idx, cap):
    """整组平移是否安全：组内不动，组外不得新增重叠，且目标刚体脱离胶囊。"""
    for i in comp:
        model.rigids[i].position = _add(model.rigids[i].position, delta)
    try:
        for i in comp:
            after = _pair_depths(model, i)
            new = set(after) - set(before_all[i])
            new = {j for j in new if j not in comp}
            if new:
                return False
        return penetration(model.rigids[target_idx], cap)[0] <= 0
    finally:
        for i in comp:
            model.rigids[i].position = _sub(model.rigids[i].position, delta)


def plan_fix(model, margin=0.06, max_rounds=12, guard_new_overlaps=True) -> dict:
    """计算外移方案。返回 {rigid_pos, joint_pos, moved, skipped, rounds, complete}

    每一轮把**所有**当前侵入的刚体各推一次（不是一次只推一个），否则 20+ 个侵入要跑几十轮。

    guard_new_overlaps：推之前先试算，若这一推会与该刚体原本不重叠的对象产生新重叠，
    就撤回并记为 skipped——外移一个兜帽把它推进耳朵，这种"修好一处坏一处"必须挡住。
    """
    base = {rb.index: rb.position for rb in model.rigids}
    moved = {}
    skipped = []
    group_moves = []
    rounds = 0
    for rounds in range(1, max_rounds + 1):
        rep = scan(model)
        targets = rep.collidable_penetrating
        if not targets:
            rounds -= 1
            break
        seen = set()
        for hit in sorted(targets, key=lambda h: -h.depth):
            if hit.body in seen:
                continue
            seen.add(hit.body)
            rb = model.rigids[hit.body]
            cap = model.rigids[hit.capsule]
            depth, (c_hair, c_head) = penetration(rb, cap)
            direction = _norm(_sub(c_hair, c_head))
            if direction == (0.0, 0.0, 0.0):
                continue
            before_pairs = _pair_depths(model, rb.index) if guard_new_overlaps else None
            old = rb.position
            applied = False
            for direction in _candidate_dirs(c_hair, c_head, cap):
                rb.position = _add(old, _mul(direction, depth + margin))
                if not guard_new_overlaps:
                    applied = True
                    break
                after_pairs = _pair_depths(model, rb.index)
                new = sorted(set(after_pairs) - set(before_pairs))
                still = penetration(rb, cap)[0]
                if not new and still <= 0:
                    applied = True
                    break
            if not applied:
                # 策略二：整组刚性平移（组内相对关系不变，不会制造组内新重叠）
                comp = _component(model, rb.index)
                if len(comp) > 1:
                    before_all = {i: _pair_depths(model, i) for i in comp}
                    for direction in _candidate_dirs(c_hair, c_head, cap):
                        delta = _mul(direction, depth + margin)
                        if _component_ok(model, comp, delta, before_all, rb.index, cap):
                            for i in comp:
                                model.rigids[i].position = _add(
                                    model.rigids[i].position, delta)
                                moved[i] = model.rigids[i].position
                            applied = True
                            group_moves.append({"anchor": rb.name, "size": len(comp)})
                            break
                    if applied:
                        continue
            if not applied:
                rb.position = old
                skipped.append({
                    "body": rb.index, "name": rb.name,
                    "reason": "单点平移与整组平移都会制造新重叠或解不掉",
                    "depth_mm": round(to_mm(depth), 2),
                })
                continue
            moved[rb.index] = rb.position

    # 关节锚点同步：两端都动取均值；只有一端动取该端位移的一半
    joint_pos = {}
    for j in model.joints:
        da = _sub(model.rigids[j.rigid_a].position, base[j.rigid_a]) \
            if j.rigid_a in moved else None
        db = _sub(model.rigids[j.rigid_b].position, base[j.rigid_b]) \
            if j.rigid_b in moved else None
        if da is None and db is None:
            continue
        if da is not None and db is not None:
            shift = _mul(_add(da, db), 0.5)
        else:
            shift = _mul(da if da is not None else db, 0.5)
        joint_pos[j.index] = _add(j.position, shift)

    remaining = scan(model).collidable_penetrating
    # 跳过记录按刚体去重（同一刚体每轮都会再试一次）
    uniq = {}
    for s in skipped:
        uniq.setdefault(s["body"], s)
    skipped = list(uniq.values())
    return {
        "rigid_pos": moved,
        "joint_pos": joint_pos,
        "moved": sorted(moved),
        "skipped": skipped,
        "group_moves": group_moves,
        "rounds": rounds,
        "complete": not remaining,
        "remaining": [{"body": h.body, "name": h.body_name,
                       "depth_mm": round(to_mm(h.depth), 2)} for h in remaining],
    }
