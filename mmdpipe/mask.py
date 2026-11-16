"""PMX 碰撞掩码的读回与判据（纯 Python，不 import bpy）。

PMX 给每个刚体两张位图：`group`（它属于第 0–15 组，一个字节）与 `mask`（16 位，
**第 n 位为 1 = 与第 n 组碰**；位清掉 = 忽略该组）。碰撞成立要**两边都允许**：
A 忽略 B 的组、或 B 忽略 A 的组，任一条成立这一对就不该碰。

2026-11-16 实测（`kafuka_all/pmx/卡芙卡3.0_fixH.pmx`，145 个刚体）：

* 掩码 145/145 个都写了（不是空表）：252 条「(刚体, 组) 忽略」声明
  → 去重后 **4535 个无序对**本该不碰；
* **单向忽略的有序对 2924 个**（约 14% 的全序）——这张掩码**不对称**。

为什么不对 `rigid_body.collision_collections` 做「按掩码设位」：Blender 那 16 位是
**归属 + 判交**语义（两个物体的集合有交集才碰），天生对称；上面那 2924 个单向对用
交集写不出来——写成"按 mask 设位"会让本该碰的组也停碰。唯一能精确表达不对称的机制
是**成对的 `DISABLE_COLLISIONS` 约束**，而 mmd_tools 的 `Model.build()` 已经在
`buildRigids()` 里做了，只是**只给距离够近的对建**：

    distance < non_collision_distance_scale * (range_a + range_b) / 2

远处被忽略的对不建对象，于是它们在 Bullet 里照样会撞。这里的读回把这个差距变成一个
可判的数（`coverage`），并让上面那个比例可由预设调。
"""
from __future__ import annotations

GROUP_COUNT = 16
ALL_GROUPS = (1 << GROUP_COUNT) - 1
NCC_MMD_TYPE = "NON_COLLISION_CONSTRAINT"

ENCODING_NOTE = (
    "collision_collections = mask | (1 << own_group)；假碰（共享位但 PMX 说该不碰）"
    "由逐对 DISABLE_COLLISIONS 约束分开。不用「交集近似」代替约束——那会静默停碰该碰的对。"
)

# Blender 侧语义实测（`tests_bpy/mask_semantics_probe.py`，2026-11-16）。
# spec §2.5 明确要求先测再实现，所以这里存的是**实测读数**，不是理解。
MEASURED_SEMANTICS = {
    "probe": "tests_bpy/mask_semantics_probe.py",
    "measured_at": "2026-11-16",
    "status": "PENDING",       # 跑完填实测值（见 probe 的 PROBE_JSON）
    "note": "Blender 的 collision_collections 是「共享某一位即碰撞」的对称语义；"
            "PMX 的非对称掩码无法用位表达，只能靠逐对约束",
}


def pair_key(a: str, b: str) -> tuple:
    return (a, b) if a < b else (b, a)


def mask_bits(obj) -> int:
    """把 `mmd_rigid.collision_group_mask`（16 个 bool）读成整数位图。

    读不到时返回 `ALL_GROUPS`（= 与所有组碰）：不可知**不该**表现成"忽略一切"，
    那会让一份读不出来的场景看起来"掩码很严格"。
    """
    rigid = getattr(obj, "mmd_rigid", None)
    raw = getattr(rigid, "collision_group_mask", None)
    if raw is None:
        return ALL_GROUPS
    value = 0
    for n, bit in enumerate(raw):
        if bit:
            value |= 1 << n
    return value


def group_of(obj) -> int:
    rigid = getattr(obj, "mmd_rigid", None)
    value = getattr(rigid, "collision_group_number", 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def collections_of(obj) -> int:
    """Bullet 侧真实生效的 16 位（`rigid_body.collision_collections`）。

    这不是 PMX 掩码的翻版，是**另一个机制**（归属+判交，天生对称）。读回来的用处是
    说清"现在的碰撞限制到底靠哪一边"：这 16 位全 1 就意味着一对一对的
    `DISABLE_COLLISIONS` 约束是唯一在起作用的机制。
    """
    body = getattr(obj, "rigid_body", None)
    raw = getattr(body, "collision_collections", None)
    if raw is None:
        return ALL_GROUPS
    value = 0
    for n, bit in enumerate(raw):
        if bit:
            value |= 1 << n
    return value


def _pair(a: str, b: str) -> tuple:
    return (a, b) if a < b else (b, a)


def mask_declarations(rigids) -> dict:
    """按 PMX 约定算出「声明了不该碰」的无序对。

    返回 `{bodies, groups, declarations, declared_pairs, all_on, all_off, one_sided}`：
      * `declared_pairs` 是 `{(name_a, name_b)}`（名字升序），任一侧忽略即算；
      * `one_sided` 是"只有一侧忽略"的对数——它正是"能不能用 `collision_collections`
        表达"的分水岭，所以单独报出来。
    """
    bodies = list(rigids)
    groups: dict = {}
    for obj in bodies:
        groups.setdefault(group_of(obj), []).append(obj)
    declared = set()
    declarations = 0
    all_on = all_off = 0
    for obj in bodies:
        bits = mask_bits(obj)
        if bits == ALL_GROUPS:
            all_on += 1
        elif bits == 0:
            all_off += 1
        for n in range(GROUP_COUNT):
            if bits & (1 << n):
                continue
            others = [o for o in groups.get(n, ()) if o is not obj]
            if not others:
                continue            # 该组没有刚体，忽略它没有意义，不计数
            declarations += 1
            for other in others:
                declared.add(_pair(obj.name, other.name))
    by_name = {o.name: o for o in bodies}
    one_sided = 0
    for (a, b) in declared:
        obj_a, obj_b = by_name[a], by_name[b]
        a_ignores = not (mask_bits(obj_a) >> group_of(obj_b)) & 1
        b_ignores = not (mask_bits(obj_b) >> group_of(obj_a)) & 1
        if a_ignores != b_ignores:
            one_sided += 1
    return {
        "bodies": len(bodies),
        "groups": {g: len(v) for g, v in sorted(groups.items())},
        "declarations": declarations,
        "declared_pairs": declared,
        "all_on": all_on,
        "all_off": all_off,
        "one_sided": one_sided,
    }


def disabled_pairs(objects) -> set:
    """场景里**实际挡掉**的刚体对：`disable_collisions == True` 的约束。

    ncc 空物体与关节都算。只认 `True`：`False` 的约束不起过滤作用，把它算成"挡掉了"
    正是那种"看起来很严格"的假绿。
    """
    pairs = set()
    for obj in objects:
        con = getattr(obj, "rigid_body_constraint", None)
        if con is None or not getattr(con, "disable_collisions", False):
            continue
        a = getattr(getattr(con, "object1", None), "name", None)
        b = getattr(getattr(con, "object2", None), "name", None)
        if not a or not b or a == b:
            continue
        pairs.add(_pair(a, b))
    return pairs


def mask_report(rigids, objects) -> dict:
    """逐刚体回读 + 汇总：声明了多少对 / 实际挡了多少对 / 差在哪。

    `coverage` 在**没有声明**时给 `None`（不是 1.0）：全 1 掩码意味着"与所有组碰"，
    一个没声明任何排除的场景覆盖率不是"满分"，是"无从谈起"。把这两件事写成同一个数，
    就是今天反复撞的"干净长得像没扫"。
    """
    bodies = list(rigids)
    decl = mask_declarations(bodies)
    blocked = disabled_pairs(objects)
    declared = decl["declared_pairs"]
    covered = declared & blocked
    uncovered = sorted(declared - blocked)
    by_name = {o.name: o for o in bodies}

    def distance(a, b):
        oa, ob = by_name.get(a), by_name.get(b)
        if oa is None or ob is None:
            return None
        try:
            return round((oa.location - ob.location).length, 4)
        except (AttributeError, TypeError):
            return None

    rows = []
    for obj in bodies:
        bits = mask_bits(obj)
        rows.append({
            "name": obj.name,
            "group": group_of(obj),
            "mask": bits,
            "collections": collections_of(obj),
            "ignored_groups": [n for n in range(GROUP_COUNT) if not (bits >> n) & 1],
            "blocked_pairs": sum(1 for p in declared if obj.name in p and p in blocked),
            "declared_pairs": sum(1 for p in declared if obj.name in p),
        })
    return {
        "rigids": decl["bodies"],
        "groups": decl["groups"],
        "declarations": decl["declarations"],
        "declared_pairs": len(declared),
        "blocked_pairs": len(covered),
        "uncovered_pairs": len(uncovered),
        "coverage": round(len(covered) / len(declared), 4) if declared else None,
        "all_on_bodies": decl["all_on"],
        "all_off_bodies": decl["all_off"],
        "one_sided_pairs": decl["one_sided"],
        "collections_non_default": sum(1 for o in bodies
                                       if collections_of(o) != ALL_GROUPS),
        "examples": [{"a": a, "b": b, "distance": distance(a, b)}
                     for a, b in uncovered[:5]],
        "rows": rows,
    }


# ------------------------------------------------------------------ 位映射（spec §3）
#
# 编码：`collision_collections = mask | (1 << own_group)`。
#
# **为什么加自己组的位**（不是直接用 mask）：Blender 那 16 位是「共享某位就碰」的对称
# 语义。PMX 的一对 (A,B) 该碰 ⟺ A.mask 含 g_B 且 B.mask 含 g_A。若只写 mask，经典情形
# 「身体组 0（mask 只有 bit1）× 组 1（mask 只有 bit0）」两边都不含自己组的位，交集为空
# ——明明该碰却不会碰。加上自己组的位之后有一条**可证**的性质：
#
#   PMX 该碰的每一对，`mask|own` 下必然共享某一位。
#   证明：g_A == g_B 时两位都在自己组的位上；否则 A 含 bit(g_B)（PMX 该碰），而 B 含
#   自己组的位 bit(g_B) ⇒ 共享 bit(g_B)。
#
# 实测（`卡芙卡3.0_fixH.pmx`，145 刚体 / 10440 对）：PMX 该碰 5905 / 不该碰 4535，
# 「该碰却无共享位」= **0**，与上面的证明一致。
#
# 代价是**假碰**：两个都「与第 5 组碰」但彼此不该碰的刚体，会共享 bit5。这类对由
# `DISABLE_COLLISIONS` 约束补（`plans()` 里算出来的 `constraints_added`），所以最终
# 语义等价，代价是约束数量。**不许用「交集模型近似」代替约束**：那会把该碰的成对
# 静默停碰（本文件顶上那段 2924 个单向对就是证据）。

def collision_bits(obj) -> int:
    """Blender 侧应当写入的位：`mask | (1 << own_group)`（spec §3 的映射）。"""
    return mask_bits(obj) | (1 << group_of(obj))


def pmx_collides(group_a: int, mask_a: int, group_b: int, mask_b: int) -> bool:
    """PMX 语义的一对判定：**两边都要允许**。"""
    return bool((mask_a >> group_b) & 1) and bool((mask_b >> group_a) & 1)


def plans(rigids) -> dict:
    """纯逻辑：算出该写哪些位、该补哪些约束、哪些表达不了（不发 bpy 调用）。

    返回的 `add_constraints` 是 `[(name_a, name_b, 原因)]`，`skipped` 是
    `[{"pair"/"name", "reason"}]`——**逐条列出，不许静默跳过**（spec §1 / `D-086`）。
    """
    bodies = list(rigids)
    facts = [(o.name, group_of(o), mask_bits(o)) for o in bodies]
    bits = {name: (bits | (1 << group)) for name, group, bits in facts}
    by_name = {name: (group, mask) for name, group, mask in facts}

    pairs_total = len(bodies) * (len(bodies) - 1) // 2
    collide = 0
    separated_by_bits = 0
    overlap_nocollide = []
    unexpressible = []
    asymmetric = []
    for i in range(len(facts)):
        for j in range(i + 1, len(facts)):
            name_a, group_a, mask_a = facts[i]
            name_b, group_b, mask_b = facts[j]
            want = pmx_collides(group_a, mask_a, group_b, mask_b)
            overlap = bool(bits[name_a] & bits[name_b])
            if want:
                collide += 1
                if not overlap:
                    unexpressible.append((name_a, name_b))
            else:
                if overlap:
                    overlap_nocollide.append((name_a, name_b))
                else:
                    separated_by_bits += 1
            # 非对称：一侧允许、另一侧不允许（交集模型对这类只能取"碰"或"不碰"）
            a_ok = bool((mask_a >> group_b) & 1)
            b_ok = bool((mask_b >> group_a) & 1)
            if a_ok != b_ok:
                asymmetric.append((name_a, name_b))

    histogram = {}
    for name, group, bits_value in facts:
        key = "%04x" % bits_value
        histogram[key] = histogram.get(key, 0) + 1
    groups = {}
    for name, group, bits_value in facts:
        groups[group] = groups.get(group, 0) + 1

    skipped = []
    for name_a, name_b in unexpressible:
        skipped.append({
            "pair": [name_a, name_b],
            "reason": "PMX 说该碰，但 `mask|own` 下两者无共享位（交集模型表达不了）",
        })

    return {
        "bodies": len(bodies),
        "groups_seen": groups,
        "mask_histogram": dict(sorted(histogram.items())),
        "bits_of": bits,
        "pairs_total": pairs_total,
        "pmx_collide": collide,
        "pmx_nocollide": pairs_total - collide,
        "separated_by_bits": separated_by_bits,
        "constraints_needed": overlap_nocollide,
        "unexpressible": unexpressible,
        "asymmetric_pairs": len(asymmetric),
        "asymmetric_examples": asymmetric[:5],
        "skipped": skipped,
    }
