"""刚体 mode 副本补丁（S3 的核心手段）的字节级测试。

判据全部落在字节上：改完长度不变、diff 位置数 = 目标 mode 字段数、非 diff 区域逐字节一致。
不跑 Blender，不做整份重序列化。
"""
import os
import struct
import tempfile
import unittest

from mmdpipe import pmx

FEIXIAO = r"E:\blender模型\没有外套本家模型\星穹铁道—飞霄（无外套）.pmx"
TARGETS = list(range(24, 30))


def _text(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("<i", len(b)) + b


def build_pmx(modes, name_pad: int = 0) -> bytes:
    """造一个最小但能被 pmx.parse 完整解析的 PMX 2.0：只有骨/刚体，没有顶点、面、材质、表情。

    name_pad 只改文本长度，用来造"同一份数据但字节偏移不同"的第二个模型（测偏移过期保护）。
    """
    pad = "p" * name_pad
    out = bytearray()
    out += b"PMX "
    out += struct.pack("<f", 2.0)
    out += struct.pack("<B", 8)
    out += bytes((1, 0, 4, 4, 4, 4, 4, 4))       # utf-8, no extra uv, vs/ts/ms/bs/mos/rs = 4
    out += _text("patch-probe" + pad) + _text("patch-probe") + _text("") + _text("")
    out += struct.pack("<i", 0)                  # 顶点
    out += struct.pack("<i", 0)                  # 面字段 0 → 面 0 个
    out += struct.pack("<i", 0)                  # 纹理表
    out += struct.pack("<i", 0)                  # 材质
    out += struct.pack("<i", 2)                  # 骨 2 根
    for i in range(2):
        out += _text("b%s%d" % (pad, i)) + _text("b%d" % i)
        out += struct.pack("<3f", 0.0, float(i), 0.0)
        out += struct.pack("<i", i - 1)          # parent
        out += struct.pack("<i", 0)              # layer
        out += struct.pack("<H", 0)              # flag：无连接/无 IK/无附加
        out += struct.pack("<3f", 0.0, 0.0, 0.0)  # 无 CONNECT → 尾部偏移
    out += struct.pack("<i", 0)                  # 表情
    out += struct.pack("<i", 0)                  # 表示枠
    out += struct.pack("<i", len(modes))         # 刚体
    for i, mode in enumerate(modes):
        out += _text("r%s%d" % (pad, i)) + _text("r%d" % i)
        out += struct.pack("<i", i % 2)          # bone
        out += struct.pack("<B", i % 16)         # group
        out += struct.pack("<H", (1 << (i % 16)))  # mask
        out += struct.pack("<B", i % 2)          # shape
        out += struct.pack("<3f", 0.1, 0.2, 0.3)   # size
        out += struct.pack("<3f", float(i), 0.5, 1.5)  # pos
        out += struct.pack("<3f", 0.0, 0.0, 0.0)   # rot
        out += struct.pack("<5f", 1.0, 0.5, 0.5, 0.0, 0.5)
        out += struct.pack("<B", mode)
    out += struct.pack("<i", 0)                  # 关节
    return bytes(out)


def diff_positions(a: bytes, b: bytes) -> list:
    return [i for i in range(min(len(a), len(b))) if a[i] != b[i]]


class TestSyntheticPatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = os.path.join(self.tmp.name, "src.pmx")
        with open(self.src, "wb") as fh:
            fh.write(build_pmx([2] * 6 + [0, 1, 2, 2]))
        self.model = pmx.load(self.src)

    def dst(self, name="patched.pmx"):
        return os.path.join(self.tmp.name, name)

    def test_parse_records_mode_offsets(self):
        self.assertEqual(len(self.model.rigid_mode_offsets), 10)
        for off, rb in zip(self.model.rigid_mode_offsets, self.model.rigids):
            self.assertEqual(self.model.raw[off], rb.mode, "偏移应指向 mode 字节本身")
        self.assertIsNone(self.model.tail_error)

    def test_patch_six_modes(self):
        target = list(range(6))
        changed = {i: 0 for i in target}
        dst = pmx.patch_save(self.model, self.dst(), rigid_mode=changed)
        with open(dst, "rb") as fh:
            out = fh.read()
        self.assertEqual(len(out), len(self.model.raw), "补丁不能改变文件长度")
        again = pmx.parse(out, dst)
        self.assertIsNone(again.tail_error)
        for i in target:
            self.assertEqual(again.rigids[i].mode, 0, "目标刚体 %d 应变成 mode0" % i)
        for i in range(6, 10):
            self.assertEqual(again.rigids[i].mode, self.model.rigids[i].mode,
                             "非目标刚体 %d 的 mode 不能变" % i)
        diffs = diff_positions(self.model.raw, out)
        expected = sorted(self.model.rigid_mode_offsets[i] for i in target)
        self.assertEqual(diffs, expected, "变更字节数必须等于目标 mode 字段数")
        for i, off in enumerate(self.model.rigid_mode_offsets):
            if i in target:
                continue
            self.assertEqual(out[off], self.model.raw[off], "非目标 mode 字节不能变")

    def test_patch_keeps_other_bytes(self):
        out_path = pmx.patch_save(self.model, self.dst(), rigid_mode={3: 0})
        with open(out_path, "rb") as fh:
            out = fh.read()
        self.assertEqual(diff_positions(self.model.raw, out),
                         [self.model.rigid_mode_offsets[3]])

    def test_patch_is_idempotent_with_empty_patch(self):
        out_path = pmx.patch_save(self.model, self.dst())
        with open(out_path, "rb") as fh:
            self.assertEqual(fh.read(), self.model.raw)

    def test_rigid_pos_patch_still_works(self):
        out_path = pmx.patch_save(self.model, self.dst(), rigid_pos={2: (9.0, 8.0, 7.0)})
        again = pmx.load(out_path)
        self.assertEqual(tuple(round(v, 4) for v in again.rigids[2].position), (9.0, 8.0, 7.0))

    def test_rejects_overwriting_source(self):
        with self.assertRaises(pmx.PMXError):
            pmx.patch_save(self.model, self.src, rigid_mode={0: 0})

    def test_rejects_illegal_mode(self):
        for bad in (3, -1, 255, 1.0, "0", True):
            with self.assertRaises(pmx.PMXError, msg="mode=%r 应被拒绝" % (bad,)):
                pmx.patch_save(self.model, self.dst("bad_%s.pmx" % str(bad)), rigid_mode={0: bad})

    def test_rejects_illegal_index(self):
        for bad in (10, -1, 999):
            with self.assertRaises(pmx.PMXError, msg="index=%r 应被拒绝" % (bad,)):
                pmx.patch_save(self.model, self.dst("bad_i%s.pmx" % bad), rigid_mode={bad: 0})

    def test_rejects_stale_offsets(self):
        """偏移过期（用 A 模型的偏移去写 B 模型）必须报错，不能改坏别的字段。"""
        other = os.path.join(self.tmp.name, "other.pmx")
        with open(other, "wb") as fh:
            fh.write(build_pmx([2] * 10, name_pad=7))
        stale = pmx.load(other)
        self.assertNotEqual(stale.rigid_mode_offsets, self.model.rigid_mode_offsets,
                            "pad 必须真的把偏移挪开，否则这条测试没意义")
        self.model.rigid_mode_offsets = stale.rigid_mode_offsets
        with self.assertRaises(pmx.PMXError):
            pmx.patch_save(self.model, self.dst("stale.pmx"),
                           rigid_mode={i: 0 for i in range(10)})

    def test_offsets_are_contiguous_mode_bytes(self):
        """mode 偏移 = 位置偏移 + 44（pos12+rot12+mass/att/rep/fric 20），互相交叉校验。"""
        for off, pos_off in zip(self.model.rigid_mode_offsets, self.model.rigid_pos_offsets):
            self.assertEqual(off - pos_off, 44)


@unittest.skipUnless(os.path.exists(FEIXIAO), "缺少飞霄（无外套）模型")
class TestFeixiaoPatch(unittest.TestCase):
    """真实模型：S3 的目标就是索引 24–29 的 mode 2→0。"""

    @classmethod
    def setUpClass(cls):
        cls.model = pmx.load(FEIXIAO)
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_targets_are_six_mode2(self):
        self.assertGreater(len(self.model.rigids), 30)
        targets = [self.model.rigids[i] for i in TARGETS]
        self.assertEqual([r.mode for r in targets], [2] * 6)
        self.assertEqual([r.name for r in targets],
                         ["右胸", "右胸１", "右胸２", "左胸", "左胸１", "左胸２"])
        # PMX 里的原名就是右胸/左胸；mmd_tools 的 rename_bones=True 在导入时才改成 胸.R/胸.L
        self.assertEqual([self.model.bones[r.bone].name for r in targets],
                         ["右胸", "右胸１", "右胸２", "左胸", "左胸１", "左胸２"])

    def test_patch_changes_exactly_six_bytes(self):
        dst = os.path.join(self.tmp.name, "feixiao_s3_mode0.pmx")
        pmx.patch_save(self.model, dst, rigid_mode={i: 0 for i in TARGETS})
        again = pmx.load(dst)
        self.assertIsNone(again.tail_error)
        self.assertEqual(len(again.raw), len(self.model.raw))
        self.assertEqual([r.mode for r in again.rigids[:6]], [0] * 6)
        for i in TARGETS:
            self.assertEqual(again.rigids[i].mode, 0)
        diffs = diff_positions(self.model.raw, again.raw)
        self.assertEqual(diffs, sorted(self.model.rigid_mode_offsets[i] for i in TARGETS))
        others_src = [(i, r.mode) for i, r in enumerate(self.model.rigids) if i not in TARGETS]
        others_dst = [(i, r.mode) for i, r in enumerate(again.rigids) if i not in TARGETS]
        self.assertEqual(others_src, others_dst, "非目标刚体 mode 必须全部不变")


if __name__ == "__main__":
    unittest.main()
