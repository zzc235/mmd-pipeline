# -*- coding: utf-8 -*-
"""`stage.apply_collision_masks()` 的接线测试（假 `bpy`，不需要 Blender）。

这一组盯的是**「接上了」和「没接全」不许同形**：

* `verdict=PARTIAL` 必须带 `verdict_reasons`，否则 cap / 表达不了 / 回读不一致 / 跳过
  在读数的人眼里长得一模一样；
* 记账恒等式 `added + already == needed` 一旦被跳过或 cap 打破，必须自己变红；
* 上限**由 plan 推出**，`DEFAULT_MAX_CONSTRAINTS` 只在需求超量级时才咬（护栏，不是预算）；
* 建约束默认走「复制已有 ncc」，不走逐条 `bpy.ops`（后者每条触发全场景求值）。
"""
import copy as copy_mod
import sys
import types
import unittest

from mmdpipe import mask as mask_mod


# ---------------------------------------------------------------- 假 bpy

class FakeRBC:
    def __init__(self, disable_collisions=True):
        self.disable_collisions = disable_collisions
        self.enabled = True
        self.object1 = None
        self.object2 = None


class FakeRigid:
    def __init__(self, group, bits):
        self.collision_group_number = group
        self._bits = bits

    @property
    def collision_group_mask(self):
        return [bool(self._bits >> n & 1) for n in range(mask_mod.GROUP_COUNT)]


class FakeBody:
    def __init__(self, collections=mask_mod.ALL_COLLECTIONS):
        self.collision_collections = [bool(collections >> n & 1)
                                      for n in range(mask_mod.COLLECTION_COUNT)]


class FakeObj:
    def __init__(self, name, group=0, mask_bits=0, *, mmd_type="RIGID_BODY",
                 with_rigid_body=True):
        self.name = name
        self.mmd_type = mmd_type
        self.mmd_rigid = FakeRigid(group, mask_bits)
        self.rigid_body = FakeBody() if with_rigid_body else None
        self.rigid_body_constraint = None

    def copy(self):
        # Blender 的 `Object.copy()`：连 `rigid_body_constraint` 一起复制（模板路要用到）
        new = FakeObj(self.name, mmd_type=self.mmd_type,
                      with_rigid_body=self.rigid_body is not None)
        new.rigid_body = copy_mod.deepcopy(self.rigid_body)
        new.rigid_body_constraint = copy_mod.deepcopy(self.rigid_body_constraint)
        return new

    def select_set(self, value):
        pass


class FakeObjects(list):
    def __init__(self, *args):
        super().__init__(*args)
        # 名字 → 查不到（模拟"plan 里有这个名字，场景里取不到对象"这条跳过路径）
        self.hide_from_get = set()

    def get(self, name, default=None):
        if name in self.hide_from_get:
            return None
        for obj in self:
            if obj.name == name:
                return obj
        return default

    def clear(self):
        # 每个用例都从干净场景开始：`hide_from_get` 也要一起清，否则上一个用例的
        # "故意查不到" 会漏到下一个用例里，把失败伪装成通过。
        self.hide_from_get.clear()
        list.clear(self)

    def new(self, name, data=None):
        obj = FakeObj(name, with_rigid_body=False)
        obj.mmd_type = "NONE"
        return obj

    def remove(self, obj, do_unlink=True):
        if obj in self:
            list.remove(self, obj)


class FakeScene(dict):
    """场景：既是 dict（`scene["mask_wired"] = ...`），又带 `collection.objects.link`。"""

    def __init__(self, linker):
        super().__init__()
        self.collection = types.SimpleNamespace(objects=linker)


class FakeBpy(types.ModuleType):
    """够 `stage.py` 里通道那条路用的最小 `bpy`。"""

    def __init__(self):
        super().__init__("bpy")
        self.objects = FakeObjects()
        self.ops_calls = []
        self.data = types.SimpleNamespace(objects=self.objects)
        self.scene = FakeScene(_Linker(self.objects))
        self.view_layer = types.SimpleNamespace(
            objects=types.SimpleNamespace(active=None))
        self.context = types.SimpleNamespace(
            scene=self.scene, view_layer=self.view_layer)
        outer = self
        self.ops = types.SimpleNamespace(
            rigidbody=types.SimpleNamespace(constraint_add=_constraint_add(outer)))


class _Linker:
    def __init__(self, objects):
        self._objects = objects

    def link(self, obj):
        if obj not in self._objects:
            self._objects.append(obj)


def _constraint_add(fake):
    def _add(*, type="GENERIC"):
        fake.ops_calls.append(type)
        active = fake.view_layer.objects.active
        if active is None:
            raise RuntimeError("constraint_add 需要活动对象")
        active.rigid_body_constraint = FakeRBC(disable_collisions=False)
    return _add


def load_stage():
    """把假 `bpy`/`mathutils` 装进 `sys.modules` 再导入 `mmdpipe.stage`（已导入就复用）。"""
    if "mmdpipe.stage" in sys.modules:
        stage = sys.modules["mmdpipe.stage"]
        bpy = sys.modules["bpy"]
        if isinstance(bpy, FakeBpy):
            return stage, bpy
        del sys.modules["mmdpipe.stage"]
    if "mathutils" not in sys.modules:
        vec = types.ModuleType("mathutils")

        class Vector:
            def __init__(self, t=(0.0, 0.0, 0.0)):
                self.t = tuple(t)

            def __sub__(self, other):
                return Vector(tuple(a - b for a, b in zip(self.t, other.t)))

            @property
            def length(self):
                return sum(x * x for x in self.t) ** 0.5

        vec.Vector = Vector
        sys.modules["mathutils"] = vec
    bpy = FakeBpy()
    sys.modules["bpy"] = bpy
    import mmdpipe.stage as stage
    return stage, bpy


# ---------------------------------------------------------------- 构造场景

def wired_scene(bpy):
    """三个刚体，同时造出三种关系：

    * `x`（组 0，掩码允许组 3）与 `y`（组 3，掩码只允许组 3）**位重叠但 PMX 说不碰**
      （PMX 是「两边都允许」，y 不允许 x 的组）⇒ 必须补一条约束，这就是假碰；
    * `x` 与 `z`（组 0，掩码只允许组 0）**PMX 说该碰**，且同组共享 own 位 ⇒ 不用约束；
    * `y` 与 `z` 位不重叠 ⇒ 本来就分开，也不用约束。
    """
    bpy.objects.clear()
    bpy.ops_calls.clear()
    x = FakeObj("x", group=0, mask_bits=(1 << 0) | (1 << 3))
    y = FakeObj("y", group=3, mask_bits=1 << 3)
    z = FakeObj("z", group=0, mask_bits=1 << 0)
    for obj in (x, y, z):
        bpy.objects.append(obj)
    return [x, y, z]


def seed_template(bpy):
    """场景里放一条 mmd_tools 形状的 ncc，作为复制模板。"""
    ncc = FakeObj("ncc_seed", mmd_type=mask_mod.NCC_MMD_TYPE, with_rigid_body=False)
    ncc.rigid_body_constraint = FakeRBC(disable_collisions=True)
    bpy.objects.append(ncc)
    return ncc


class TestWiringMetrics(unittest.TestCase):
    def setUp(self):
        self.stage, self.bpy = load_stage()

    def test_auto_uses_template_copy_and_never_calls_ops(self):
        bodies = wired_scene(self.bpy)
        seed_template(self.bpy)
        result = self.stage.apply_collision_masks()
        self.assertEqual(result["constraint_creation"], "template_copy")
        self.assertEqual(self.bpy.ops_calls, [],
                         "复制路径还在调 bpy.ops（每条都会触发全场景求值）")
        self.assertEqual(result["verdict"], "WIRED")
        self.assertEqual(result["verdict_reasons"], [])
        self.assertTrue(result["constraints_identity"])
        self.assertEqual(result["constraints_added"], result["constraints_to_add"])
        # 位写进去了，且是 mask|own
        for obj in bodies:
            group = mask_mod.group_of(obj)
            self.assertEqual(mask_mod.collections_of(obj),
                             mask_mod.mask_bits(obj) | (1 << group))

    def test_no_template_falls_back_to_ops_and_says_so(self):
        wired_scene(self.bpy)
        result = self.stage.apply_collision_masks()
        self.assertEqual(result["constraint_creation"], "ops")
        self.assertTrue(self.bpy.ops_calls, "没有模板却没走 ops，说明哪里错了")
        self.assertEqual(result["constraints_added"], len(self.bpy.ops_calls))

    def test_explicit_template_copy_without_template_raises(self):
        wired_scene(self.bpy)
        with self.assertRaises(RuntimeError):
            self.stage.apply_collision_masks(constraint_creation="template_copy")

    def test_bad_creation_mode_is_rejected(self):
        wired_scene(self.bpy)
        with self.assertRaises(ValueError):
            self.stage.apply_collision_masks(constraint_creation="copy")

    def test_missing_body_becomes_skipped_and_breaks_identity(self):
        wired_scene(self.bpy)
        seed_template(self.bpy)
        # 让 y 查不到（plan 里还有它，`bpy.data.objects.get()` 取不到）⇒ 那一对必须进 skipped
        self.bpy.objects.hide_from_get.add("y")
        result = self.stage.apply_collision_masks()
        self.assertEqual(result["constraints_needed"], 1)
        self.assertGreaterEqual(result["skipped_count"], 1)
        self.assertEqual(result["verdict"], "PARTIAL")
        self.assertIn("skipped", result["verdict_reasons"])
        self.assertFalse(result["constraints_identity"],
                         "跳过了一对，记账恒等式还成立 ⇒ 恒等式没在记账")

    def test_guardrail_bites_when_demand_exceeds_it(self):
        wired_scene(self.bpy)
        seed_template(self.bpy)
        original = mask_mod.DEFAULT_MAX_CONSTRAINTS
        mask_mod.DEFAULT_MAX_CONSTRAINTS = 0      # 故意把护栏压到"需求超量"
        try:
            result = self.stage.apply_collision_masks()
        finally:
            mask_mod.DEFAULT_MAX_CONSTRAINTS = original
        self.assertTrue(result["guardrail_hit"])
        self.assertTrue(result["constraints_capped"])
        self.assertEqual(result["verdict"], "PARTIAL")
        self.assertIn("guardrail_hit", result["verdict_reasons"])
        self.assertIn("constraints_capped", result["verdict_reasons"])
        self.assertEqual(result["constraints_added"], 0)
        self.assertEqual(result["skipped_count"], 1)

    def test_cap_comes_from_plan_so_delivery_scale_is_not_capped(self):
        """护栏默认值必须高于交付场景需求量级（U323 要补 8 298 条）。"""
        self.assertGreaterEqual(mask_mod.DEFAULT_MAX_CONSTRAINTS, 10111,
                                "护栏低于交付需求量级 ⇒ 每次全尺寸建场必然 capped")
        wired_scene(self.bpy)
        seed_template(self.bpy)
        result = self.stage.apply_collision_masks()          # 不传 max_constraints
        self.assertFalse(result["constraints_capped"])
        self.assertFalse(result["guardrail_hit"])

    def test_empty_scene_reports_empty_with_all_keys(self):
        self.bpy.objects.clear()
        result = self.stage.apply_collision_masks()
        self.assertEqual(result["verdict"], "EMPTY")
        self.assertEqual(result["verdict_reasons"], ["no_bodies"])
        for key in self.stage.MASK_WIRED_KEYS:
            self.assertIn(key, result, "EMPTY 分支少了 %s，stage_build 折 metrics 会 KeyError"
                          % key)

    def test_metric_keys_exist_on_normal_path(self):
        wired_scene(self.bpy)
        seed_template(self.bpy)
        result = self.stage.apply_collision_masks()
        for key in self.stage.MASK_WIRED_KEYS:
            self.assertIn(key, result)

    def test_same_scene_twice_is_idempotent(self):
        wired_scene(self.bpy)
        seed_template(self.bpy)
        first = self.stage.apply_collision_masks()
        second = self.stage.apply_collision_masks()
        self.assertGreater(first["constraints_added"], 0)
        self.assertEqual(second["constraints_added"], 0)
        self.assertEqual(second["constraints_already_blocked"],
                         first["constraints_needed"])


class TestStageMaskVerdict(unittest.TestCase):
    """`stage_mask()` 是 2号 的准入 ②、1号 的 S8 第三层共用的那支仪器（`D-145`）。"""

    def setUp(self):
        self.stage, self.bpy = load_stage()

    def test_wired_after_a_complete_apply(self):
        wired_scene(self.bpy)
        seed_template(self.bpy)
        self.stage.apply_collision_masks()
        report = self.stage.stage_mask()
        self.assertEqual(report["verdict"], "WIRED")
        self.assertEqual(report["verdict_reasons"], [])
        self.assertFalse(report["constraints_capped"])
        self.assertEqual(report["skipped_count"], 0)
        self.assertEqual(report["blocked_and_should_collide"], 0)
        self.assertEqual(report["nocollide_pairs_still_colliding"], 0)
        self.assertTrue(report["wired_record"])

    def test_no_build_record_is_never_wired(self):
        """别人手搭的场景没有建场记录 ⇒ 判词不许是 WIRED（"没记录"≠"没问题"）。"""
        wired_scene(self.bpy)
        seed_template(self.bpy)
        self.stage.apply_collision_masks()
        self.bpy.scene.clear()                     # 抹掉 scene["mask_wired"]
        report = self.stage.stage_mask()
        self.assertEqual(report["verdict"], "PARTIAL")
        self.assertIn("no_wired_record", report["verdict_reasons"])

    def test_capped_run_stays_partial_after_the_fact(self):
        wired_scene(self.bpy)
        seed_template(self.bpy)
        original = mask_mod.DEFAULT_MAX_CONSTRAINTS
        mask_mod.DEFAULT_MAX_CONSTRAINTS = 0
        try:
            self.stage.apply_collision_masks()
            report = self.stage.stage_mask()
        finally:
            mask_mod.DEFAULT_MAX_CONSTRAINTS = original
        self.assertEqual(report["verdict"], "PARTIAL")
        self.assertTrue(report["constraints_capped"])
        self.assertIn("constraints_capped", report["verdict_reasons"])

    def test_untouched_bits_are_partial(self):
        wired_scene(self.bpy)                      # 全是默认位（没跑通道）
        report = self.stage.stage_mask()
        self.assertEqual(report["verdict"], "PARTIAL")
        self.assertIn("bit_patterns_below_2", report["verdict_reasons"])

    def test_empty_scene_is_empty(self):
        self.bpy.objects.clear()
        report = self.stage.stage_mask()
        self.assertEqual(report["verdict"], "EMPTY")
        self.assertEqual(report["verdict_reasons"], ["no_bodies"])


if __name__ == "__main__":
    unittest.main()
