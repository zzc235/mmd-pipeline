"""刚体 mode + 关节限位副本补丁的字节级测试。

判据全部落在字节上：改完长度不变、diff 位置数 = 目标 mode 字段数、非 diff 区域逐字节一致；
关节限位另外断言「每个字段单独写的字节窗口」与「不传参时输出与源逐字节相同」。
不跑 Blender，不做整份重序列化。
"""
import math
import os
import struct
import tempfile
import unittest

from mmdpipe import pmx

FEIXIAO = r"E:\blender模型\没有外套本家模型\星穹铁道—飞霄（无外套）.pmx"
TARGETS = list(range(24, 30))
JOINT_FIELDS = ("move_min", "move_max", "rot_min", "rot_max", "spring_move", "spring_rot")


def _text(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("<i", len(b)) + b


def build_pmx(modes, name_pad: int = 0, joints=None) -> bytes:
    """造一个最小但能被 pmx.parse 完整解析的 PMX 2.0：只有骨/刚体（/关节），没有顶点、面、材质、表情。

    name_pad 只改文本长度，用来造"同一份数据但字节偏移不同"的第二个模型（测偏移过期保护）。
    joints: None → 0 个关节；list[dict] → 每个 dict 可含 JOINT_LIMIT_OFFSETS 的六个字段，值给 3 元组。
    """
    pad = "p" * name_pad
    joint_specs = list(joints or [])
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
    out += struct.pack("<i", len(joint_specs))   # 关节
    for i, spec in enumerate(joint_specs):
        out += _text("j%s%d" % (pad, i)) + _text("j%d" % i)
        out += struct.pack("<B", 0)              # kind: 6DOF spring
        out += struct.pack("<i", i % 2) + struct.pack("<i", (i + 1) % 2)   # rigid a/b
        out += struct.pack("<3f", 0.0, 0.0, 0.0)   # position
        out += struct.pack("<3f", 0.0, 0.0, 0.0)   # rotation
        for name in ("move_min", "move_max", "rot_min", "rot_max", "spring_move", "spring_rot"):
            out += struct.pack("<3f", *tuple(spec.get(name, (0.0, 0.0, 0.0))))
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


def build_joint_pmx(name_pad: int = 0, joint_count: int = 3) -> bytes:
    """三个关节，每个关节六个字段都非零且彼此不同（方便断言"只改了我写的那个字段"）。"""
    joints = []
    for i in range(joint_count):
        joints.append({name: (float(i) + 1.0, float(i) + 2.0, float(i) + 3.0)
                       for name in JOINT_FIELDS})
    return build_pmx([2, 2], name_pad=name_pad, joints=joints)


class TestJointLimitPatch(unittest.TestCase):
    """joint_limit 的六条验收：窗口、no-op、幂等、越界、类型、过期偏移。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = os.path.join(self.tmp.name, "joints.pmx")
        with open(self.src, "wb") as fh:
            fh.write(build_joint_pmx())
        self.model = pmx.load(self.src)

    def dst(self, name="patched.pmx"):
        return os.path.join(self.tmp.name, name)

    def read(self, path):
        with open(path, "rb") as fh:
            return fh.read()

    def test_each_field_lands_in_its_own_window(self):
        """每个字段单独写一次：diff 必须全部落在 [base+off, base+off+12) 内，且只改这个字段。"""
        for name in JOINT_FIELDS:
            with self.subTest(field=name):
                base = self.model.joint_pos_offsets[0]
                off = base + pmx.JOINT_LIMIT_OFFSETS[name]
                new = (11.0, 12.0, 13.0)
                path = pmx.patch_save(self.model, self.dst("w_%s.pmx" % name),
                                      joint_limit={0: {name: new}})
                out = self.read(path)
                self.assertEqual(len(out), len(self.model.raw), "补丁不能改变文件长度")
                diffs = pmx.diff_offsets(self.model.raw, out)
                self.assertTrue(diffs, "%s 写新值必须产生字节差异" % name)
                self.assertGreaterEqual(min(diffs), off,
                                        "%s 的差异不能早于字段起点" % name)
                self.assertLess(max(diffs), off + pmx.JOINT_LIMIT_WIDTH,
                                "%s 的差异不能越过字段末尾（+78 与 +84 就靠这条区分）" % name)
                again = pmx.parse(out, path)
                self.assertEqual(again.joints[0].fields[name], new, "重解析应读到新值")
                for other in JOINT_FIELDS:
                    if other == name:
                        continue
                    self.assertEqual(again.joints[0].fields[other],
                                     self.model.joints[0].fields[other],
                                     "%s 不能让 %s 跟着变" % (name, other))

    def test_all_six_windows_are_disjoint(self):
        """六段字段的窗口两两不重叠；否则 +78 会压到 spring_move 上（初版那个错值）。"""
        base = self.model.joint_pos_offsets[0]
        windows = {}
        for name in JOINT_FIELDS:
            off = base + pmx.JOINT_LIMIT_OFFSETS[name]
            windows[name] = set(range(off, off + pmx.JOINT_LIMIT_WIDTH))
        names = list(JOINT_FIELDS)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                self.assertFalse(windows[a] & windows[b],
                                 "%s 与 %s 的字节窗口重叠" % (a, b))
        self.assertEqual(pmx.JOINT_LIMIT_OFFSETS["spring_rot"], 84,
                         "spring_rot 必须是 +84（初版 +78 落在 spring_move 内部）")

    def test_multi_joint_patch_only_touches_each_window(self):
        limit = {0: {"move_min": (9.0, 9.0, 9.0)}, 2: {"spring_rot": (7.0, 7.0, 7.0)}}
        path = pmx.patch_save(self.model, self.dst("multi.pmx"), joint_limit=limit)
        out = self.read(path)
        self.assertEqual(len(out), len(self.model.raw))
        expected = set()
        for idx, spec in limit.items():
            base = self.model.joint_pos_offsets[idx]
            for name in spec:
                off = base + pmx.JOINT_LIMIT_OFFSETS[name]
                expected |= set(range(off, off + pmx.JOINT_LIMIT_WIDTH))
        diffs = set(pmx.diff_offsets(self.model.raw, out))
        self.assertTrue(diffs)
        self.assertFalse(diffs - expected, "出现目标窗口外的字节改动：%s" % sorted(diffs - expected))
        again = pmx.parse(out, path)
        self.assertEqual(again.joints[0].fields["move_min"], (9.0, 9.0, 9.0))
        self.assertEqual(again.joints[2].fields["spring_rot"], (7.0, 7.0, 7.0))
        self.assertEqual(again.joints[1].fields, self.model.joints[1].fields,
                         "没点名的关节一个字节都不能动")

    def test_writing_same_value_changes_nothing(self):
        original = self.model.joints[0].fields["move_max"]
        path = pmx.patch_save(self.model, self.dst("same.pmx"),
                              joint_limit={0: {"move_max": tuple(original)}})
        self.assertEqual(pmx.diff_offsets(self.model.raw, self.read(path)), [],
                         "写同值必须零差异")

    def test_no_patch_arguments_is_byte_identical(self):
        """不传任何补丁参数：输出与源逐字节相同（防"顺手把 24 个 float 整体重打包"）。"""
        for kwargs in ({}, {"rigid_mode": None}, {"rigid_pos": None}, {"joint_pos": None},
                       {"joint_limit": None}, {"rigid_mode": {}, "joint_limit": {}}):
            with self.subTest(kwargs=kwargs):
                path = pmx.patch_save(self.model, self.dst("noop.pmx"), **kwargs)
                self.assertEqual(self.read(path), self.model.raw,
                                 "空补丁必须逐字节相同（%r）" % (kwargs,))

    def test_rejects_out_of_range_index(self):
        for bad in (3, 99, -1, "0", True, 1.0):
            with self.assertRaises(pmx.PMXError, msg="index=%r 应被拒绝" % (bad,)):
                pmx.patch_save(self.model, self.dst("bad_i.pmx"),
                               joint_limit={bad: {"move_min": (1.0, 1.0, 1.0)}})

    def test_rejects_bad_values(self):
        cases = [
            ("不是 dict", 0, "not-a-dict"),
            ("未知字段", 0, {"move_minimum": (1.0, 1.0, 1.0)}),
            ("字段名拼错大小写", 0, {"move_Min": (1.0, 1.0, 1.0)}),
            ("值不是三元组", 0, {"move_min": (1.0, 2.0)}),
            ("值不是序列", 0, {"move_min": 1.0}),
            ("字符串值", 0, {"move_min": "abc"}),
            ("含 bool", 0, {"move_min": (True, 2.0, 3.0)}),
            ("含字符串元素", 0, {"move_min": (1.0, "2", 3.0)}),
            ("NaN", 0, {"move_min": (float("nan"), 2.0, 3.0)}),
            ("+Inf", 0, {"rot_max": (float("inf"), 2.0, 3.0)}),
        ]
        for label, idx, spec in cases:
            with self.subTest(case=label):
                with self.assertRaises(pmx.PMXError, msg="%s 应被拒绝" % label):
                    pmx.patch_save(self.model, self.dst("bad_v.pmx"), joint_limit={idx: spec})

    def test_rejects_stale_offsets(self):
        """偏移过期（拿 A 模型的偏移写 B 模型）必须报错，不能改坏别的字段。"""
        other = os.path.join(self.tmp.name, "other.pmx")
        with open(other, "wb") as fh:
            fh.write(build_joint_pmx(name_pad=7))
        stale = pmx.load(other)
        self.assertNotEqual(stale.joint_pos_offsets, self.model.joint_pos_offsets,
                            "pad 必须真的把偏移挪开，否则这条测试没意义")
        this_model = pmx.load(self.src)
        this_model.joint_pos_offsets = stale.joint_pos_offsets
        with self.assertRaises(pmx.PMXError):
            pmx.patch_save(this_model, self.dst("stale.pmx"),
                           joint_limit={i: {"move_min": (1.0, 1.0, 1.0)} for i in range(3)})

    def test_parse_records_all_six_fields(self):
        for i, joint in enumerate(self.model.joints):
            for name in JOINT_FIELDS:
                off = self.model.joint_pos_offsets[i] + pmx.JOINT_LIMIT_OFFSETS[name]
                packed = struct.pack("<3f", *joint.fields[name])
                self.assertEqual(self.model.raw[off:off + 12], packed,
                                 "关节 %d 的 %s 解析值与字节不一致" % (i, name))
        self.assertIsNone(self.model.tail_error)


@unittest.skipUnless(os.path.exists(FEIXIAO), "缺少飞霄（无外套）模型")
class TestFeixiaoPatch(unittest.TestCase):
    """真实模型：S3 的目标就是索引 24–29 的 mode 2→0；关节限位在 389 个关节上按字节复核。"""

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

    def test_joint_field_offsets_match_bytes_on_all_joints(self):
        """389 个关节逐个核对六个字段的偏移：这是 +84 唯一能在真实模型上验的方式
        （飞霄弹簧全为 0，写 +78 与 +84 在语义字段上都读 0.0，只有字节能区分）。"""
        checked = 0
        for i, joint in enumerate(self.model.joints):
            base = self.model.joint_pos_offsets[i]
            for name, off in pmx.JOINT_LIMIT_OFFSETS.items():
                packed = struct.pack("<3f", *joint.fields[name])
                self.assertEqual(self.model.raw[base + off:base + off + 12], packed,
                                 "关节 %d 的 %s 偏移与字节不符" % (i, name))
                checked += 1
        self.assertEqual(checked, len(self.model.joints) * 6)

    def test_patch_move_limit_on_real_joint(self):
        target = None
        for i, joint in enumerate(self.model.joints):
            if joint.fields["move_min"] != (0.0, 0.0, 0.0) \
                    or joint.fields["move_max"] != (0.0, 0.0, 0.0):
                target = i
                break
        self.assertIsNotNone(target, "飞霄应有 transl 限位非零的关节")
        current = self.model.joints[target].fields["move_min"]
        new = tuple(round(v + 0.25, 6) for v in current)
        dst = os.path.join(self.tmp.name, "feixiao_move_limit.pmx")
        pmx.patch_save(self.model, dst, joint_limit={target: {"move_min": new}})
        again = pmx.load(dst)
        base = self.model.joint_pos_offsets[target]
        off = base + pmx.JOINT_LIMIT_OFFSETS["move_min"]
        diffs = diff_positions(self.model.raw, again.raw)
        self.assertTrue(diffs, "写新限位必须产生字节差异")
        self.assertGreaterEqual(min(diffs), off)
        self.assertLess(max(diffs), off + 12)
        self.assertEqual(struct.pack("<3f", *again.joints[target].fields["move_min"]),
                         struct.pack("<3f", *new), "重解析应读到写入的 float32 值")
        self.assertEqual(again.joints[target].fields["move_max"],
                         self.model.joints[target].fields["move_max"], "另一个限位不能变")
        self.assertIsNone(again.tail_error)


if __name__ == "__main__":
    unittest.main()
