# -*- coding: utf-8 -*-
"""`stage_motion` 取 fcurve 的那一处（离屏，不需要 Blender）。

钉的是什么（`总控` 19:06 派工 + `D-212` 之后 3号 在真件上撞出的形状）：

* Blender 4.4+ 的动作**随 `.blend` 存盘再读回来**是分层/槽位动作（`layers[].strips[].
  channelbags[].fcurves`），`action.fcurves` 直接 `AttributeError`。`stage.py` 原来那处
  `len(action.fcurves)` 只看得到同会话刚导入的动作，所以从没崩过 —— 但「从没崩过」不等于
  「这条路对」：拿存过盘的件再进 `stage_motion` 就会崩；
* 现在只走 `apply_action.fcurves_of()`，并把读数从哪条路来记进 `metrics["fcurves_via"]`；
* **一份实现**：`stage.fcurves_of` 必须**就是** `apply_action.fcurves_of` 那个对象，
  否则又是两份实现（`D-186`）；
* 反控两条：老写法在这份假件上必须崩（证明假件忠实，不是为了让测试变绿造的）；
  源码 AST 检查必须能抓住老写法（否则那条断言本身是空的）；
* `G3`（曲线太少，不像有效动作）在分层路径上照样咬 —— 换取曲线的方式不许把「数到 0」当正常。
"""
import ast
import io
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_stage_wiring import load_stage  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGE_PY = os.path.join(ROOT, "mmdpipe", "stage.py")


# ---------------------------------------------------------------- 假动作
class FakeFCurve:
    def __init__(self, path='pose.bones["上半身"].location', index=0):
        self.data_path = path
        self.array_index = index
        self.keyframe_points = []


class LegacyAction:
    """同会话里刚由导入器造出来的动作：`action.fcurves` 读得到。"""

    def __init__(self, count=400):
        self.name = "B_aligned_bone"
        self.fcurves = [FakeFCurve(index=i % 3) for i in range(count)]
        self.frame_range = (1.0, 832.0)


class LayeredAction:
    """随 `.blend` 存盘再读回来的分层/槽位动作：`action.fcurves` 抛 `AttributeError`。

    `fcurves` 特意做成 property 并 raise —— 这正是真件上的形状（属性不存在），
    而不是「返回空列表」。两者对判据的后果完全不同：前者要走 channelbags，
    后者会让 `G3` 无条件咬（每份存盘件都会被判「不像有效动作」）。
    """

    def __init__(self, count=400, bags_per_strip=1):
        self.name = "B_aligned_bone"
        self.frame_range = (1.0, 832.0)
        per = max(1, count // bags_per_strip) if count else 0
        self.layers = [types.SimpleNamespace(strips=[
            types.SimpleNamespace(channelbags=[
                types.SimpleNamespace(fcurves=[FakeFCurve(index=i % 3) for i in range(per)])
                for _ in range(bags_per_strip)])])]

    @property
    def fcurves(self):
        raise AttributeError("'Action' object has no attribute 'fcurves'")


# ---------------------------------------------------------------- 假场景
class FakeArm:
    def __init__(self, action):
        self.name = "arm"
        self.animation_data = types.SimpleNamespace(action=action)

    def select_set(self, on):
        return None


class FakeRoot:
    name = "root"

    def select_set(self, on):
        return None


PRESET = {
    "motion": {"scale": 0.08, "bone_mapper": "PMX", "rename_bones": True,
               "use_underscore": True, "update_scene_settings": True},
    "render": {"fps": 30},
}


def _bpy_for_motion():
    """给 `stage_motion` 补上它要的两个 operator（假 bpy 是共享的，覆盖安装即可）。

    每次都重新装一遍闭包，否则前一条测试留下的 `calls` 列表会让本条断言看到空的 ——
    「共享夹具里的历史状态」正是那种让断言恒绿的东西。
    """
    stage, bpy = load_stage()
    calls = []
    bpy.ops.object = types.SimpleNamespace(
        select_all=lambda **kw: calls.append(("select_all", kw)))
    bpy.ops.mmd_tools = types.SimpleNamespace(
        import_vmd=lambda **kw: calls.append(("import_vmd", kw)))
    bpy.scene.rigidbody_world = None
    bpy.scene.frame_current = 1
    return stage, bpy, calls


def _run_motion(action, frame_end_hint=833):
    """跑一次 `stage_motion`，**并把共享假 bpy 的活动对象还原**。

    假 bpy 是模块级共享的（`load_stage()` 复用），`stage_motion` 会把 root 设成
    `view_layer.objects.active`。不还原的话，后面 `test_stage_wiring` 里走 ops 兜底的用例
    会拿到我这个假 root（`previous.name` 直接 AttributeError）——夹具污染不是"测试独立性"问题，
    是让别人的断言按我的假对象跑。
    """
    stage, bpy, calls = _bpy_for_motion()
    view_layer = bpy.context.view_layer
    previous = view_layer.objects.active
    try:
        res, end = stage.stage_motion(PRESET, FakeRoot(), FakeArm(action), "dummy.vmd",
                                      frame_end_hint)
    finally:
        view_layer.objects.active = previous
    return stage, res, end, calls


# ---------------------------------------------------------------- 判据
class TestStageMotionFcurves(unittest.TestCase):
    def test_legacy_action_reads_through_action_fcurves(self):
        """正控：同会话刚导入的动作走 `.fcurves`，并且**这条路被记下来**。"""
        _, res, end, calls = _run_motion(LegacyAction(count=400))
        self.assertEqual(res.metrics["fcurves"], 400)
        self.assertEqual(res.metrics["fcurves_via"], "action.fcurves")
        self.assertEqual(end, 832)
        self.assertEqual(res.metrics["frame_range"], [1, 832])
        self.assertFalse(res.blocked, "400 条曲线不该判 G3")
        self.assertEqual([c[0] for c in calls], ["select_all", "import_vmd"])

    def test_layered_action_reads_through_channelbags(self):
        """分层动作：不许崩，且计数从 channelbags 来。"""
        _, res, end, calls = _run_motion(LayeredAction(count=400))
        self.assertEqual(res.metrics["fcurves"], 400)
        self.assertEqual(res.metrics["fcurves_via"], "layers.strips.channelbags")
        self.assertEqual(end, 832)
        self.assertFalse(res.blocked)
        self.assertEqual([c[0] for c in calls], ["select_all", "import_vmd"],
                         "import_vmd 只该调一次")

    def test_layered_action_still_blocks_on_too_few_curves(self):
        """G3 在分层路径上照样咬：换成 channelbags 不等于把「数到 0」当正常。"""
        stage, res, _, _ = _run_motion(LayeredAction(count=3))
        self.assertEqual(res.metrics["fcurves"], 3)
        self.assertTrue(res.blocked, "3 条曲线必须判 G3")
        codes = [i.code for i in res.issues if i.severity == stage.BLOCK]
        self.assertIn("G3", codes)

    def test_layered_action_with_no_channelbags_blocks(self):
        """分层动作但一条曲线都没有：`fcurves=0` ⇒ G3 咬，不许静默放过。"""
        action = LayeredAction(count=0)
        stage, res, _, _ = _run_motion(action)
        self.assertEqual(res.metrics["fcurves"], 0)
        self.assertTrue(res.blocked)
        self.assertIn("G3", [i.code for i in res.issues if i.severity == stage.BLOCK])

    def test_old_way_crashes_on_layered_action(self):
        """反控（取证）：老写法在这份假件上必须崩 —— 假件不是为让测试变绿造的。"""
        with self.assertRaises(AttributeError):
            len(LayeredAction(count=400).fcurves)

    def test_same_implementation_as_apply_action(self):
        """一份实现：`stage.fcurves_of` 必须就是 `apply_action.fcurves_of`。"""
        stage, _ = load_stage()
        from mmdpipe import apply_action
        self.assertIs(stage.fcurves_of, apply_action.fcurves_of)
        self.assertTrue(callable(stage.fcurves_of))


# ---------------------------------------------------------------- 源码级
def _read(path):
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


def _bare_fcurves_attrs(source):
    """源码里所有 `X.fcurves` 形态的行号（`fcurves_of` 里的 `action.fcurves` 也算）。"""
    tree = ast.parse(source)
    return [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and n.attr == "fcurves"]


class TestStageSourceHasNoBareFcurves(unittest.TestCase):
    def test_stage_py_has_no_bare_fcurves(self):
        self.assertEqual(_bare_fcurves_attrs(_read(STAGE_PY)), [],
                         "stage.py 里不许直接读 `.fcurves`，一律走 fcurves_of()")

    def test_the_ast_check_catches_the_old_line(self):
        """反控：这条 AST 断言必须能抓住原来那一行，否则它自己是空的。"""
        old = "def f(action):\n    return len(action.fcurves)\n"
        self.assertEqual(_bare_fcurves_attrs(old), [2])
        self.assertIn("fcurves_of(action)", _read(STAGE_PY),
                      "取 fcurve 必须经由 fcurves_of(action)")

    def test_g3_threshold_message_mentions_count(self):
        """G3 的提示必须带实际条数 —— 「不像有效动作」不带数就查不动。"""
        self.assertIn("只有 %d 条曲线，不像有效动作", _read(STAGE_PY))


if __name__ == "__main__":
    unittest.main()
