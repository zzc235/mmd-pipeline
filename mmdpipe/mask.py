"""PMX 碰撞掩码的读回与判据（纯 Python，不 import bpy）。

**先钉语义，否则全部读数会整体反号。** 证据链三步：

1. `mmd_tools/core/pmx/importer.py:491`
   `collision_group_mask=[rigid.collision_group_mask & (1 << i) == 0 for i in range(16)]`
   ⇒ Blender 属性 `mmd_rigid.collision_group_mask[i]` 为 **True 表示"与该组碰"**
   （PMX 原始位是「非衝突グループフラグ」：**原始位置位 = 不碰**）；
2. `mmd_tools/core/pmx/exporter.py:996-999` 反向写回（属性 False → 原始位置 1），往返一致；
3. **名字实测**（`卡芙卡3.0_fixH.pmx`）：组 5 的 48 个刚体全是 `HairA1_JNT…`（头发），
   mask `0xffdf` = 除 bit5 外全置位。按「置位 = 不碰」读：头发**只与头发碰**（自碰撞），
   这是标准 MMD 设置；按反读会得到「头发与头发不碰、与身体全碰」——头发刚体与头/身体在
   静止姿态就重叠，那样必然炸开。组 4 是 `zxk__*`（裙子，mask `0xff2f` = 除 {4,6,7} 外
   全置位）同理：只与裙/下摆碰。

本模块一律读**属性**（True = 碰），不读 PMX 原始位。正确语义下的实测数字
（`卡芙卡3.0_fixH.pmx`，145 个刚体 / 10 440 对）：

* 该碰 **3073** / 不该碰 **7367**（不该碰占 70.6%，与 1号 在交付场景上测到的 77.2% 同量级）；
* **单向**掩码（一侧允许、另一侧不允许）**1462** 对——这是"不能用归属位表达"的那批；
* 位编码 `mask | own` 下：**该碰却无共享位 = 0**（见下方证明），不该碰里 5818 对靠位自己
  就分开，**1549** 对需要补 `DISABLE_COLLISIONS`。

为什么不对 `rigid_body.collision_collections` 只写掩码：Blender 那 16 位是**归属 + 判交**
（两个物体的集合有交集才碰），天生对称。只写 `mask` 时，经典情形「身体组 0（掩码只开
bit1）× 组 1（掩码只开 bit0）」两边都不含自己组的位、交集为空——明明该碰却不会碰。
"""
from __future__ import annotations

GROUP_COUNT = 16          # PMX 的组号 / 非衝突フラグ只有 16 位
# Blender 的 `rigid_body.collision_collections` 是 **20 位**（实测：写 16 项会抛
# `ValueError: sequences of dimension 0 should contain 20 items, not 16`）。
# 16..19 我们自己永远置 False——它们不对应任何 PMX 组。
COLLECTION_COUNT = 20
ALL_GROUPS = (1 << GROUP_COUNT) - 1
ALL_COLLECTIONS = (1 << COLLECTION_COUNT) - 1
NCC_MMD_TYPE = "NON_COLLISION_CONSTRAINT"

ENCODING_NOTE = (
    "collision_collections = mask | (1 << own_group)；假碰（共享位但 PMX 说该不碰）"
    "由逐对 DISABLE_COLLISIONS 约束分开。不用「交集近似」代替约束——那会静默停碰该碰的对。"
)

# Blender 侧语义**实测**（`tests_bpy/mask_semantics_probe.py`，Blender 5.2.2 LTS，2026-11-16）。
# spec §2.5 要求先测再实现，所以这里存的是读数，不是理解。
MEASURED_SEMANTICS = {
    "probe": "tests_bpy/mask_semantics_probe.py",
    "blender": "5.2.2 LTS",
    "measured_at": "2026-11-16",
    "status": "MEASURED",
    # 三个刚体，跑 40 帧，重力下落：
    "shared_bit_blocks": True,        # D1(bit1) 落到 G1(bit1) 上，停在 z=1.000
    "disjoint_bits_pass": True,       # D2(bit1) 穿过 G2(bit2)，掉到 z=-9.704
    "one_side_bit_is_enough": True,   # D(bit1+bit2) 对 G1(bit1)/G2(bit2) 都被挡住（都停在 1.000）
    "rna_description": "Collision collections rigid body belongs to",
    "zeros_and_all_differ": True,     # 全 0 位 vs 全 1 位的快照不同（单元级判据）
    "conclusion": "collision_collections 是「共享某一位即碰撞」的对称语义；"
                  "只有 20 位（PMX 用 16），写 16 项会抛 ValueError。"
                  "PMX 的非对称掩码无法用位表达，只能靠逐对 DISABLE_COLLISIONS 约束",
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
    """Bullet 侧真实生效的 20 位（`rigid_body.collision_collections`）。

    这不是 PMX 掩码的翻版，是**另一个机制**（归属+判交，天生对称）。读回来的用处是
    说清"现在的碰撞限制到底靠哪一边"：读不到就按全 1 处理（同上，不可知 ≠ 不碰）。
    """
    body = getattr(obj, "rigid_body", None)
    raw = getattr(body, "collision_collections", None)
    if raw is None:
        return ALL_COLLECTIONS
    value = 0
    for n, bit in enumerate(raw):
        if bit:
            value |= 1 << n
    return value


def collection_flags(bits: int) -> list:
    """把 16 位整数摊成 Blender 要的 **20 项**布尔（16..19 恒 False）。"""
    return [bool((bits >> n) & 1) for n in range(COLLECTION_COUNT)]


# 建约束的默认上限（spec §4.4 的"数量可核"要一个具体数，也要一个不许无声跑飞的闸）。
# 实测代价（2026-11-16，`H_nobake.blend` / `J_baked.blend`，323 个刚体、12 个依赖环）：
# 逐对象 `bpy.ops.rigidbody.constraint_add()` 每次都触发整场景 depsgraph 求值，
# 1500 条级别 10 分钟跑不完、日志涨到 459 MB。所以**大场景必须走建场那条路**
# （`stage_build` 里刚体还没烘焙、没有缓存要重算），事后 apply 只适合小场景/无缓存场景。
#
# 上限为什么从 4000 提到 20000（2026-11-16 15:1x，交付路径上的硬边界）：
#   全尺寸交付场景要补的对数 = `plans()["constraints_needed"]` 10 111 − 已经挡对的 1 813
#   = **8 298**。旧的 4000 会让每一次全尺寸建场**必然** `constraints_capped`，于是
#   `verdict` 永远是 PARTIAL——"通道接上了"这件事在交付尺度上根本判不出来，而那不是
#   物理结论，是我自己写死的闸。20000 留 2.4 倍余量，同时仍然是一个"不许无声跑飞"的闸。
#   配套：`mmdpipe/stage.py` 的建约束改成复制已有 ncc（不走逐条 ops），代价从
#   60 ms–0.48 s/条降到毫秒级，否则 8298 条按旧路要 8 分钟到 1 小时。
DEFAULT_MAX_CONSTRAINTS = 20000


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


def exception_rows(bodies, exceptions) -> list:
    """作用域外的刚体在"共享位即碰"语义下**仍会与多少作用域内刚体互撞**。

    比的是**通道打完之后的**位（`collision_bits()` = `mask | own`），不是当前场景里的位：
    要回答的是"接上之后还剩多少"，不是"接之前有多少"（接之前大家都是 `{0001}`，
    数出来会是全部，那个数没有信息量）。

    为什么要这张表而不是"跳过就完了"：`地面_物理` 这种对象有 `rigid_body` + `mmd_rigid`，
    但 `mmd_type` 不是 `RIGID_BODY`（不在通道作用域），而它的掩码是 0。跳过它意味着一个
    声明"谁都不碰"的地面在接上之后**仍与 62 个刚体互撞**——这个数必须出现在报告里
    （`D-20261116-133`：结论要写在纸上，不是靠跳过）。
    """
    rows = []
    for obj in exceptions:
        bits = collections_of(obj)
        still = sum(1 for other in bodies if bits & collision_bits(other))
        rows.append({"name": obj.name,
                     "group": group_of(obj),
                     "mask": mask_bits(obj),
                     "collections": bits,
                     "still_collides_with": still,
                     "reason": "不在通道作用域（mmd_type 不是 RIGID_BODY），"
                               "掩码对 PMX 刚体之外的对手方不适用"})
    return rows


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

    # 两个**归零量**（D0 `D-20261116-142`）：判"通道接上了"看这两个为 0，
    # **不看**约束总数。`released` 会把挡错的放开（总数降）、`added` 会补假碰（总数升），
    # 总数不变恰恰可能是"又放又补"。这两个数各有 0 与"没测到"的区别：
    # `None` = 压根没有这类对（无从谈起），`0` = 有这类对、但一条都不剩。
    plan = plans(bodies, blocked)
    already_needed = sum(1 for a, b in plan["constraints_needed"]
                         if pair_key(a, b) in blocked)
    blocked_and_should_collide = len(plan["release_pairs"])
    still_colliding = len(plan["constraints_needed"]) - already_needed

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
                                       if collections_of(o) != ALL_COLLECTIONS),
        # 两个归零量：不在作用域/规则不适用时给 `None`，不给 0（0 是"测了，是零"）
        "blocked_and_should_collide": (blocked_and_should_collide
                                       if plan["pmx_collide"] else None),
        "nocollide_pairs_still_colliding": (still_colliding
                                            if plan["pmx_nocollide"] else None),
        "unexpressible_pairs": len(plan["unexpressible"]),
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
# 实测（`卡芙卡3.0_fixH.pmx`，145 刚体 / 10440 对，按属性语义 True=碰）：
# 该碰 3073 / 不该碰 7367，「该碰却无共享位」= **0**，与上面的证明一致；
# 不该碰里 5818 对靠位自己分开，1549 对需要补约束。
#
# 代价是**假碰**：两个都「与第 5 组碰」但彼此不该碰的刚体，会共享 bit5。这类对由
# `DISABLE_COLLISIONS` 约束补（`plans()` 里算出来的 `constraints_added`），所以最终
# 语义等价，代价是约束数量。**不许用「交集模型近似」代替约束**：那会把该碰的成对
# 静默停碰（本文件顶上那段 1462 个单向对就是证据）。

def collision_bits(obj) -> int:
    """Blender 侧应当写入的位：`mask | (1 << own_group)`（spec §3 的映射）。"""
    return mask_bits(obj) | (1 << group_of(obj))


def pmx_collides(group_a: int, mask_a: int, group_b: int, mask_b: int) -> bool:
    """PMX 语义的一对判定：**两边都要允许**。"""
    return bool((mask_a >> group_b) & 1) and bool((mask_b >> group_a) & 1)


def plans(rigids, blocked=None) -> dict:
    """纯逻辑：算出该写哪些位、该补/该放哪些约束、哪些表达不了（不发 bpy 调用）。

    `blocked`：场景里**已经存在**的 `disable_collisions` 对（来自 `disabled_pairs()`）。
    给了它，就能算出 `release_pairs`——那些**挡错了**的对。

    为什么需要"放"：`mmd_tools` 的 `buildRigids()` 用 `if not ignore: continue` 读属性，
    但属性 True 表示"与该组**碰**"（证据链见模块说明），于是它给**本该互碰**的对建了
    DISABLE_COLLISIONS。实测 `J_baked.blend`：4009 条里有 **2196 条挡错了**
    （例：`136_下擺_6_11 × 137_下擺_6_12` 被挡住，而两条都在下擺组、PMX 说该碰）。
    只补不放，通道"接上"了也仍然会静默停碰 2196 对。
    """
    bodies = list(rigids)
    facts = [(o.name, group_of(o), mask_bits(o)) for o in bodies]
    bits = {name: (bits_value | (1 << group)) for name, group, bits_value in facts}
    blocked = set() if blocked is None else set(blocked)

    pairs_total = len(bodies) * (len(bodies) - 1) // 2
    collide = 0
    separated_by_bits = 0
    overlap_nocollide = []
    unexpressible = []
    collide_pairs = set()
    asymmetric = []
    for i in range(len(facts)):
        for j in range(i + 1, len(facts)):
            name_a, group_a, mask_a = facts[i]
            name_b, group_b, mask_b = facts[j]
            want = pmx_collides(group_a, mask_a, group_b, mask_b)
            overlap = bool(bits[name_a] & bits[name_b])
            if want:
                collide += 1
                collide_pairs.add((name_a, name_b))
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

    release = sorted(blocked & collide_pairs)
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
        "release_pairs": release,
        "blocked_before": len(blocked),
        "unexpressible": unexpressible,
        "asymmetric_pairs": len(asymmetric),
        "asymmetric_examples": asymmetric[:5],
        "skipped": skipped,
    }
