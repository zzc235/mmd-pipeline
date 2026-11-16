"""`mmdpipe/chain_nla.py` 的写侧离屏测试（**不开 Blender**）。

覆盖到哪一层，写死在这里：**只覆盖 `_shift_b_action` 在两种动作形状上的曲线读写**。
不覆盖真实 NLA 拼接（`import_vmd(use_nla)` / `nla.bake` / `export_vmd`）—— 那几样只有
在真 Blender 里跑才算验过；本文件也不证明 `Action.fcurve_ensure_for_datablock` 在 5.2 里
长什么样（那是待验假设，真机窗口里量）。

为什么要这块：`chain_nla` 原来直接写 `action.fcurves.find/new`。分层动作上 `.fcurves`
一碰就抛，于是「在存过盘的件上重跑拼接」崩的是**写**，不是读（`D-213` 派工）。
"""
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class _Fake:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class _KP:
    """关键帧：只要 `co[0]`/`co[1]` 两个下标。"""

    def __init__(self, frame, value):
        self.co = [frame, value]


class _Points(list):
    """`keyframe_points`：支持 `insert(frame, value, options=)` 与迭代。"""

    def __init__(self, keys=()):
        super().__init__(_KP(f, v) for f, v in keys)

    def insert(self, frame, value, options=None):
        self.append(_KP(frame, value))
        return self[-1]


class _Curve:
    def __init__(self, path, index, group="", keys=()):
        self.data_path = path
        self.array_index = index
        self.group = group
        self.keyframe_points = _Points(keys)
        self.updated = 0

    def update(self):
        self.updated += 1


class _Coll:
    """`fcurves` 集合：`find` / `new` / `len` / 迭代。"""

    def __init__(self, curves=None):
        self.curves = list(curves or [])

    def find(self, path, index=0):
        for c in self.curves:
            if c.data_path == path and c.array_index == index:
                return c
        return None

    def new(self, path, index=0, action_group=""):
        c = _Curve(path, index, action_group)
        self.curves.append(c)
        return c

    def __len__(self):
        return len(self.curves)

    def __iter__(self):
        return iter(self.curves)


def _layered(bags, slots=None):
    """分层动作：`.fcurves` 一碰就抛，只有 `layers[].strips[].channelbags[]`。"""
    for bag, slot in zip(bags, slots or [None] * len(bags)):
        if slot is not None:
            bag.slot = slot
    layer = _Fake(strips=[_Fake(channelbags=bags)])
    return _Fake(layers=[layer])


def load_chain_nla():
    """装一个哑 `bpy` 让模块能加载（只测纯逻辑，不调真 bpy）。"""
    if "bpy" not in sys.modules:
        sys.modules["bpy"] = types.ModuleType("bpy")
    if "addon_utils" not in sys.modules:
        sys.modules["addon_utils"] = types.ModuleType("addon_utils")
    from mmdpipe import chain_nla
    return chain_nla


CN = load_chain_nla()
PATH = 'pose.bones["センター"].location'


class ShiftBOneActionTest(unittest.TestCase):

    def setUp(self):
        self.arm = _Fake(animation_data=_Fake(action_slot=None))

    def test_legacy_action_creates_three_curves_with_two_keys(self):
        coll = _Coll()
        keys, via = CN._shift_b_action(self.arm, _Fake(fcurves=coll), "センター",
                                       (0.5, -0.25, 2.0), 301, 601)
        self.assertEqual(keys, 2)
        self.assertEqual(via, ["action.fcurves"])
        self.assertEqual(len(coll), 3)
        for i, c in enumerate(coll):
            self.assertEqual([(kp.co[0], round(kp.co[1], 4)) for kp in c.keyframe_points],
                             [(301, (0.5, -0.25, 2.0)[i]), (601, (0.5, -0.25, 2.0)[i])])

    def test_layered_action_shifts_existing_keys(self):
        """存盘再读回来的动作：写侧必须自己找到 channelbag，而不是崩在 `.fcurves`。"""
        bag = _Fake(fcurves=_Coll([_Curve(PATH, 0, "センター", keys=[(10, 1.0)])]))
        act = _layered([bag])
        keys, via = CN._shift_b_action(self.arm, act, "センター", (2.0, 0.0, 0.0), 1, 2)
        self.assertEqual(keys, 1)
        self.assertEqual(via, ["channelbags[0](find)", "channelbags[0](new)"])
        self.assertEqual(bag.fcurves.curves[0].keyframe_points[0].co[1], 3.0)

    def test_old_form_expression_really_would_crash(self):
        """反控：退回 `action.fcurves.find(...)` 那种写法，在分层动作上是 `AttributeError`。"""
        act = _layered([_Fake(fcurves=_Coll())])
        with self.assertRaises(AttributeError):
            act.fcurves.find(PATH, index=0)

    def test_two_channelbags_without_slot_match_is_refused(self):
        """看不清就当红：不许挑一个 bag 往上写，也不许改写了一半就停。"""
        bags = [_Fake(fcurves=_Coll()), _Fake(fcurves=_Coll())]
        with self.assertRaises(RuntimeError):
            CN._shift_b_action(self.arm, _layered(bags), "センター", (1.0, 0.0, 0.0), 1, 2)
        self.assertEqual([len(b.fcurves) for b in bags], [0, 0])

    def test_slot_match_picks_the_right_bag(self):
        slot = object()
        bags = [_Fake(fcurves=_Coll([_Curve(PATH, 0, "センター", keys=[(5, 0.0)])])),
                _Fake(fcurves=_Coll([_Curve(PATH, 0, "センター", keys=[(5, 0.0)])]))]
        arm = _Fake(animation_data=_Fake(action_slot=slot))
        keys, via = CN._shift_b_action(arm, _layered(bags, slots=[object(), slot]),
                                       "センター", (1.0, 0.0, 0.0), 1, 2)
        self.assertEqual(keys, 1)
        self.assertEqual(via, ["channelbags[slot](find)", "channelbags[slot](new)"])
        self.assertEqual([b.fcurves.curves[0].keyframe_points[0].co[1] for b in bags],
                         [0.0, 1.0])

    def test_action_without_any_container_is_refused(self):
        with self.assertRaises(RuntimeError):
            CN._shift_b_action(self.arm, _Fake(layers=[]), "センター", (1.0, 0.0, 0.0), 1, 2)


if __name__ == "__main__":
    unittest.main()
