# -*- coding: utf-8 -*-
"""PMX 碰撞掩码读回（`mmdpipe/mask.py`）的判据测试。

这一组的重点不是"算得对"，而是**失败与不一致不同形**：

* 没有声明任何排除 ≠ 覆盖率 100%（`coverage` 必须是 `None`）；
* 一个文件都没读出来 ≠ 掩码很严格（读不到按"与所有组碰"处理）；
* `disable_collisions=False` 的约束不算挡掉了（那是"看起来很严格"的假绿）。
"""
import unittest

from mmdpipe import mask as mask_mod


class FakeRigid:
    def __init__(self, group, bits, name=None):
        self.group = group
        self.bits = bits
        self.name = name

    @property
    def mmd_rigid(self):
        return self

    @property
    def collision_group_mask(self):
        return [bool(self.bits >> n & 1) for n in range(mask_mod.GROUP_COUNT)]

    @property
    def collision_group_number(self):
        return self.group


class Obj:
    """一个刚体对象：名字 + 所属组 + 掩码位图 + Bullet 侧集合位。"""

    def __init__(self, name, group, bits, *, location=(0.0, 0.0, 0.0),
                 collections=mask_mod.ALL_COLLECTIONS):
        self.name = name
        self.location = _Vec(location)
        self.mmd_rigid = FakeRigid(group, bits, name)
        self.rigid_body = type("RB", (), {"collision_collections":
                                          [bool(collections >> n & 1)
                                           for n in range(mask_mod.COLLECTION_COUNT)]})()


class _Vec:
    def __init__(self, t):
        self.t = tuple(t)

    def __sub__(self, other):
        return _Vec(tuple(a - b for a, b in zip(self.t, other.t)))

    @property
    def length(self):
        return sum(x * x for x in self.t) ** 0.5


class NCC:
    """ncc 空物体：带一个 DISABLE_COLLISIONS 的 GENERIC 约束。"""

    def __init__(self, a, b, disable=True):
        self.name = "ncc"
        self.rigid_body_constraint = type(
            "RBC", (), {"disable_collisions": disable, "object1": a, "object2": b})()


def bits_for(groups, allowed=None):
    """按"只与 allowed 里的组碰"造掩码位。"""
    allowed = groups if allowed is None else allowed
    value = 0
    for g in allowed:
        value |= 1 << g
    return value


class TestMaskBits(unittest.TestCase):
    def test_bits_read_from_bool_vector(self):
        o = Obj("a", 0, 0b0000_0000_0000_0011)
        self.assertEqual(mask_mod.mask_bits(o), 3)
        self.assertEqual(mask_mod.group_of(o), 0)

    def test_unreadable_mask_is_all_groups_not_empty(self):
        """读不到掩码时必须是"与所有组碰"——不可知不能表现成"忽略一切"。"""
        o = Obj("a", 0, 0)
        o.mmd_rigid = object()               # 没有 collision_group_mask 属性
        self.assertEqual(mask_mod.mask_bits(o), mask_mod.ALL_GROUPS)

    def test_collections_read_back_separately(self):
        o = Obj("a", 0, 0xFFFF, collections=0b1010)
        self.assertEqual(mask_mod.collections_of(o), 0b1010)
        self.assertNotEqual(mask_mod.collections_of(o), mask_mod.mask_bits(o))


class TestDeclarations(unittest.TestCase):
    def test_ignored_group_becomes_declared_pairs(self):
        # A 在第 0 组、忽略第 1 组；B、C 在第 1 组；D 在第 2 组（没人忽略它）
        a = Obj("A", 0, bits_for([0, 2]))
        b = Obj("B", 1, bits_for([0, 1, 2]))
        c = Obj("C", 1, bits_for([0, 1, 2]))
        d = Obj("D", 2, bits_for([0, 1, 2]))
        decl = mask_mod.mask_declarations([a, b, c, d])
        self.assertEqual(decl["declared_pairs"], {("A", "B"), ("A", "C")})
        # declarations 数的是「(刚体, 组) 忽略」**声明条数**，不是展开后的对数：
        # A 忽略组 1 是一次声明，覆盖 B、C 两个刚体。
        self.assertEqual(decl["declarations"], 1)
        self.assertNotIn(("A", "D"), decl["declared_pairs"])

    def test_pair_is_declared_if_either_side_ignores(self):
        a = Obj("A", 0, bits_for([0]))                 # A 忽略组 1
        b = Obj("B", 1, bits_for([0, 1]))              # B 不忽略组 0
        decl = mask_mod.mask_declarations([a, b])
        self.assertEqual(decl["declared_pairs"], {("A", "B")})
        self.assertEqual(decl["one_sided"], 1)          # 单向：不能用集合位表达

    def test_symmetric_ignore_is_not_one_sided(self):
        a = Obj("A", 0, bits_for([0]))
        b = Obj("B", 1, bits_for([1]))
        decl = mask_mod.mask_declarations([a, b])
        self.assertEqual(decl["declared_pairs"], {("A", "B")})
        self.assertEqual(decl["one_sided"], 0)

    def test_empty_group_is_not_counted(self):
        """忽略一个空组没有意义，不能算成"声明了很多对"。"""
        a = Obj("A", 0, bits_for([]))                  # 忽略所有组
        decl = mask_mod.mask_declarations([a])
        self.assertEqual(decl["declared_pairs"], set())
        self.assertEqual(decl["declarations"], 0)
        self.assertEqual(decl["all_off"], 1)


class TestCoverage(unittest.TestCase):
    def setUp(self):
        self.a = Obj("A", 0, bits_for([0]))
        self.b = Obj("B", 1, bits_for([1]))
        self.rigids = [self.a, self.b]

    def test_no_constraint_means_zero_coverage(self):
        rep = mask_mod.mask_report(self.rigids, [self.a, self.b])
        self.assertEqual(rep["declared_pairs"], 1)
        self.assertEqual(rep["blocked_pairs"], 0)
        self.assertEqual(rep["coverage"], 0.0)
        self.assertEqual(rep["uncovered_pairs"], 1)

    def test_one_sided_ncc_covers_pair(self):
        ncc = NCC(self.a, self.b)
        rep = mask_mod.mask_report(self.rigids, [self.a, self.b, ncc])
        self.assertEqual(rep["blocked_pairs"], 1)
        self.assertEqual(rep["coverage"], 1.0)
        self.assertEqual(rep["examples"], [])

    def test_disable_false_is_not_coverage(self):
        """`disable_collisions=False` 的约束不起过滤作用——算成挡掉了就是假绿。"""
        ncc = NCC(self.a, self.b, disable=False)
        rep = mask_mod.mask_report(self.rigids, [self.a, self.b, ncc])
        self.assertEqual(rep["blocked_pairs"], 0)
        self.assertEqual(rep["coverage"], 0.0)

    def test_no_declaration_gives_none_not_one(self):
        """全 1 掩码（与所有组碰）覆盖必须是 `None`，不是 1.0。"""
        a = Obj("A", 0, mask_mod.ALL_GROUPS)
        b = Obj("B", 1, mask_mod.ALL_GROUPS)
        rep = mask_mod.mask_report([a, b], [a, b])
        self.assertEqual(rep["declared_pairs"], 0)
        self.assertIsNone(rep["coverage"])
        self.assertEqual(rep["all_on_bodies"], 2)

    def test_zero_mask_and_all_mask_give_different_reports(self):
        """应当被拒的输入：全 0 与全 1 掩码必须得出**不同**的读回。

        若两种都返回同一份报告（例如都 coverage=None、都 0 对），说明读回根本没看见掩码。
        """
        off = [Obj("A", 0, 0), Obj("B", 1, 0)]
        on = [Obj("A", 0, mask_mod.ALL_GROUPS), Obj("B", 1, mask_mod.ALL_GROUPS)]
        rep_off = mask_mod.mask_report(off, off)
        rep_on = mask_mod.mask_report(on, on)
        self.assertNotEqual(rep_off, rep_on)
        self.assertEqual(rep_off["all_off_bodies"], 2)
        self.assertEqual(rep_off["all_on_bodies"], 0)
        self.assertEqual(rep_on["all_on_bodies"], 2)
        self.assertEqual(rep_on["all_off_bodies"], 0)
        # 全 0：互相忽略 → 一对被声明；全 1：什么都不排除 → 无声明
        self.assertEqual(rep_off["declared_pairs"], 1)
        self.assertEqual(rep_on["declared_pairs"], 0)
        self.assertEqual(rep_off["coverage"], 0.0)
        self.assertIsNone(rep_on["coverage"])

    def test_rows_read_back_per_body(self):
        rep = mask_mod.mask_report(self.rigids, [self.a, self.b])
        rows = {r["name"]: r for r in rep["rows"]}
        self.assertEqual(rows["A"]["mask"], bits_for([0]))
        self.assertEqual(rows["A"]["ignored_groups"], [1] * 0 + list(range(1, 16)))
        self.assertEqual(rows["A"]["declared_pairs"], 1)
        self.assertEqual(rows["A"]["blocked_pairs"], 0)
        self.assertEqual(rep["collections_non_default"], 0)   # 默认全 1，没按掩码设位

    def test_examples_carry_distance(self):
        self.a.location = _Vec((0.0, 0.0, 0.0))
        self.b.location = _Vec((1.5, 2.0, 0.0))
        self.b.location = _Vec((0.0, 0.0, 0.0))
        far = Obj("F", 1, bits_for([1]))
        far.location = _Vec((3.0, 4.0, 0.0))
        # A 忽略组 1 → 与 B/F 都声明；只挡 B，F 留在 examples 里
        ncc = NCC(self.a, self.b)
        rep = mask_mod.mask_report([self.a, self.b, far], [self.a, self.b, far, ncc])
        self.assertEqual(rep["uncovered_pairs"], 1)
        self.assertEqual(rep["examples"][0]["b"], "F")
        self.assertEqual(rep["examples"][0]["distance"], 5.0)


class TestPlans(unittest.TestCase):
    """`plans()`：位编码 + 该补哪些约束 + 表达不了的对（spec §3/§4 的纯逻辑部分）。"""

    def test_encoding_includes_own_group_bit(self):
        # 组 0、掩码只有 bit1 → 写进 Blender 的位必须含自己组的 bit0
        a = Obj("A", 0, bits_for([1]))
        plan = mask_mod.plans([a])
        self.assertEqual(plan["bits_of"]["A"], bits_for([0, 1]))

    def test_pmx_collide_pairs_are_never_unexpressible(self):
        """可证性质：PMX 该碰的对，`mask|own` 下必然共享某一位。

        经典情形：身体组 0（掩码只开 bit1）× 组 1（掩码只开 bit0）——两边都不含自己组
        的位，若只写 mask 交集为空、明明该碰却不会碰；加上自己组就共享 bit0/bit1。
        """
        a = Obj("A", 0, bits_for([1]))
        b = Obj("B", 1, bits_for([0]))
        self.assertTrue(mask_mod.pmx_collides(0, bits_for([1]), 1, bits_for([0])))
        plan = mask_mod.plans([a, b])
        self.assertEqual(plan["pmx_collide"], 1)
        self.assertEqual(plan["unexpressible"], [])
        self.assertEqual(plan["skipped"], [])

    def test_same_group_shares_own_bit(self):
        a = Obj("A", 3, bits_for([3]))
        b = Obj("B", 3, bits_for([3]))
        plan = mask_mod.plans([a, b])
        self.assertTrue(mask_mod.pmx_collides(3, bits_for([3]), 3, bits_for([3])))
        self.assertEqual(plan["unexpressible"], [])

    def test_false_positive_pairs_get_constraints(self):
        """两个都「与第 5 组碰」但彼此不该碰 → 共享 bit5，必须补约束。"""
        a = Obj("A", 0, bits_for([5]))          # 组 0，只与组 5 碰
        b = Obj("B", 9, bits_for([5]))          # 组 9，只与组 5 碰
        self.assertFalse(mask_mod.pmx_collides(0, bits_for([5]), 9, bits_for([5])))
        plan = mask_mod.plans([a, b])
        self.assertEqual(plan["pmx_nocollide"], 1)
        self.assertEqual(plan["constraints_needed"], [("A", "B")])
        self.assertEqual(plan["separated_by_bits"], 0)

    def test_disjoint_nocollide_needs_no_constraint(self):
        a = Obj("A", 0, bits_for([0]))          # 组 0，只与组 0 碰
        b = Obj("B", 7, bits_for([7]))          # 组 7，只与组 7 碰
        plan = mask_mod.plans([a, b])
        self.assertEqual(plan["constraints_needed"], [])
        self.assertEqual(plan["separated_by_bits"], 1)

    def test_asymmetric_pair_is_detected_and_still_exact(self):
        """非对称掩码（一侧允许、另一侧不允许）：必须被报出来，而且**照样能精确处理**。"""
        a = Obj("A", 0, bits_for([1]))          # 允许组 1
        b = Obj("B", 1, bits_for([1]))          # 只允许组 1（即不允许组 0）
        self.assertFalse(mask_mod.pmx_collides(0, bits_for([1]), 1, bits_for([1])))
        plan = mask_mod.plans([a, b])
        self.assertEqual(plan["asymmetric_pairs"], 1)
        # 精确处理靠约束（不是"静默近似"）：这一对被补上 DISABLE_COLLISIONS
        self.assertEqual(plan["constraints_needed"], [("A", "B")])
        # 所以 skipped 为空——没有东西被跳过，这是与 spec §4.3 字面要求的差异，已在正文说明
        self.assertEqual(plan["skipped"], [])
        self.assertEqual(plan["unexpressible"], [])

    def test_empty_scene_is_zero_not_error(self):
        plan = mask_mod.plans([])
        self.assertEqual(plan["bodies"], 0)
        self.assertEqual(plan["pairs_total"], 0)
        self.assertEqual(plan["constraints_needed"], [])
        self.assertEqual(plan["skipped"], [])

    def test_counts_are_numbers_not_booleans(self):
        """spec §4.4：数量必须可核，不能是布尔。"""
        a = Obj("A", 0, bits_for([5]))
        b = Obj("B", 9, bits_for([5]))
        plan = mask_mod.plans([a, b])
        for key in ("bodies", "pairs_total", "pmx_collide", "pmx_nocollide",
                    "separated_by_bits", "asymmetric_pairs"):
            self.assertIsInstance(plan[key], int, key)

    def test_all_zero_and_all_one_masks_differ(self):
        """单元级判据（spec §4.1）：全 0 与全 1 掩码必须给出不同的位。"""
        off = [Obj("A", 2, 0), Obj("B", 3, 0)]
        on = [Obj("A", 2, mask_mod.ALL_GROUPS), Obj("B", 3, mask_mod.ALL_GROUPS)]
        plan_off = mask_mod.plans(off)
        plan_on = mask_mod.plans(on)
        self.assertNotEqual(plan_off["bits_of"]["A"], plan_on["bits_of"]["A"])
        self.assertEqual(plan_off["bits_of"]["A"], bits_for([2]))      # 只剩自己组
        self.assertEqual(plan_on["bits_of"]["A"], mask_mod.ALL_GROUPS)
        self.assertNotEqual(plan_off["mask_histogram"], plan_on["mask_histogram"])


class TestExceptionRows(unittest.TestCase):
    """作用域外的刚体单列一行（`D-20261116-133`：跳过要写在纸上，不是靠跳过）。"""

    def test_mask_zero_exception_still_collides_with_wired_bodies(self):
        """`地面_物理` 那种对象：掩码 0、不在作用域，接上之后仍与 N 个刚体互撞。

        比的是**接上之后**的位（`mask|own`），不是当前的 `{0001}`——后者数出来是全部，
        没有信息量。
        """
        # 作用域内：三个刚体，各自「只碰自己组 + 自己组位」
        a = Obj("A", 0, bits_for([0]))
        b = Obj("B", 1, bits_for([1]))
        c = Obj("C", 0, bits_for([0, 1]))
        # 作用域外：掩码 0（谁都不碰），当前位仍是默认的 bit0
        ground = Obj("地面_物理", 1, 0, collections=1)
        rows = mask_mod.exception_rows([a, b, c], [ground])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["name"], "地面_物理")
        self.assertEqual(row["mask"], 0)
        self.assertEqual(row["group"], 1)
        # 接上之后：A = {0}, B = {1,1}={1}, C = {0,1}；地面 = {0}
        # 与 A({0}) 共享 → 碰；与 B({1}) 不共享 → 不碰；与 C({0,1}) 共享 → 碰
        self.assertEqual(row["still_collides_with"], 2)
        self.assertTrue(row["reason"])

    def test_no_exception_gives_empty_list(self):
        a = Obj("A", 0, bits_for([0]))
        self.assertEqual(mask_mod.exception_rows([a], []), [])


class TestTwoZeroQuantities(unittest.TestCase):
    """判「通道接上了」看**两个归零量**，不看约束总数（D0 `D-20261116-142`）。

    `released` 降、`added` 升，总数不变恰恰可能是"又放又补"。所以要有两个各自能归零、
    且能把"没测到"与"测到 0"分开的读数。
    """

    def test_wrong_block_counts_in_blocked_and_should_collide(self):
        # A×B 该碰（同组共享 own 位），却被一条 DISABLE_COLLISIONS 挡住 ⇒ 挡错 1 对
        a = Obj("A", 0, bits_for([0]))
        b = Obj("B", 0, bits_for([0]))
        report = mask_mod.mask_report([a, b], [a, b, NCC(a, b)])
        self.assertEqual(report["blocked_and_should_collide"], 1)

    def test_false_positive_pair_is_counted_then_cleared_by_constraint(self):
        # X 允许组 3、Y 只允许组 3 ⇒ PMX 说不碰，但位在 bit3 上重叠（假碰）
        x = Obj("X", 0, bits_for([0, 3]))
        y = Obj("Y", 3, bits_for([3]))
        before = mask_mod.mask_report([x, y], [x, y])
        self.assertEqual(before["nocollide_pairs_still_colliding"], 1)
        # 这一对里没有任何「该碰」的对 ⇒ 那一栏是 None（无从谈起），不是 0
        self.assertIsNone(before["blocked_and_should_collide"])
        after = mask_mod.mask_report([x, y], [x, y, NCC(x, y)])
        self.assertEqual(after["nocollide_pairs_still_colliding"], 0)

    def test_absent_kind_is_none_not_zero(self):
        """"没有这类对"（None）与"有、但一条不剩"（0）不许同形。"""
        a = Obj("A", 0, bits_for([0]))
        report = mask_mod.mask_report([a], [a])
        self.assertIsNone(report["blocked_and_should_collide"])
        self.assertIsNone(report["nocollide_pairs_still_colliding"])

    def test_both_zero_on_a_clean_wired_scene(self):
        # X×Z 该碰（同组、双向允许）、X×Y 是假碰（用约束分开）、Y×Z 位本来就分开
        x = Obj("X", 0, bits_for([0, 3]))
        y = Obj("Y", 3, bits_for([3]))
        z = Obj("Z", 0, bits_for([0]))
        report = mask_mod.mask_report([x, y, z], [x, y, z, NCC(x, y)])
        self.assertGreater(report["rigids"], 0)
        self.assertEqual(report["blocked_and_should_collide"], 0)
        self.assertEqual(report["nocollide_pairs_still_colliding"], 0)
        self.assertEqual(report["unexpressible_pairs"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
