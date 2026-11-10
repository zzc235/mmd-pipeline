"""VMD 层测试：解析、拼接字节一致、表情合并偏移。

纯 Python，不需要 Blender。
"""
import hashlib
import os
import shutil
import tempfile
import unittest

from mmdpipe import vmd

M = r"E:/blender模型"
A = M + "/原神摇_by_ChildeDuck_c658aa3daba96482861d466e1f1868c7/原神摇/原神摇.vmd"
B = M + "/活着dj_by_lucky破_923ad74feee8ea23a61ed34b5798a78e/活着dj/活着dj_VMD-TDA.vmd"
EXPR = M + "/活着dj_by_lucky破_923ad74feee8ea23a61ed34b5798a78e/活着dj/表情.vmd"


def _sha(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class TestParse(unittest.TestCase):
    @unittest.skipUnless(os.path.exists(A), "缺少样本")
    def test_bone_and_range(self):
        m = vmd.load(A)
        self.assertEqual(m.frame_range, (0, 446))
        self.assertGreater(len(m.bone_tracks), 40)
        self.assertTrue(m.tracks_valid, "尾部没对齐")

    @unittest.skipUnless(os.path.exists(A), "缺少样本")
    def test_tail_tracks_present(self):
        m = vmd.load(A)
        for attr in ("camera_count", "light_count", "shadow_count", "ik_count"):
            self.assertTrue(hasattr(m, attr), "缺 %s 字段" % attr)


class TestConcat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mmdtest ")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @unittest.skipUnless(os.path.exists(A) and os.path.exists(B), "缺少样本")
    def test_byte_identical_repeatable(self):
        o1 = os.path.join(self.tmp, "c1.vmd")
        o2 = os.path.join(self.tmp, "c2.vmd")
        vmd.concat([vmd.load(A), vmd.load(B)], o1, gap=6)
        vmd.concat([vmd.load(A), vmd.load(B)], o2, gap=6)
        self.assertEqual(_sha(o1), _sha(o2), "同一输入两次拼接结果不一致")

    @unittest.skipUnless(os.path.exists(A) and os.path.exists(B), "缺少样本")
    def test_frame_range_and_counts(self):
        out = os.path.join(self.tmp, "c.vmd")
        rep = vmd.concat([vmd.load(A), vmd.load(B)], out, gap=6)
        self.assertEqual(list(rep["spans"][0]["dst_range"]), [0, 446])
        self.assertEqual(rep["spans"][1]["dst_range"][0], 453)
        m = vmd.load(out)
        self.assertTrue(m.tracks_valid)
        self.assertEqual(m.bone_count, rep["bone_records"])

    @unittest.skipUnless(os.path.exists(A) and os.path.exists(B), "缺少样本")
    def test_records_preserved(self):
        """拼接只改帧号，其余字节必须原样。"""
        out = os.path.join(self.tmp, "c.vmd")
        rep = vmd.concat([vmd.load(A), vmd.load(B)], out, gap=6)
        src = len(vmd.load(A).raw) + len(vmd.load(B).raw)
        self.assertGreater(rep["bone_records"], 0)
        self.assertEqual(rep["bone_records"] + rep["morph_records"],
                         vmd.load(A).bone_count + vmd.load(A).morph_count
                         + vmd.load(B).bone_count + vmd.load(B).morph_count)
        self.assertGreater(src, 0)

    @unittest.skipUnless(os.path.exists(A) and os.path.exists(B), "缺少样本")
    def test_path_with_spaces(self):
        """夹具必须带空格：E:\\dsh pr 本身就在踩这个坑。"""
        out = os.path.join(self.tmp, "带 空格.vmd")
        vmd.concat([vmd.load(A), vmd.load(B)], out, gap=6)
        self.assertTrue(os.path.exists(out))

    @unittest.skipUnless(os.path.exists(A) and os.path.exists(EXPR), "缺少样本")
    def test_merge_offset(self):
        base = vmd.load(A)
        expr = vmd.load(EXPR)
        out = os.path.join(self.tmp, "m.vmd")
        vmd.merge(base, expr, out, offset=453)
        m = vmd.load(out)
        frames = []
        d = m.raw
        for i in range(m.morph_count):
            s = m.morph_start + i * vmd.MORPH_RECORD
            frames.append(int.from_bytes(d[s + 15:s + 19], "little"))
        self.assertTrue(frames, "没有表情记录")
        self.assertGreaterEqual(min(frames), 453, "表情没跟随段偏移")


if __name__ == "__main__":
    unittest.main()
