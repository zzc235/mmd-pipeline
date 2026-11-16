"""拼接层回归：三段帧账本、每个交接对、记录守恒、显式截断、NLA 段数门禁。

纯 Python，不需要 Blender。夹具从两个已登记样本切 91/91/151 帧，
对应 2026-11-15 丢段样例的帧数（期望 337、实际 244）。
"""
from __future__ import annotations

import os
import shutil
import struct
import tempfile
import unittest

from mmdpipe import chainplan, concatvmd, vmd

M = "E:/blender模型"
A = M + "/原神摇_by_ChildeDuck_c658aa3daba96482861d466e1f1868c7/原神摇/原神摇.vmd"
B = M + "/活着dj_by_lucky破_923ad74feee8ea23a61ed34b5798a78e/活着dj/活着dj_VMD-TDA.vmd"
HAVE = os.path.exists(A) and os.path.exists(B)


def _slice(motion, lo, hi):
    d = motion.raw
    bones = []
    for i in range(motion.bone_count):
        s = motion.bone_start + i * vmd.BONE_RECORD
        rec = d[s:s + vmd.BONE_RECORD]
        if lo <= struct.unpack_from("<I", rec, 15)[0] <= hi:
            bones.append(rec)
    morphs = []
    for i in range(motion.morph_count):
        s = motion.morph_start + i * vmd.MORPH_RECORD
        rec = d[s:s + vmd.MORPH_RECORD]
        if lo <= struct.unpack_from("<I", rec, 15)[0] <= hi:
            morphs.append(rec)
    name_len = 20 if motion.magic == "0002" else 10
    head = bytearray(d[:30 + name_len])
    head[30:30 + name_len] = b"t_fixture" + b"\x00" * (name_len - len(b"t_fixture"))
    out = head + struct.pack("<I", len(bones)) + b"".join(bones)
    out += struct.pack("<I", len(morphs)) + b"".join(morphs)
    out += struct.pack("<4I", 0, 0, 0, 0)
    return bytes(out)


@unittest.skipUnless(HAVE, "缺少样本")
class TestThreeSegmentLedger(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="mmdchain ")
        a, b = vmd.load(A), vmd.load(B)
        cls.segs = []
        for name, motion, hi in (("seg1_91.vmd", a, 90),
                                 ("seg2_91.vmd", b, 90),
                                 ("seg3_151.vmd", b, 150)):
            p = os.path.join(cls.tmp, name)
            with open(p, "wb") as fh:
                fh.write(_slice(motion, 0, hi))
            cls.segs.append(p)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _concat(self, paths, gap=2, frames=None, name="chain.vmd"):
        out = os.path.join(self.tmp, name)
        rep = concatvmd.concat_vmd(paths, out, gap=gap, verbose=False, frames=frames)
        return rep, out

    # --- 账本 -------------------------------------------------------------
    def test_plan_three_segments_is_337(self):
        rep = chainplan.plan(self.segs, gap=2)
        self.assertEqual([s["timeline"] for s in rep["segments"]],
                         [[0, 90], [93, 183], [186, 336]])
        self.assertEqual([s["offset"] for s in rep["segments"]], [0, 93, 186])
        self.assertEqual(rep["total_frames"], 337)

    def test_every_junction_is_reported(self):
        rep = chainplan.plan(self.segs, gap=2)
        self.assertEqual([j["pair"] for j in rep["junctions"]], [[0, 1], [1, 2]])
        self.assertEqual([j["timeline"] for j in rep["junctions"]],
                         [[90, 93], [183, 186]])
        # 兼容字段仍指第一个交接对
        self.assertEqual(rep["pose_diff"], rep["junctions"][0]["pose_diff"])

    # --- 拼接帧数守恒 -----------------------------------------------------
    def test_concat_offsets_accumulate(self):
        rep, out = self._concat(self.segs)
        self.assertEqual([s["dst_range"] for s in rep["spans"]],
                         [[0, 90], [93, 183], [186, 336]])
        self.assertEqual(rep["total_frames"], 337)

    def test_concat_has_no_overlap_at_3_segments(self):
        rep, _ = self._concat(self.segs)
        self.assertEqual(rep["overlaps"], [], "三段拼接出现时间轴重叠 = 丢段")

    def test_plan_and_concat_agree(self):
        plan = chainplan.plan(self.segs, gap=2)
        rep, _ = self._concat(self.segs)
        self.assertEqual(plan["total_frames"], rep["total_frames"])

    def test_bone_records_conserved(self):
        src = sum(vmd.load(p).bone_count for p in self.segs)
        rep, out = self._concat(self.segs)
        self.assertEqual(rep["bone_records"], src)
        self.assertEqual(vmd.load(out).bone_count, src)

    def test_transition_gap_frames_are_empty(self):
        """gap 只能是空帧，不能塞源记录。"""
        rep, out = self._concat(self.segs)
        m = vmd.load(out)
        d, hit = m.raw, []
        for i in range(m.bone_count):
            s = m.bone_start + i * vmd.BONE_RECORD
            hit.append(struct.unpack_from("<I", d, s + 15)[0])
        self.assertFalse({91, 92, 184, 185} & set(hit), "gap 帧里出现骨骼记录")

    def test_order_change_changes_span(self):
        rev = [self.segs[2], self.segs[1], self.segs[0]]
        rep, _ = self._concat(rev, name="rev.vmd")
        self.assertEqual([s["dst_range"] for s in rep["spans"]],
                         [[0, 150], [153, 243], [246, 336]])
        self.assertEqual(rep["total_frames"], 337)

    def test_single_segment_unchanged(self):
        rep, _ = self._concat([self.segs[0]], gap=2, name="one.vmd")
        self.assertEqual(rep["total_frames"], 91)

    # --- 截断 vs 丢段 -----------------------------------------------------
    def test_explicit_truncation_is_not_loss(self):
        rep, _ = self._concat(self.segs, frames=244)
        self.assertEqual(rep["total_frames"], 337)
        self.assertEqual(rep["explicit_truncated_frames"], 93)
        self.assertEqual(rep["unexplained_gap_frames"], 0)

    def test_path_with_spaces_and_chinese(self):
        rep, out = self._concat(self.segs, name="三段 拼接.vmd")
        self.assertEqual(rep["total_frames"], 337)
        self.assertTrue(os.path.exists(out))

    # --- NLA 段数门禁 -----------------------------------------------------
    # --- 尾部轨道（表情/IK）随偏移保留 -------------------------------------
    def test_morph_and_ik_tracks_follow_offset(self):
        """第二段的表情与 IK 开关必须整体跟到 offset 之后，不能被丢掉。"""
        tail = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "out", "B_aligned.vmd")
        if not (os.path.exists(tail) and vmd.load(tail).morph_count):
            self.skipTest("缺少带表情/IK 的样本")
        src = vmd.load(tail)
        rep, out = self._concat([self.segs[0], tail], gap=2, name="tail.vmd")
        m = vmd.load(out)
        self.assertEqual(m.morph_count, src.morph_count)
        frames = [struct.unpack_from("<I", m.raw, m.morph_start + i * vmd.MORPH_RECORD + 15)[0]
                  for i in range(m.morph_count)]
        self.assertGreaterEqual(min(frames), 93, "表情没跟随段偏移")
        self.assertGreaterEqual(m.ik_count, src.ik_count, "IK 开关轨道被丢")

    def test_nla_guard_blocks_three_segments(self):
        ok, why = chainplan.nla_segments_check(3)
        self.assertFalse(ok)
        self.assertIn("2 段", why)
        self.assertIn("splice", why)

    def test_nla_guard_allows_two_segments(self):
        self.assertEqual(chainplan.nla_segments_check(2), (True, ""))

    def test_nla_guard_rejects_single_segment(self):
        ok, _ = chainplan.nla_segments_check(1)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
