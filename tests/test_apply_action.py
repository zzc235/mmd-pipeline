"""`mmdpipe/apply_action.py` 的离屏测试（**不开 Blender**）。

覆盖到哪一层，写死在这里：**只覆盖「换算计划」「记录判据」「动作源身份」三块纯 Python 逻辑**，
不覆盖 Blender 里的 `import_vmd` / `_trim_action` / `_hold_action` / `free_bake_all` ——
那几样只有在真 Blender 里跑才算验过（见 M05 报告里的三臂读数）。

反控（`D-186` 批准的三条）各自**只红它自己那一条**，不许合取式糊成一条：
    A2 声明 frame_end 与回读不符 / A3 应用后 is_baked 变 true / 计划参数自相矛盾。
"""
import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mmdpipe import apply_action as AA  # noqa: E402


# ------------------------------------------------------------------ 造一份 VMD
def make_vmd(path, bones, last_frame, model_name="test"):
    """最小合法 VMD：30 字节头 + 20 字节模型名 + 骨帧段（每骨每帧一条）。"""
    head = b"Vocaloid Motion Data 0002"
    head = head + b"\x00" * (30 - len(head))
    name = model_name.encode("shift_jis")[:20].ljust(20, b"\x00")
    recs = []
    for b in bones:
        bn = b.encode("shift_jis")[:15].ljust(15, b"\x00")
        for f in range(0, last_frame + 1):
            recs.append(bn + struct.pack("<I", f) + b"\x00" * 12 + b"\x00" * 16
                        + b"\x00" * 64)
    body = struct.pack("<I", len(recs)) + b"".join(recs)
    tail = struct.pack("<I", 0) * 5       # 表情 / 相机 / 光源 / 阴影 / IK 五段各 0 条
    with open(path, "wb") as fh:
        fh.write(head + name + body + tail)
    return path


class PlanTest(unittest.TestCase):
    """源末帧 → 应用后末帧 → 最终窗口 的换算。"""

    def test_no_op_keeps_applied_end(self):
        pl = AA.plan(300)
        self.assertEqual(pl["applied_last"], 301)      # +1 偏移是接线事实
        self.assertEqual(pl["final_last"], 301)
        self.assertEqual(pl["ops"], [])

    def test_hold_pads_to_window(self):
        pl = AA.plan(300, hold_until=832)
        self.assertEqual(pl["applied_last"], 301)
        self.assertEqual(pl["final_last"], 832)
        self.assertEqual(pl["ops"], [{"op": "hold", "from": 301, "to": 832, "frames": 531}])

    def test_trim_shortens(self):
        pl = AA.plan(300, trim_end=240)
        self.assertEqual(pl["final_last"], 240)
        self.assertEqual(pl["ops"][0]["dropped_frames"], 61)

    def test_reject_hold_not_beyond_source(self):
        with self.assertRaises(AA.PlanError):
            AA.plan(300, hold_until=301)               # 等于「应用后末帧」⇒ 补不出定格

    def test_reject_trim_beyond_source(self):
        with self.assertRaises(AA.PlanError):
            AA.plan(300, trim_end=400)                 # 源只到 301，截到 400 是越界

    def test_reject_trim_and_hold_together(self):
        with self.assertRaises(AA.PlanError):
            AA.plan(300, trim_end=240, hold_until=832)

    def test_reject_bad_frame_start(self):
        with self.assertRaises(AA.PlanError):
            AA.plan(300, frame_start=0)

    def test_reject_negative_source(self):
        with self.assertRaises(AA.PlanError):
            AA.plan(-1)


class DescribeSourceTest(unittest.TestCase):
    def test_reads_span_bones_keys_and_sha(self):
        with tempfile.TemporaryDirectory() as d:
            p = make_vmd(os.path.join(d, "a.vmd"), ["センター", "上半身"], 5)
            src = AA.describe_source(p)
        self.assertEqual(src["frame_range"], [0, 5])
        self.assertEqual(src["bones"], 2)
        self.assertEqual(src["bone_frames"], 12)       # 2 骨 × 6 帧
        self.assertEqual(len(src["sha256"]), 64)
        self.assertEqual(src["bytes"], os.path.getsize(p) if os.path.exists(p) else src["bytes"])


def good_record(**over):
    """一条全绿记录（三臂里真跑出来的形状）。反控都从这个底座上改动一处。"""
    rec = {
        "profile": {"ensure_addons": {"mmd_tools": True}},
        "source": {"path": "A.vmd", "sha256": "0" * 64, "frame_range": [0, 832],
                   "bones": 259, "bone_frames": 43962},
        "plan": AA.plan(832),
        "action": {"name": "arm_action", "fcurves": 900, "frame_range": [1, 833],
                   "nla_tracks": 0},
        "window": {"frame_start": 1, "frame_end": 833,
                   "frame_end_source": "readback:arm.animation_data.action.frame_range[1]"},
        "cache": {"has_rigidbody_world": True, "is_baked": False, "is_outdated": None,
                  "freed_bake": False},
    }
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(rec.get(k), dict):
            rec[k] = dict(rec[k], **v)
        else:
            rec[k] = v
    return rec


def failed(rec):
    out = AA.check_record(rec)
    return out["verdict"], [c["id"] for c in out["checks"] if not c["ok"]]


class CheckRecordTest(unittest.TestCase):
    def test_good_record_is_ready(self):
        self.assertEqual(failed(good_record()), ("READY", []))

    # --- 反控 0：插件没真就位（`hasattr` 会骗人）→ 只红 A0
    def test_reject_addon_not_ready_only_A0(self):
        rec = good_record(profile={"ensure_addons": {"mmd_tools": False}})
        self.assertEqual(failed(rec), ("BLOCKED", ["A0_profile_ready"]))

    # --- 反控 1：声明 frame_end 与回读不符 → 只红 A2
    def test_reject_declared_frame_end_mismatch_only_A2(self):
        rec = good_record()
        rec["action"]["frame_range"] = [1, 833]
        rec["window"]["frame_end"] = 832              # 声明 832，回读 833
        rec["plan"]["final_last"] = 832               # 让 A5 保持绿，隔离出 A2
        self.assertEqual(failed(rec), ("BLOCKED", ["A2_frame_end_readback"]))

    # --- 反控 1b：frame_end 不是回读来的 → 也只红 A2
    def test_reject_frame_end_not_from_readback_only_A2(self):
        rec = good_record()
        rec["window"]["frame_end_source"] = "expected:plan"
        self.assertEqual(failed(rec), ("BLOCKED", ["A2_frame_end_readback"]))

    # --- 反控 2：应用后 is_baked 变 true → 只红 A3
    def test_reject_baked_after_apply_only_A3(self):
        rec = good_record(cache={"is_baked": True})
        self.assertEqual(failed(rec), ("BLOCKED", ["A3_is_baked_false"]))

    # --- 反控 3：没有物理世界时 is_baked 无从读回 → 只红 A3（不许默认绿）
    def test_reject_no_rigidbody_world_only_A3(self):
        rec = good_record(cache={"has_rigidbody_world": False, "is_baked": None})
        self.assertEqual(failed(rec), ("BLOCKED", ["A3_is_baked_false"]))

    def test_reject_few_fcurves_only_A1(self):
        rec = good_record(action={"fcurves": 50})
        self.assertEqual(failed(rec), ("BLOCKED", ["A1_action_applied"]))

    def test_reject_nla_stacking_only_A4(self):
        rec = good_record(action={"nla_tracks": 2})
        self.assertEqual(failed(rec), ("BLOCKED", ["A4_no_nla_stacking"]))

    def test_reject_window_vs_plan_only_A5(self):
        rec = good_record()
        rec["plan"] = AA.plan(832, hold_until=900)
        rec["action"]["frame_range"] = [1, 833]
        rec["window"]["frame_end"] = 833
        self.assertEqual(failed(rec), ("BLOCKED", ["A5_window_matches_plan"]))

    def test_missing_fields_are_red_not_exception(self):
        verdict, bad = failed({})
        self.assertEqual(verdict, "BLOCKED")
        self.assertIn("A1_action_applied", bad)
        self.assertIn("A3_is_baked_false", bad)


class SourceOfTruthTest(unittest.TestCase):
    """两臂素材的换算必须在记录里显式，不许下游猜（D-186 第三节）。"""

    def test_d_arm_832_no_trim(self):
        pl = AA.plan(832)
        self.assertEqual((pl["applied_last"], pl["final_last"]), (833, 833))

    def test_d_arm_tail_outside_window_is_declared(self):
        pl = AA.plan(832)
        self.assertEqual(pl["applied_last"], 833)
        self.assertGreater(pl["applied_last"], 832)    # 尾帧在测量窗口外 ⇒ 必须进 known_risks

    def test_cw2_hold_from_is_302_not_301(self):
        pl = AA.plan(300, hold_until=832)
        self.assertEqual(pl["applied_last"], 301)      # 预注册写「301..832」，实测起点 302
        self.assertEqual(pl["ops"][0]["from"] + 1, 302)


if __name__ == "__main__":
    unittest.main()
