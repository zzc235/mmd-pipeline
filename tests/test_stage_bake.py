# -*- coding: utf-8 -*-
"""`stage_build` 显式烘焙参数 + 契约 B 行为探针（离屏，不需要 Blender）。

钉的是什么（`D-067` / `D-173` / 总控 18:31 派单）：

* `bake=None` ⇒ 旧路径逐字不变（metrics 里不多出 `bake` 键），否则会悄悄改掉别人的读数；
* `bake={...}` ⇒ 烘一次 + 随件落盘 `requested/applied/frame_start/frame_end/fps/pose_source/
  is_baked/is_outdated/probe`；
* **「烘过了」不是判据**：`is_baked` 在假烘焙上也是 True，所以必须有行为探针——
  冷跳读回来的姿态要等于烘焙前顺序解算的那次；
* 反控：假烘焙把人偶挪一帧（`is_baked` 照样 True）⇒ 探针必须判红，`bake_gate_reason()`
  必须给出 BLOCK 理由。
"""
import inspect
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_stage_wiring import load_stage  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------- 假场景
class FakePointCache:
    def __init__(self):
        self.frame_start = 1
        self.frame_end = 1
        self.is_baked = False
        self.is_outdated = False


class FakeRBW:
    def __init__(self):
        self.point_cache = FakePointCache()


class FakeWorld:
    """刚体世界的姿态来源：`truth(frame)` 是解算值，`cache` 是烘焙后冷跳读到的值。

    「诚实烘焙」把 `truth` 抄进 `cache`；「假烘焙」抄错一帧，但把 `is_baked` 置真——
    这正是 `D-155/D-158` 说的那种件：标志位证明不了任何事。
    """

    def __init__(self, names=("下擺_0_1", "下擺_0_2")):
        self.names = list(names)
        self.frame = 1
        self.cache = {}

    def truth(self, name, frame):
        base = 0.1 * (self.names.index(name) + 1)
        return [[base + frame * 0.01, 0.0, 0.0, 0.0],
                [0.0, base + frame * 0.02, 0.0, 0.0],
                [0.0, 0.0, base, 0.0],
                [0.0, 0.0, 0.0, 1.0]]

    def pose(self, name):
        if self.frame in self.cache and name in self.cache[self.frame]:
            return self.cache[self.frame][name]
        return self.truth(name, self.frame)


class FakeScene:
    def __init__(self, world, fps=24, with_rbw=True):
        self.world = world
        self.render = types.SimpleNamespace(fps=fps)
        self.rigidbody_world = FakeRBW() if with_rbw else None
        self.frame_sets = []

    def frame_set(self, frame):
        self.frame_sets.append(frame)
        self.world.frame = frame


class FakeRigid:
    def __init__(self, world, name):
        self._world = world
        self.name = name
        self.mmd_type = "RIGID_BODY"

    @property
    def matrix_world(self):
        return self._world.pose(self.name)


class FakeNoMatrix:
    """没有 `matrix_world` 的对象：`pose_snapshot` 要跳过它，而不是抛。"""
    name = "坏对象"


def honest_bake(scene, world):
    def _bake(**_kw):
        cache = scene.rigidbody_world.point_cache
        for frame in range(int(cache.frame_start), int(cache.frame_end) + 1):
            world.cache[frame] = {name: world.truth(name, frame) for name in world.names}
        cache.is_baked = True
        cache.is_outdated = False
    return _bake


def lying_bake(scene, world, shift=1):
    """`is_baked=True`，但缓存里钉的是**另一帧**的姿态。"""
    def _bake(**_kw):
        cache = scene.rigidbody_world.point_cache
        for frame in range(int(cache.frame_start), int(cache.frame_end) + 1):
            world.cache[frame] = {name: world.truth(name, frame + shift)
                                  for name in world.names}
        cache.is_baked = True
        cache.is_outdated = False
    return _bake


def make_setup(fps=24, with_rbw=True):
    stage, _bpy = load_stage()
    world = FakeWorld()
    scene = FakeScene(world, fps=fps, with_rbw=with_rbw)
    objects = [FakeRigid(world, name) for name in world.names]
    return stage, world, scene, objects


# ---------------------------------------------------------------- bake_request
class TestBakeRequest(unittest.TestCase):
    def setUp(self):
        self.stage, _w, _s, _o = make_setup()

    def test_none_stays_none(self):
        self.assertIsNone(self.stage.bake_request(None))

    def test_defaults_follow_frame_start(self):
        self.assertEqual(self.stage.bake_request({"frame_start": 5}),
                         {"frame_start": 5, "frame_end": 5})
        self.assertEqual(self.stage.bake_request({}), {"frame_start": 1, "frame_end": 1})

    def test_fps_accepted(self):
        self.assertEqual(self.stage.bake_request({"frame_start": 1, "frame_end": 10, "fps": 30}),
                         {"frame_start": 1, "frame_end": 10, "fps": 30})

    def test_unknown_key_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            self.stage.bake_request({"frame_start": 1, "fps_base": 0.5})
        self.assertIn("fps_base", str(ctx.exception))

    def test_backwards_range_is_refused(self):
        with self.assertRaises(ValueError):
            self.stage.bake_request({"frame_start": 10, "frame_end": 3})

    def test_non_positive_fps_is_refused(self):
        with self.assertRaises(ValueError):
            self.stage.bake_request({"frame_start": 1, "fps": 0})

    def test_non_dict_is_refused(self):
        with self.assertRaises(ValueError):
            self.stage.bake_request(True)


# ---------------------------------------------------------------- 探针
class TestPoseSnapshotAndProbe(unittest.TestCase):
    def setUp(self):
        self.stage, self.world, _s, self.objects = make_setup()

    def test_snapshot_is_sixteen_floats(self):
        snap = self.stage.pose_snapshot(self.objects)
        self.assertEqual(sorted(snap), sorted(self.world.names))
        for values in snap.values():
            self.assertEqual(len(values), 16)
        self.assertTrue(all(isinstance(v, float) for v in snap[self.world.names[0]]))

    def test_snapshot_skips_objects_without_matrix(self):
        snap = self.stage.pose_snapshot(self.objects + [FakeNoMatrix()])
        self.assertNotIn("坏对象", snap)

    def test_identical_snapshots_match(self):
        a = self.stage.pose_snapshot(self.objects)
        probe = self.stage.bake_probe({1: a}, {1: a})
        self.assertTrue(probe["matched"])
        self.assertEqual(probe["max_delta"], 0.0)
        self.assertEqual(probe["bodies"], len(self.world.names))

    def test_within_tolerance_matches(self):
        a = self.stage.pose_snapshot(self.objects)
        b = {name: [v + 1e-8 for v in values] for name, values in a.items()}
        probe = self.stage.bake_probe({1: a}, {1: b})
        self.assertTrue(probe["matched"])
        self.assertLess(probe["max_delta"], 1e-6)

    def test_beyond_tolerance_is_red_with_detail(self):
        a = self.stage.pose_snapshot(self.objects)
        b = {name: list(values) for name, values in a.items()}
        b[self.world.names[0]][0] += 1e-3
        probe = self.stage.bake_probe({1: a}, {1: b})
        self.assertFalse(probe["matched"])
        self.assertEqual(probe["mismatch_count"], 1)
        row = probe["mismatches"][0]
        self.assertEqual(row["object"], self.world.names[0])
        self.assertGreater(row["delta"], 1e-6)

    def test_missing_frame_is_red(self):
        a = self.stage.pose_snapshot(self.objects)
        probe = self.stage.bake_probe({1: a, 2: a}, {1: a})
        self.assertFalse(probe["matched"])
        self.assertEqual(probe["missing_frames"], [2])

    def test_extra_frame_is_red(self):
        a = self.stage.pose_snapshot(self.objects)
        probe = self.stage.bake_probe({1: a}, {1: a, 2: a})
        self.assertFalse(probe["matched"])
        self.assertEqual(probe["extra_frames"], [2])

    def test_missing_body_is_red(self):
        a = self.stage.pose_snapshot(self.objects)
        b = {1: {self.world.names[0]: a[self.world.names[0]]}}
        probe = self.stage.bake_probe({1: a}, b)
        self.assertFalse(probe["matched"])
        self.assertEqual(probe["missing_objects"][0]["object"], self.world.names[1])

    def test_empty_snapshots_are_not_green(self):
        """两个空快照相「等」——但那是「什么都没读到」，不是「一致」。"""
        probe = self.stage.bake_probe({}, {})
        self.assertFalse(probe["matched"])
        self.assertEqual(probe["bodies"], 0)


# ---------------------------------------------------------------- 五条判据
def green_record(stage):
    probe = {"matched": True, "reference_moved": True, "mismatch_count": 0,
             "max_delta": 0.0, "frames": [1]}
    return {"requested": {"frame_start": 1, "frame_end": 10}, "applied": True,
            "frame_start": 1, "frame_end": 10, "fps": 24,
            "pose_source": "cache_replay", "is_baked": True, "is_outdated": False,
            "probe": probe}


class TestBakeChecks(unittest.TestCase):
    def setUp(self):
        self.stage, _w, _s, _o = make_setup()

    def test_green_record_passes_the_gate(self):
        record = green_record(self.stage)
        self.assertEqual(self.stage.bake_missing(record), [])
        self.assertIsNone(self.stage.bake_gate_reason(record))

    def test_each_criterion_can_be_red_alone(self):
        """六条各红一次，每次只有那一条红——否则合取式里坏一条就看不见。"""
        cases = {
            "requested": lambda r: r.update({"requested": None}),
            "applied": lambda r: r.update({"applied": False}),
            "not_outdated": lambda r: r.update({"is_outdated": True}),
            "probe_matched": lambda r: r.update({"probe": {"matched": False,
                                                           "reference_moved": True,
                                                           "mismatch_count": 3,
                                                           "max_delta": 0.5, "frames": [1]}}),
            "probe_informative": lambda r: r.update({"probe": {"matched": True,
                                                               "reference_moved": False,
                                                               "mismatch_count": 0,
                                                               "max_delta": 0.0,
                                                               "frames": [1]}}),
            "fields_complete": lambda r: r.pop("fps"),
        }
        for key, mutate in cases.items():
            record = green_record(self.stage)
            mutate(record)
            missing = self.stage.bake_missing(record)
            self.assertEqual(missing, [key], "判据 %s 的红没有单独成立" % key)
            reason = self.stage.bake_gate_reason(record)
            self.assertIsNotNone(reason)
            self.assertIn(key, reason)

    def test_probe_failure_reason_carries_numbers(self):
        record = green_record(self.stage)
        record["probe"] = {"matched": False, "reference_moved": True, "mismatch_count": 7,
                           "max_delta": 0.25, "frames": [1, 5, 10]}
        reason = self.stage.bake_gate_reason(record)
        self.assertIn("probe_matched", reason)
        self.assertIn("7", reason)
        self.assertIn("0.25", reason)


# ---------------------------------------------------------------- stage_bake 端到端
class TestStageBake(unittest.TestCase):
    def setUp(self):
        self.stage, self.world, self.scene, self.objects = make_setup()

    def test_honest_bake_passes(self):
        record = self.stage.stage_bake(self.scene, {"frame_start": 1, "frame_end": 9},
                                       objects=self.objects,
                                       bake_call=honest_bake(self.scene, self.world))
        self.assertTrue(record["applied"])
        self.assertTrue(record["is_baked"])
        self.assertEqual(record["pose_source"], "cache_replay")
        self.assertEqual((record["frame_start"], record["frame_end"]), (1, 9))
        self.assertEqual(record["fps"], 24)
        self.assertTrue(record["probe"]["matched"])
        self.assertIsNone(self.stage.bake_gate_reason(record))

    def test_lying_bake_is_caught_by_the_probe_not_the_flag(self):
        """反控：`is_baked` 仍是 True，只有行为探针能判红。"""
        record = self.stage.stage_bake(self.scene, {"frame_start": 1, "frame_end": 9},
                                       objects=self.objects,
                                       bake_call=lying_bake(self.scene, self.world))
        self.assertTrue(record["is_baked"])
        self.assertTrue(record["applied"])
        self.assertFalse(record["probe"]["matched"])
        self.assertGreater(record["probe"]["mismatch_count"], 0)
        reason = self.stage.bake_gate_reason(record)
        self.assertIn("probe_matched", reason)

    def test_bake_none_records_nothing_applied(self):
        record = self.stage.stage_bake(self.scene, None, objects=self.objects)
        self.assertIsNone(record["requested"])
        self.assertFalse(record["applied"])
        self.assertIn("requested", self.stage.bake_missing(record))

    def test_missing_rigidbody_world_is_recorded_not_raised(self):
        stage, world, scene, objects = make_setup(with_rbw=False)
        record = stage.stage_bake(scene, {"frame_start": 1, "frame_end": 3}, objects=objects)
        self.assertFalse(record["applied"])
        self.assertEqual(record["probe"].get("error"), "no_rigidbody_world")

    def test_requested_fps_is_written_to_the_scene(self):
        record = self.stage.stage_bake(self.scene, {"frame_start": 1, "frame_end": 3, "fps": 30},
                                       objects=self.objects,
                                       bake_call=honest_bake(self.scene, self.world))
        self.assertEqual(self.scene.render.fps, 30)
        self.assertEqual(record["fps"], 30)

    def test_cold_read_leaves_the_frame_before_reading(self):
        """冷跳必须先离开目标帧再跳回来：否则读到的是上一帧留下的值。"""
        self.stage.stage_bake(self.scene, {"frame_start": 1, "frame_end": 5},
                              objects=self.objects,
                              bake_call=honest_bake(self.scene, self.world))
        tail = self.scene.frame_sets[-4:]
        self.assertEqual(tail, [0, 3, 0, 5])

    def test_static_scene_gives_matched_but_uninformative(self):
        """场景不动时，烘前烘后必然逐位相同 —— 那只是「两次读到同一个静态值」，不是证据。

        这正是真 Blender 上「无动作的件」的形状：`matched=True`、`max_delta=0.0`，
        但它证明不了缓存忠实。所以 `reference_moved=False` 必须单独判红。
        """
        static_world = FakeWorld()
        static_world.truth = lambda name, frame: [[0.0, 0.0, 0.0, 0.0],
                                                  [0.0, 0.0, 0.0, 0.0],
                                                  [0.0, 0.0, 0.0, 0.0],
                                                  [0.0, 0.0, 0.0, 1.0]]
        scene = FakeScene(static_world)
        objects = [FakeRigid(static_world, name) for name in static_world.names]
        record = self.stage.stage_bake(scene, {"frame_start": 1, "frame_end": 5},
                                       objects=objects,
                                       bake_call=honest_bake(scene, static_world))
        self.assertTrue(record["probe"]["matched"])
        self.assertFalse(record["probe"]["reference_moved"])
        self.assertEqual(self.stage.bake_missing(record), ["probe_informative"])


# ---------------------------------------------------------------- 调用点与旧路径
class TestCallSite(unittest.TestCase):
    def setUp(self):
        self.source = inspect.getsource(sys.modules["mmdpipe.stage"].stage_build)

    def test_signature_has_explicit_bake(self):
        sig = inspect.signature(sys.modules["mmdpipe.stage"].stage_build)
        self.assertIn("bake", sig.parameters)
        self.assertIsNone(sig.parameters["bake"].default)

    def test_bake_block_is_guarded_and_after_the_mask_gate(self):
        guard = self.source.index("if bake is not None:")
        self.assertGreater(guard, self.source.index("mask_gate_reason(wired)"))
        self.assertGreater(self.source.index('res.metrics["bake"]'), guard)
        # 只此一处写 metrics["bake"]，且在 guard 之后 ⇒ bake=None 时 metrics 不会被改
        self.assertEqual(self.source.count('res.metrics["bake"]'), 1)

    def test_guard_returns_block_on_gate_reason(self):
        self.assertIn("bake_gate_reason(record)", self.source)
        block_at = self.source.index("bake_gate_reason(record)")
        self.assertLess(block_at, self.source.index("res.elapsed = _now() - t0\n    return res"))

    def test_existing_callers_do_not_pass_bake(self):
        """`runner.py` / 交付构建链不传 bake ⇒ 它们走的还是旧路径。"""
        paths = [os.path.join(ROOT, "mmdpipe", "runner.py"),
                 os.path.join(ROOT, "reports", "subai", "M02", "scripts",
                              "m02_rebuild_scene_v3.py")]
        checked = 0
        for path in paths:
            if not os.path.isfile(path):
                continue
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            for chunk in text.split("stage_build(")[1:]:
                head = chunk[:200]
                self.assertNotIn("bake=", head, "%s 里 stage_build 调用带了 bake" % path)
                checked += 1
        self.assertGreater(checked, 0, "一个 stage_build 调用点都没找到，这条断言等于没跑")


if __name__ == "__main__":
    unittest.main()
