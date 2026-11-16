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
import inspect
import os
import sys
import types
import unittest

from coordination import preflight as preflight_mod
from mmdpipe import mask as mask_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


class TestMaskGate(unittest.TestCase):
    """`D-144③`：上限由 plan 推出 + 四条判据**逐条可红** + 建场前 fail-closed。

    四条判据（`WIRED / capped=false / skipped==[] / added+already==needed`）分成四个 bool
    给出，不许合成一个 `and`：合取式里一位写错，整体永远是绿的而读数的人看不出哪条坏。
    所以下面四个**红样本**分别只破坏一条，逐个判红。
    """

    def setUp(self):
        self.stage, self.bpy = load_stage()

    def _green(self):
        wired_scene(self.bpy)
        seed_template(self.bpy)
        self.bpy.ops_calls.clear()
        return self.stage.apply_collision_masks()

    # ------------------------------------------------------------ 绿样本

    def test_all_four_criteria_green_in_one_assertion(self):
        result = self._green()
        checks = self.stage.mask_wired_checks(result)
        self.assertEqual(sorted(checks), sorted(self.stage.MASK_WIRED_CRITERIA),
                         "判据清单和实现漂了：%r" % (checks,))
        self.assertEqual(
            {name for name, ok in checks.items() if not ok}, set(),
            "四条判据有红的：%r（判词理由 %r）"
            % ({name: ok for name, ok in checks.items() if not ok},
               result.get("verdict_reasons")))
        self.assertEqual(self.stage.mask_wired_missing(result), [])
        self.assertIsNone(self.stage.mask_gate_reason(result))

    # ------------------------------------------------------------ 四条红样本

    def test_each_criterion_can_turn_red_alone(self):
        """四条各红一次：每条都只该红它自己。"""
        base = self._green()
        mutations = {
            "verdict_wired": {"verdict": "PARTIAL"},
            "not_capped": {"constraints_capped": True},
            "no_skipped": {"skipped_count": 1},
            "added_plus_already_equals_needed":
                {"constraints_added": base["constraints_added"] + 1},
        }
        for name, patch in mutations.items():
            broken = dict(base)
            broken.update(patch)
            self.assertEqual(
                self.stage.mask_wired_missing(broken), [name],
                "破坏 %s（%r）之后红项不对：%r" % (name, patch,
                                            self.stage.mask_wired_missing(broken)))
            self.assertIn(name, self.stage.mask_gate_reason(broken))

    def test_skipped_list_also_breaks_the_skipped_criterion(self):
        broken = dict(self._green())
        broken["skipped_count"] = 0
        broken["skipped"] = [{"pair": ["a", "b"], "reason": "达到建约束上限"}]
        self.assertIn("no_skipped", self.stage.mask_wired_missing(broken))

    def test_missing_record_is_red_not_green(self):
        """没有建场记录的字段（旧场景/手搭场景）不许读成「没问题」。"""
        base = self._green()
        expected = {"constraints_capped": "not_capped", "skipped_count": "no_skipped"}
        for key, criterion in expected.items():
            broken = dict(base)
            broken.pop(key)
            self.assertIn(
                criterion, self.stage.mask_wired_missing(broken),
                "缺 %s 却判绿了：%r" % (key, self.stage.mask_wired_missing(broken)))

    def test_channel_off_is_not_gated(self):
        """通道没开（`wired is None`）不归这条闸管——但也绝不算「接好了」。"""
        self.assertIsNone(self.stage.mask_gate_reason(None))
        self.assertEqual(self.stage.mask_wired_missing(None),
                         list(self.stage.MASK_WIRED_CRITERIA),
                         "没读数时四条判据必须全是红的（不是「没跳过」）")

    # ------------------------------------------------------------ fail-closed 在调用点上

    def test_stage_build_really_calls_the_gate(self):
        """只测抽出来的纯函数 = 「测了没改的那份文件」（D-125 那类假绿）。

        所以还要证明它在**建场路径上**：`stage_build()` 调它、并且在任何烘焙动作之前
        `return`；`runner.record()` 对 BLOCK 停住（`--force` 之外）。
        """
        src = inspect.getsource(self.stage.stage_build)
        self.assertIn("mask_gate_reason(wired)", src,
                      "stage_build 没调用 mask_gate_reason —— 判据没接在建场路径上")
        gate_at = src.index("mask_gate_reason(wired)")
        # 旧写法是「源码里不许出现 bake」。`D-173` 给 `stage_build` 加了显式 `bake=` 参数之后，
        # 按词断言就不成立了——但它防的是同一件事：**烘焙必须发生在闸门之后**。改成按位置断言，
        # 顺带要求烘焙算子只在 `stage_bake()` 里出现（`stage_build` 不许自己调 ptcache）。
        self.assertNotIn("ptcache", src, "stage_build 自己调了烘焙算子：应该走 stage_bake()")
        first_bake = src.index("stage_bake(")
        self.assertGreater(first_bake, gate_at, "烘焙调用出现在掩码闸门之前")
        self.assertLess(first_bake, src.index("bake_gate_reason(record)"),
                        "`stage_bake` 的调用必须在判「烘得合不合格」之前")
        self.assertLess(gate_at, src.rindex("return res"),
                        "BLOCK 之后又往下走了（`return res` 不在闸门后面）")
        with open(os.path.join(ROOT, "mmdpipe", "runner.py"), encoding="utf-8") as fh:
            runner_src = fh.read()
        self.assertIn("if result.blocked:", runner_src)
        self.assertIn("return not result.blocked or args.force", runner_src,
                      "runner 没在 BLOCK 上停 ⇒ 建场红了还会继续烘焙")

    # ------------------------------------------------------------ preflight 读数同一个函数

    def test_preflight_cap_comes_from_the_same_function_as_the_build(self):
        """`cap` 必须与建场用的是同一个函数返回值，不许在请求 JSON 里手写。"""
        result = self._green()
        fields = self.stage.mask_preflight_fields(result)
        self.assertEqual(fields["needs"], result["constraints_to_add"])
        self.assertEqual(
            fields["cap"],
            self.stage.constraint_limit(result["constraints_needed"])[0],
            "预检的 cap 不是建场那个上限函数的返回值：%r" % (fields,))
        self.assertEqual(fields["skipped"], 0)
        request = {
            "provenance": {"stage": os.path.join(ROOT, "mmdpipe", "stage.py")},
            "lease": False,
            **fields,
        }
        outcome = preflight_mod.check(request, worktree=ROOT)
        self.assertEqual(outcome["state"], "READY",
                         "预热请求没过：%s" % (preflight_mod.render(outcome),))
        # 红样本：同一个需求，cap 手写成比 needs 小 ⇒ 开工前就拦（CAP_UNMET）
        shrunk = dict(request, cap=max(0, fields["needs"] - 1))
        blocked = preflight_mod.check(shrunk, worktree=ROOT)
        self.assertEqual(blocked["state"], "BLOCKED")
        self.assertEqual(blocked["reason_code"], "CAP_UNMET")

    def test_delivery_scale_arithmetic(self):
        """全尺寸读数（记录值：需求 10 111 对、已挡 1 813 对 ⇒ 要补 8 298）。

        这条不碰 Blender：用的是 `reports/subai/M00/measurements.json` 里那两个数的算术关系，
        核对「上限由需求推出」在交付尺度上的读数：cap = 10 111（护栏 20 000 不咬），needs = 8 298。
        """
        result = {"constraints_needed": 10111,
                  "constraints_already_blocked": 1813,
                  "constraints_to_add": 10111 - 1813,
                  "skipped_count": 0}
        self.assertEqual(result["constraints_to_add"], 8298)
        fields = self.stage.mask_preflight_fields(result)
        self.assertEqual(fields, {"needs": 8298, "cap": 10111, "skipped": 0,
                                  "guardrail_hit": False})
        request = {"provenance": {"stage": os.path.join(ROOT, "mmdpipe", "stage.py")},
                   "lease": False, **fields}
        self.assertEqual(preflight_mod.check(request, worktree=ROOT)["state"], "READY")


class _ListHatingScene(FakeScene):
    """拒绝「列表值」的场景：Blender 的 IDProperty 数组收不了字符串列表。

    假场景是 `dict`，什么值都存得下，所以离屏测试天生看不见这条边界 ——
    这也正是「手抄 11 键 vs `MASK_WIRED_KEYS` 18 键」漂了 400 行没人发现的原因。
    """

    def __setitem__(self, key, value):
        if isinstance(value, dict) and any(
                isinstance(v, (list, tuple)) for v in value.values()):
            raise TypeError("IDProperty 数组不支持列表值")
        super().__setitem__(key, value)


class TestMaskWiredRecordCoversTheWholeList(unittest.TestCase):
    """场景里那本「建场记录」必须按 `MASK_WIRED_KEYS` 生成，不许手抄子集。

    1号 2026-11-16 19:08 在冻结件回读里撞出：`mask_wired` 只有 11 个键，
    `constraints_released` 不在里面 —— 于是「掩码放掉 2196 条」这件事在交付件里**没有出处**，
    他只能数到 `10111 = 8298 + 1813`，拼不出 `4009`。手抄清单与 `MASK_WIRED_KEYS`
    是同一个东西的两份写法，400 行后就漂了。
    """

    def setUp(self):
        self.stage, self.bpy = load_stage()

    def test_stored_record_carries_every_key_the_report_has(self):
        wired_scene(self.bpy)
        seed_template(self.bpy)
        result = self.stage.apply_collision_masks()
        stored = dict(self.bpy.scene["mask_wired"])
        want = {k for k in self.stage.MASK_WIRED_KEYS if k in result}
        self.assertEqual(set(stored), want,
                         "场景里的建场记录与 MASK_WIRED_KEYS 对不上：少 %r / 多 %r"
                         % (sorted(want - set(stored)), sorted(set(stored) - want)))

    def test_released_count_lands_in_the_artifact(self):
        """`constraints_released` 是「放掉了几条」的唯一出处，必须在件里。"""
        wired_scene(self.bpy)
        seed_template(self.bpy)
        self.stage.apply_collision_masks()
        self.assertIn("constraints_released", self.bpy.scene["mask_wired"])
        self.assertIn("bodies", self.bpy.scene["mask_wired"])

    def test_the_stored_key_is_not_outside_the_single_list(self):
        wired_scene(self.bpy)
        seed_template(self.bpy)
        self.stage.apply_collision_masks()
        extra = set(self.bpy.scene["mask_wired"]) - set(self.stage.MASK_WIRED_KEYS)
        self.assertEqual(extra, set(), "记录里冒出清单外的键：%r" % (sorted(extra),))

    def test_unstorable_value_does_not_wipe_the_record(self):
        """一个值存不下 ⇒ 整条记录不许消失：退成标量，并把缺口记进返回值。

        这条防的是「PARTIAL 时反而没证据」：`verdict_reasons` 一旦非空就带字符串列表，
        旧写法整条 `scene["mask_wired"] = {...}` 会一起失败，连 `constraints_capped` 都没了。
        """
        wired_scene(self.bpy)
        seed_template(self.bpy)
        strict = _ListHatingScene(self.bpy.scene.collection.objects)
        original = self.bpy.context.scene
        self.bpy.context.scene = strict
        try:
            result = self.stage.apply_collision_masks()
        finally:
            self.bpy.context.scene = original
        self.assertIn("mask_wired", strict, "整条建场记录被吞掉了")
        self.assertIn("verdict_reasons", result.get("mask_wired_omitted") or [],
                      "被丢掉的键没有记进返回值：%r" % (result.get("mask_wired_omitted"),))
        self.assertIn("constraints_released", strict["mask_wired"])
        self.assertIn("verdict", strict["mask_wired"])


if __name__ == "__main__":
    unittest.main()
