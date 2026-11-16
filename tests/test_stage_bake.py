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
import ast
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


class TestBakeRecordSaysWhereTheCacheLives(unittest.TestCase):
    """内存缓存**不随 `.blend` 落盘** ⇒ 记录必须自己说清「烘到哪去了」。"""

    def _stage(self):
        stage, _ = load_stage()
        return stage

    def _scene(self, cache):
        return types.SimpleNamespace(
            rigidbody_world=None if cache is None else types.SimpleNamespace(point_cache=cache))

    def test_memory_only_cache_is_recorded_as_off(self):
        stage = self._stage()
        cache = types.SimpleNamespace(frame_start=1, frame_end=833,
                                      use_disk_cache=False, disk_cache_bake=False)
        rec = stage.bake_record(self._scene(cache),
                                {"frame_start": 1, "frame_end": 833, "fps": 30},
                                {}, True, True, False)
        self.assertIs(rec["persist"]["use_disk_cache"], False)
        self.assertIs(rec["persist"]["disk_cache_bake"], False)
        self.assertFalse(rec["persist"]["reopened"])

    def test_no_point_cache_is_none_not_false(self):
        """量不到 ≠ 没开：没有 point_cache 时必须是 `None`，不许写 False 冒充读数。"""
        stage = self._stage()
        rec = stage.bake_record(self._scene(None), None, {}, False, False, False)
        self.assertIsNone(rec["persist"]["use_disk_cache"])
        self.assertIsNone(rec["persist"]["disk_cache_bake"])


class TestBakeFailureShapeTellsTheThreeApart(unittest.TestCase):
    """`D-214` / `D-217`：`applied=true` 不足判「交付件已烘」，三种形状要能分开打红。

    `1号` 19:15 在重开的冻结件上量到的那份：`is_baked=true / is_outdated=true /
    use_disk_cache=false`、`info="833 frames in memory (7.3 MiB), cache is outdated!"`，
    冷跳读到的姿态与顺序重算差 `max_delta=1.85651505 m @f417`（275/323 超 tol）。
    """

    def setUp(self):
        self.stage, _ = load_stage()

    def _record(self, applied=True, reopened=None, baked_after=None, outdated=None,
                replay_matched=True, first_eval=True):
        record = {
            "requested": {"frame_start": 1, "frame_end": 833, "fps": 30},
            "applied": applied,
            "frame_start": 1, "frame_end": 833, "fps": 30,
            "pose_source": "cache_replay" if applied else "fresh_solve",
            "is_baked": applied, "is_outdated": False,
            "probe": {"matched": True, "reference_moved": True},
            "persist": {"use_disk_cache": False, "disk_cache_bake": False,
                        "cache_info": None, "reopened": False,
                        "is_baked_after_reopen": None, "is_outdated_after_reopen": None,
                        "replay_probe": None},
        }
        if reopened is not None:
            record = self.stage.bake_artifact_record(
                record, reopened=reopened,
                replay_probe=self.stage.bake_replay_probe(
                    matched=replay_matched,
                    first_eval_after_open=first_eval,
                    max_delta=0.0 if replay_matched else 1.85651505,
                    frames=[417]),
                is_baked_after_reopen=baked_after,
                is_outdated_after_reopen=outdated)
        return record

    def test_not_baked(self):
        record = self._record(applied=False)
        self.assertEqual(self.stage.bake_failure_shape(record), "not_baked")
        self.assertIn("applied", self.stage.bake_missing(record))

    def test_baked_but_cache_not_usable_after_reopen(self):
        """今晚那份：进程内六条全绿，重开就 `is_outdated` ⇒ 落「烘了但没持久化」。"""
        record = self._record(reopened=True, baked_after=True, outdated=True)
        self.assertEqual(self.stage.bake_failure_shape(record), "baked_not_persisted")
        self.assertEqual(self.stage.bake_missing(record), [],
                         "进程内六条应当全绿——红在重开那一层")
        self.assertEqual(self.stage.bake_artifact_missing(record),
                         ["cache_usable_after_reopen"])
        self.assertIsNone(self.stage.bake_gate_reason(record))
        self.assertIn("baked_not_persisted",
                      self.stage.bake_artifact_gate_reason(record))

    def test_never_reopened_is_unmeasured_not_a_failure(self):
        """没在重开的字节上量过 ⇒ `replay_unmeasured`（缺料），不是 `replay_mismatch`（做错）。

        `D-219`：把 `UNMEASURED` 当 `FAIL` 用，会让读者去找一个不存在的正确性 bug。
        """
        record = self._record()
        self.assertEqual(self.stage.bake_failure_shape(record), "replay_unmeasured")
        self.assertEqual(self.stage.bake_artifact_missing(record),
                         ["reopen_measured", "cache_usable_after_reopen",
                          "replay_first_eval_after_open", "replay_matched_after_reopen"])

    def test_reopened_without_a_replay_probe_is_unmeasured(self):
        """缓存可用、但没做重放对照 ⇒ 仍然是「缺料」，不许写成不一致。"""
        record = self._record(reopened=True, baked_after=True, outdated=False)
        record["persist"]["replay_probe"] = None
        self.assertEqual(self.stage.bake_failure_shape(record), "replay_unmeasured")
        self.assertEqual(self.stage.bake_artifact_missing(record),
                         ["replay_first_eval_after_open", "replay_matched_after_reopen"])

    def test_persisted_but_replay_differs(self):
        """缓存可用、但冷跳读回来的姿态与顺序重算不一致 ⇒ 最难发现的那一种。"""
        record = self._record(reopened=True, baked_after=True, outdated=False,
                              replay_matched=False)
        self.assertEqual(self.stage.bake_failure_shape(record), "replay_mismatch")
        self.assertEqual(self.stage.bake_artifact_missing(record),
                         ["replay_matched_after_reopen"])

    def test_ok_when_measured_and_replayed_on_the_reopened_bytes(self):
        record = self._record(reopened=True, baked_after=True, outdated=False)
        self.assertEqual(self.stage.bake_failure_shape(record), "ok")
        self.assertEqual(self.stage.bake_artifact_missing(record), [])
        self.assertIsNone(self.stage.bake_artifact_gate_reason(record))

    def test_self_fulfilling_replay_is_unmeasured_not_matched(self):
        """`D-223`/`D-224`：先顺序走完再冷跳（`first_eval_after_open=false`）⇒ 不算一致。

        `1号` 19:20 那支 `matched=true / max_delta=0.0` 就是这种：缓存里装的是本会话自己
        刚算出来的东西，冷跳读到的是它自己。判它 `replay_unmeasured`，**不是** `replay_mismatch`。
        """
        record = self._record(reopened=True, baked_after=True, outdated=False,
                              first_eval=False)
        self.assertEqual(self.stage.bake_failure_shape(record), "replay_unmeasured")
        checks = self.stage.bake_checks(record)
        self.assertFalse(checks["replay_first_eval_after_open"])
        self.assertFalse(checks["replay_matched_after_reopen"],
                         "方式不对时 matched 这面旗不许单独为真")
        self.assertEqual(self.stage.bake_artifact_missing(record),
                         ["replay_first_eval_after_open", "replay_matched_after_reopen"])

    def test_missing_first_eval_flag_is_unmeasured(self):
        """漏写这个键 ⇒ 同样算没量（不许因为默认值变成"一致"）。"""
        record = self._record(reopened=True, baked_after=True, outdated=False)
        del record["persist"]["replay_probe"]["first_eval_after_open"]
        self.assertEqual(self.stage.bake_failure_shape(record), "replay_unmeasured")
        self.assertFalse(self.stage.bake_checks(record)["replay_matched_after_reopen"])

    def test_replay_probe_builder_defaults_the_flag_to_false(self):
        """漏写 `first_eval_after_open` ⇒ 落 `false`（可补的记录），而不是抛异常。

        `D-225`：「能靠记录解决的事，不要用拒绝解决」—— 漏一个可补的字段不该让一次
        6–12 分钟的构建当场死掉，红在记录里、理由看得见、单条重跑就补得回。
        """
        probe = self.stage.bake_replay_probe(matched=True, max_delta=0.0, frames=[417])
        self.assertIs(probe["first_eval_after_open"], False)
        self.assertEqual(sorted(probe), ["first_eval_after_open", "frames",
                                         "matched", "max_delta"])
        record = self._record(reopened=True, baked_after=True, outdated=False)
        record["persist"]["replay_probe"] = probe
        self.assertEqual(self.stage.bake_failure_shape(record), "replay_unmeasured",
                         "漏键的探针不许被判成「一致」")
        self.assertIn("replay_first_eval_after_open",
                      self.stage.bake_artifact_missing(record))

    def test_disk_cache_switch_is_recorded_but_never_a_criterion(self):
        """`use_disk_cache` 只记录：`D-218` 实测赋值会把 Blender 打死，判据不能建在它上面。"""
        record = self._record(reopened=True, baked_after=True, outdated=False)
        record["persist"]["use_disk_cache"] = True
        self.assertEqual(self.stage.bake_failure_shape(record), "ok")
        self.assertEqual(self.stage.bake_artifact_missing(record), [])
        self.assertNotIn("use_disk_cache", " ".join(self.stage.BAKE_ARTIFACT_CRITERIA))

    def test_artifact_criteria_build_on_the_in_process_ones(self):
        """一层建在另一层上：不存在两份互相打架的规则。"""
        self.assertEqual(list(self.stage.BAKE_CRITERIA),
                         ["requested", "applied", "not_outdated", "probe_matched",
                          "probe_informative", "fields_complete"])
        self.assertEqual(list(self.stage.BAKE_ARTIFACT_CRITERIA),
                         list(self.stage.BAKE_CRITERIA)
                         + ["reopen_measured", "cache_usable_after_reopen",
                            "replay_first_eval_after_open", "replay_matched_after_reopen"])

    def test_ok_is_a_construction_the_engine_cannot_reach(self):
        """结构哨兵：`ok` 要求「开件后第一次求值」**且**「等于顺序重算」，两者在非起始帧互斥。

        * 暖探针（顺序重算后冷跳）⇒ `first_eval_after_open=false` ⇒ `replay_unmeasured`；
        * 冷探针（开件后第一次求值就是它）⇒ 没有同会话暖参照，只能比另一会话的冷参照，
          而 `D-223` 保证两者差 1.86–1.99 m ⇒ `replay_mismatch`。

        所以 `ok` 在引擎里到不了；`2号` 19:49 的 `f1` 判别补了边界（姿态与解算状态无关的帧上两者相同）。
        这条测试是那个待决点的哨兵：引擎或口径一变它就红，提醒回去重新裁，不许在实现里偷偷放宽。
        """
        warm = self._record(reopened=True, baked_after=True, outdated=False, first_eval=False)
        self.assertEqual(self.stage.bake_failure_shape(warm), "replay_unmeasured")
        cold_mismatch = self._record(reopened=True, baked_after=True, outdated=False,
                                    first_eval=True, replay_matched=False)
        self.assertEqual(self.stage.bake_failure_shape(cold_mismatch), "replay_mismatch")
        # 仪器本身允许 ok（引擎做不到的那种组合），否则判据就成了「恒红」
        instrument_ok = self._record(reopened=True, baked_after=True, outdated=False)
        self.assertEqual(self.stage.bake_failure_shape(instrument_ok), "ok")

    def test_the_six_criteria_names_are_unchanged(self):
        """1号 在读 `bake_checks()["probe_informative"]`：老键的名字与语义不许动。"""
        checks = self.stage.bake_checks({})
        for name in self.stage.BAKE_CRITERIA:
            self.assertIn(name, checks)
        self.assertEqual(list(checks), list(self.stage.BAKE_ARTIFACT_CRITERIA))

    def test_stage_py_never_writes_use_disk_cache(self):
        """反控：源码里不许**赋值** `use_disk_cache`（赋值会把 Blender 打死）。

        只允许读（`getattr(cache, "use_disk_cache", ...)`）。这条防的是「下次有人好心把它打开」。
        用 AST 判，不按词匹配——文档字符串里写着这个字段名的地方不算。
        """
        tree = ast.parse(inspect.getsource(sys.modules["mmdpipe.stage"]))
        offenders = []
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = (node.targets if isinstance(node, ast.Assign)
                           else [node.target])
            for target in targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Attribute) and sub.attr == "use_disk_cache":
                        offenders.append(node.lineno)
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "setattr"
                    and any(isinstance(a, ast.Constant) and a.value == "use_disk_cache"
                            for a in node.args)):
                offenders.append(node.lineno)
        self.assertEqual(offenders, [], "stage.py 里出现了对 use_disk_cache 的赋值")


if __name__ == "__main__":
    unittest.main()
