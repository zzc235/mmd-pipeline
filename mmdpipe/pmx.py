"""PMX 2.0 / 2.1 解析器 —— 纯 Python，不依赖 bpy。

两处用途：
  * S0 资产预检 / S1 定义层普查（命令行，不开 Blender）
  * 插件内的 VMD×PMX 命名匹配报告

只读，不改写、不保存。
"""
from __future__ import annotations

import math
import os
import struct
from dataclasses import dataclass, field
from typing import Any

# 骨骼 flag 位
BONE_CONNECT = 0x0001
BONE_IK = 0x0020
BONE_INHERIT_ROT = 0x0100
BONE_INHERIT_MOV = 0x0200
BONE_AXIS = 0x0400
BONE_LOCAL = 0x0800
BONE_EXTERNAL = 0x2000


class PMXError(Exception):
    """PMX 结构异常（越界、未知枚举、长度非法）。"""


class _Reader:
    __slots__ = ("data", "pos")

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def take(self, n: int) -> bytes:
        if n < 0 or self.pos + n > len(self.data):
            raise PMXError("越界读取 pos=%d n=%d size=%d" % (self.pos, n, len(self.data)))
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return struct.unpack("<H", self.take(2))[0]

    def i32(self) -> int:
        return struct.unpack("<i", self.take(4))[0]

    def f32(self) -> float:
        return struct.unpack("<f", self.take(4))[0]

    def f32n(self, n: int) -> list[float]:
        return list(struct.unpack("<%df" % n, self.take(4 * n)))

    def index(self, size: int) -> int:
        if size == 1:
            return self.u8()
        if size == 2:
            return self.u16()
        if size == 4:
            return self.i32()
        raise PMXError("非法索引宽度 %d" % size)

    def text(self, encoding: str) -> str:
        n = self.i32()
        if n < 0 or n > (1 << 22):
            raise PMXError("异常文本长度 %d @%d" % (n, self.pos - 4))
        return self.take(n).decode(encoding, "replace")


@dataclass
class Bone:
    index: int
    name: str
    parent: int
    position: tuple
    flag: int

    @property
    def is_ik(self) -> bool:
        return bool(self.flag & BONE_IK)


@dataclass
class Rigid:
    index: int
    name: str
    bone: int
    group: int
    mask: int
    shape: int
    mode: int
    position: tuple
    size: tuple = (0.0, 0.0, 0.0)
    rotation: tuple = (0.0, 0.0, 0.0)


@dataclass
class Joint:
    index: int
    name: str
    kind: int
    rigid_a: int
    rigid_b: int
    limit_span: float          # 六个限位值的最大绝对值；0 = 限位全 0
    spring_max: float          # 六个弹簧刚度的最大绝对值；0 = 弹簧全 0
    position: tuple = (0.0, 0.0, 0.0)
    fields: dict = field(default_factory=dict)   # 六个限位/弹簧字段的原始值，见 JOINT_LIMIT_OFFSETS

    @property
    def limits_zero(self) -> bool:
        return self.limit_span < 1e-9

    @property
    def springs_zero(self) -> bool:
        return self.spring_max < 1e-9

    @property
    def welded(self) -> bool:
        """限位全 0 且 弹簧全 0 = PMX 里被焊死，不会独立运动。"""
        return self.limits_zero and self.springs_zero


@dataclass
class PMXModel:
    path: str
    version: float
    encoding: str
    additional_uvs: int
    name: str
    name_en: str
    vertex_count: int
    materials: list
    bones: list
    morphs: list
    rigids: list
    joints: list
    triangles: int = 0
    morph_offset_extra: int = 0
    bbox_min: tuple = (0.0, 0.0, 0.0)
    bbox_max: tuple = (0.0, 0.0, 0.0)
    bytes_total: int = 0
    bytes_consumed: int = 0
    tail_error: str | None = None
    raw: bytes = b""
    textures: list = field(default_factory=list)
    rigid_pos_offsets: list = field(default_factory=list)
    rigid_mode_offsets: list = field(default_factory=list)
    joint_pos_offsets: list = field(default_factory=list)

    @property
    def bone_names(self) -> set:
        return {b.name for b in self.bones}

    @property
    def morph_names(self) -> set:
        return set(self.morphs)


def load(path: str) -> PMXModel:
    with open(path, "rb") as fh:
        data = fh.read()
    return parse(data, path)


def _skip_faces(r: _Reader, data: bytes, start: int, field: int, vs: int):
    """面段的计数字段含义因导出器而异：
      A 字段 = 顶点索引总数（MMD 系导出器实测如此）
      B 字段 = 三角形数（PMX 规范原文）
    两个候选都试，判据是"紧接着的纹理表能不能读通"。不写死。
    """
    if field < 0:
        raise PMXError("面数字段非法 %d" % field)
    candidates = [(field, field // 3), (field * 3, field)]
    last = None
    for indices, triangles in candidates:
        end = start + indices * vs
        if end > len(data):
            continue
        probe = _Reader(data)
        probe.pos = end
        try:
            tex_count = probe.i32()
            if not (0 <= tex_count <= 4000):
                raise PMXError("纹理数不合理 %d" % tex_count)
            for _ in range(min(tex_count, 4)):
                ln = probe.i32()
                if ln < 0 or ln > 1024:
                    raise PMXError("纹理名长度不合理 %d" % ln)
                probe.take(ln)
        except PMXError as exc:
            last = exc
            continue
        r.pos = end
        return end, triangles
    raise PMXError("面段无法定位，两个候选都失败：%s" % last)


def _parse_morphs(r: _Reader, encoding: str, vs: int, bs: int,
                  mos: int, rs: int, ms: int, extra: int) -> list:
    """解析表情段。extra = 材质变形每条偏移多出的字节数（导出器差异，实测有 +1）。"""
    count = r.i32()
    if not (0 <= count <= 5000):
        raise PMXError("表情数不合理 %d" % count)
    morphs = []
    for _ in range(count):
        name = r.text(encoding)
        r.text(encoding)
        r.u8()                       # panel
        mtype = r.u8()
        n = r.i32()
        if not (0 <= n <= 500000):
            raise PMXError("表情 %s 的偏移数不合理 %d" % (name, n))
        for _ in range(n):
            if mtype == 0:                       # group
                r.index(mos); r.f32()
            elif mtype == 1:                     # vertex
                r.index(vs); r.f32n(3)
            elif mtype == 2:                     # bone
                r.index(bs); r.f32n(3); r.f32n(4)
            elif 3 <= mtype <= 7:                # uv
                r.index(vs); r.f32n(4)
            elif mtype == 8:                     # material
                r.index(ms)
                r.f32n(4); r.f32n(3); r.f32(); r.f32n(3)
                r.f32n(4); r.f32()
                r.f32n(4); r.f32n(4); r.f32n(4)
                if extra:
                    r.take(extra)
            elif mtype == 9:                     # flip
                r.index(mos); r.f32()
            elif mtype == 10:                    # impulse
                r.index(rs); r.u8(); r.f32n(3); r.f32n(3)
            else:
                raise PMXError("未知 morph 类型 %d" % mtype)
        morphs.append(name)
    return morphs


def parse(data: bytes, path: str = "<memory>") -> PMXModel:
    r = _Reader(data)
    if r.take(4) != b"PMX ":
        raise PMXError("不是 PMX 文件（magic 不符）")
    version = r.f32()
    if not (2.0 <= version < 3.0):
        raise PMXError("不支持的 PMX 版本 %.2f" % version)
    globals_count = r.u8()
    g = list(r.take(globals_count))
    if globals_count < 8:
        raise PMXError("globals 只有 %d 项，需要 8" % globals_count)
    encoding = "utf-16-le" if g[0] == 0 else "utf-8"
    additional_uvs = g[1]
    vs, ts, ms, bs, mos, rs = g[2], g[3], g[4], g[5], g[6], g[7]

    name = r.text(encoding)
    name_en = r.text(encoding)
    r.text(encoding)  # comment
    r.text(encoding)  # comment_en

    vertex_count = r.i32()
    if vertex_count < 0:
        raise PMXError("顶点数非法 %d" % vertex_count)
    vmin = [float("inf")] * 3
    vmax = [float("-inf")] * 3
    for _ in range(vertex_count):
        vpos = r.f32n(3)          # position
        for k in range(3):
            if vpos[k] < vmin[k]:
                vmin[k] = vpos[k]
            if vpos[k] > vmax[k]:
                vmax[k] = vpos[k]
        r.f32n(3)                 # normal
        r.f32n(2)                 # uv
        if additional_uvs:
            r.f32n(additional_uvs * 4)
        wt = r.u8()
        # 注意：权重里的骨骼索引用「骨骼索引宽度 bs」，不是顶点索引宽度 vs。
        # HSR 三个模型的 vs 和 bs 都是 2，写成 vs 也能过；bs=1 的模型会立刻错位。
        if wt == 0:               # BDEF1
            r.index(bs)
        elif wt == 1:             # BDEF2
            r.index(bs); r.index(bs); r.f32()
        elif wt == 2:             # BDEF4
            for _ in range(4):
                r.index(bs)
            r.f32n(4)
        elif wt == 3:             # SDEF
            r.index(bs); r.index(bs); r.f32()
            r.f32n(3); r.f32n(3); r.f32n(3)
        elif wt == 4:             # QDEF
            for _ in range(4):
                r.index(bs)
            r.f32n(4)
        else:
            raise PMXError("未知顶点权重类型 %d @顶点%d" % (wt, _))
        r.f32()                   # edge scale

    face_field = r.i32()
    face_start = r.pos
    after_faces, triangles = _skip_faces(r, data, face_start, face_field, vs)

    tex_count = r.i32()
    textures = [r.text(encoding) for _ in range(tex_count)]

    mat_count = r.i32()
    materials = []
    for _ in range(mat_count):
        mname = r.text(encoding)
        r.text(encoding)
        r.f32n(4)                 # diffuse
        r.f32n(3)                 # specular
        r.f32()
        r.f32n(3)                 # ambient
        r.u8()                    # draw flag
        r.f32n(4)                 # edge color
        r.f32()
        r.index(ts)               # texture
        r.index(ts)               # sphere
        r.u8()                    # sphere mode
        toon_flag = r.u8()
        if toon_flag == 1:
            r.index(ts)
        else:
            r.u8()
        r.text(encoding)          # memo
        r.i32()                   # face count
        materials.append(mname)

    bone_count = r.i32()
    if bone_count < 0:
        raise PMXError("骨骼数非法 %d" % bone_count)
    bones = []
    for i in range(bone_count):
        bname = r.text(encoding)
        r.text(encoding)
        pos = tuple(r.f32n(3))
        parent = r.index(bs)
        r.i32()                   # layer
        flag = r.u16()
        if flag & BONE_CONNECT:
            r.index(bs)
        else:
            r.f32n(3)
        if flag & (BONE_INHERIT_ROT | BONE_INHERIT_MOV):
            r.index(bs)
            r.f32()
        if flag & BONE_AXIS:
            r.f32n(3)
        if flag & BONE_LOCAL:
            r.f32n(3); r.f32n(3)
        if flag & BONE_EXTERNAL:
            r.i32()
        if flag & BONE_IK:
            r.index(bs)           # target
            r.i32()               # loop
            r.f32()               # limit angle
            link_count = r.i32()
            for _ in range(link_count):
                r.index(bs)
                if r.u8() == 1:
                    r.f32n(3); r.f32n(3)
        bones.append(Bone(i, bname, parent, pos, flag))

    model = PMXModel(
        path=path, version=version, encoding=encoding,
        additional_uvs=additional_uvs, name=name, name_en=name_en,
        vertex_count=vertex_count, materials=materials, bones=bones,
        textures=textures, bbox_min=tuple(vmin), bbox_max=tuple(vmax),
        morphs=[], rigids=[], joints=[], triangles=triangles,
        bytes_total=len(data),
    )

    # 以下段结构较脆：失败要如实标记，不能把"解析失败"说成"没有物理"
    rigid_pos_offsets: list = []
    rigid_mode_offsets: list = []
    joint_pos_offsets: list = []
    try:
        morph_start = r.pos
        morphs = []
        disp_count = None
        last_err = None
        for extra in (0, 1, 2):
            probe = _Reader(data)
            probe.pos = morph_start
            try:
                morphs = _parse_morphs(probe, encoding, vs, bs, mos, rs, ms, extra)
                dc = probe.i32()
                if not (0 <= dc <= 200):
                    raise PMXError("表示枠数不合理 %d" % dc)
            except PMXError as exc:
                last_err = exc
                continue
            r.pos = probe.pos
            disp_count = dc
            model.morph_offset_extra = extra
            break
        if disp_count is None:
            raise PMXError("表情段无法对齐（extra=0/1/2 均失败）：%s" % last_err)
        model.morphs = morphs

        for _ in range(disp_count):
            r.text(encoding); r.text(encoding)
            r.u8()                              # 特殊枠フラグ
            n = r.i32()
            for _ in range(n):
                kind = r.u8()                   # 0=骨骼 1=表情
                r.index(mos if kind == 1 else bs)

        rigid_count = r.i32()
        rigids = []
        for i in range(rigid_count):
            rname = r.text(encoding)
            r.text(encoding)
            bone = r.index(bs)
            group = r.u8()
            mask = r.u16()
            shape = r.u8()
            size = tuple(r.f32n(3))
            pos_off = r.pos
            pos = tuple(r.f32n(3))
            rot = tuple(r.f32n(3))
            r.f32()               # mass
            r.f32()               # move attenuation
            r.f32()               # rotation attenuation
            r.f32()               # repulsion
            r.f32()               # friction
            mode_off = r.pos
            mode = r.u8()
            rigids.append(Rigid(i, rname, bone, group, mask, shape, mode, pos,
                                size=size, rotation=rot))
            rigid_pos_offsets.append(pos_off)
            rigid_mode_offsets.append(mode_off)
        model.rigids = rigids

        joint_count = r.i32()
        joints = []
        for i in range(joint_count):
            jname = r.text(encoding)
            r.text(encoding)
            kind = r.u8()
            a = r.index(rs)
            b = r.index(rs)
            joint_pos_offsets.append(r.pos)
            jpos = tuple(r.f32n(3))
            r.f32n(3)                               # rot
            lpm = r.f32n(3); lpx = r.f32n(3)
            lrm = r.f32n(3); lrx = r.f32n(3)
            sp = r.f32n(3); sr = r.f32n(3)
            joints.append(Joint(
                index=i, name=jname, kind=kind, rigid_a=a, rigid_b=b,
                limit_span=max([abs(v) for v in lpm + lpx + lrm + lrx], default=0.0),
                spring_max=max([abs(v) for v in sp + sr], default=0.0),
                position=jpos,
                fields={
                    "move_min": tuple(lpm), "move_max": tuple(lpx),
                    "rot_min": tuple(lrm), "rot_max": tuple(lrx),
                    "spring_move": tuple(sp), "spring_rot": tuple(sr),
                },
            ))
        model.joints = joints
    except PMXError as exc:
        model.tail_error = str(exc)

    model.bytes_consumed = r.pos
    model.raw = data
    model.rigid_pos_offsets = rigid_pos_offsets
    model.rigid_mode_offsets = rigid_mode_offsets
    model.joint_pos_offsets = joint_pos_offsets
    return model


# ---------------------------------------------------------------- 写回

# 刚体 mode 语义（PMX 2.0）：0 = 跟随骨骼（不做物理），1 = 物理演算，2 = 物理演算 + 回填骨骼旋转
RIGID_MODES = (0, 1, 2)

# 关节限位 / 弹簧字段相对 joint_pos_offsets[i] 的字节偏移。
# 顺序取自解析器实际读法（position 12B → rotation 12B → 六段各 12B，关节尾部共 96 B），
# 逐字节实测过，不按 PMX 规范推断。**spring_rot 是 +84**：初版写 +78 会落在
# spring_move 第 3 个 float 内部，写进去 PMX 仍能解析、spring_max 仍读 0.0，语义字段看不出异常
# （2026-11-16 勘误，证据见 tests/test_pmx_patch.py 的窗口断言）。
JOINT_LIMIT_OFFSETS = {
    "move_min": 24,
    "move_max": 36,
    "rot_min": 48,
    "rot_max": 60,
    "spring_move": 72,
    "spring_rot": 84,
}
JOINT_LIMIT_WIDTH = 12          # 3f


def diff_offsets(a: bytes, b: bytes) -> list:
    """逐字节比较，返回所有不同字节的偏移。长度不同直接报错——补丁不许改文件长度。"""
    if len(a) != len(b):
        raise PMXError("字节长度不同：%d vs %d" % (len(a), len(b)))
    return [i for i in range(len(a)) if a[i] != b[i]]


def _check_joint_limit(model, joint_limit) -> dict:
    """校验并预打包 joint_limit 补丁：{关节索引: {字段名: (字节偏移, 12 字节载荷)}}。

    写前用解析时记下的原始值回读比对（按 bytes，不比 float——NaN / ±0.0 都要逐位对齐），
    不一致说明偏移过期（模型换过），拒绝写，而不是把别的字段改坏。
    """
    limits: dict = {}
    for idx, spec in (joint_limit or {}).items():
        if isinstance(idx, bool) or not isinstance(idx, int):
            raise PMXError("关节索引必须是整数，收到 %r" % (idx,))
        if not (0 <= idx < len(model.joints)):
            raise PMXError("关节索引越界 %d（joint_limit 补丁，共 %d 个关节）"
                           % (idx, len(model.joints)))
        if not isinstance(spec, dict):
            raise PMXError("关节 %d 的 joint_limit 必须是 dict，收到 %s"
                           % (idx, type(spec).__name__))
        unknown = sorted(k for k in spec if k not in JOINT_LIMIT_OFFSETS)
        if unknown:
            raise PMXError("关节 %d 含未知字段 %s（只接受 %s）"
                           % (idx, unknown, sorted(JOINT_LIMIT_OFFSETS)))
        base = model.joint_pos_offsets[idx]
        parsed_fields = model.joints[idx].fields
        packed: dict = {}
        for name, val in spec.items():
            if isinstance(val, (str, bytes)) or not hasattr(val, "__len__"):
                raise PMXError("关节 %d 的 %s 必须是 3 个数，收到 %r" % (idx, name, val))
            vals = tuple(val)
            if len(vals) != 3:
                raise PMXError("关节 %d 的 %s 必须正好 3 个数，收到 %d 个"
                               % (idx, name, len(vals)))
            for v in vals:
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    raise PMXError("关节 %d 的 %s 含非法值 %r（只接受 int/float，bool 拒绝）"
                                   % (idx, name, v))
                if not math.isfinite(v):
                    raise PMXError("关节 %d 的 %s 含非有限值 %r（拒绝写 NaN/Inf）"
                                   % (idx, name, v))
            off = base + JOINT_LIMIT_OFFSETS[name]
            if off + JOINT_LIMIT_WIDTH > len(model.raw):
                raise PMXError("关节 %d 的 %s 偏移越界：%d（文件 %d 字节）"
                               % (idx, name, off, len(model.raw)))
            parsed = parsed_fields.get(name)
            if parsed is None:
                raise PMXError("关节 %d 缺少 %s 的解析记录，无法校验偏移" % (idx, name))
            if struct.pack("<3f", *parsed) != model.raw[off:off + JOINT_LIMIT_WIDTH]:
                raise PMXError("关节 %d 的 %s 偏移过期：字节里 %s，解析记录 %r"
                               % (idx, name, list(model.raw[off:off + JOINT_LIMIT_WIDTH]), parsed))
            packed[name] = (off, struct.pack("<3f", *(float(v) for v in vals)))
        limits[idx] = packed
    return limits


def patch_save(model, dst: str, rigid_pos: dict | None = None,
               joint_pos: dict | None = None,
               rigid_mode: dict | None = None,
               joint_limit: dict | None = None) -> str:
    """只改指定刚体的 mode / 刚体与关节的位置浮点数 / 关节限位与弹簧，其余字节原样保留。

    不做整份重序列化——那是"写坏文件"的主要来源（附加 UV、morph 偏移都对不上）。

    安全约定：**永远不覆盖源文件**。dst 与解析来源同一路径直接拒绝。
    rigid_pos / joint_pos: {index: (x, y, z)}
    rigid_mode: {index: 0/1/2}，只改那一个字节；写之前用解析时记下的偏移回读旧值，
                不一致说明偏移过期（模型换过）→ 拒绝写，而不是把别的字段改坏。
    joint_limit: {index: {"move_min": (x, y, z), "move_max": ..., "rot_min": ..., 
                 "rot_max": ..., "spring_move": ..., "spring_rot": ...}}，字段名照
                 JOINT_LIMIT_OFFSETS；缺字段不写，传 None 不写。同样写前回读校验。
    """
    if not model.raw:
        raise PMXError("解析时没保留原始字节，不能安全写回")
    if os.path.abspath(dst) == os.path.abspath(model.path):
        raise PMXError("拒绝覆盖源文件：dst 与源 PMX 相同（%s）" % dst)
    modes = dict(rigid_mode or {})
    for idx, mode in modes.items():
        if not (0 <= idx < len(model.rigid_mode_offsets)):
            raise PMXError("刚体索引越界 %d（mode 补丁）" % idx)
        if isinstance(mode, bool) or not isinstance(mode, int):
            raise PMXError("非法刚体 mode %r（只接受整数 0/1/2）" % (mode,))
        if mode not in RIGID_MODES:
            raise PMXError("非法刚体 mode %d（只接受 0/1/2）" % mode)
        if model.rigid_mode_offsets[idx] >= len(model.raw):
            raise PMXError("刚体 %d 的 mode 偏移越界：%d"
                           % (idx, model.rigid_mode_offsets[idx]))
        old = model.raw[model.rigid_mode_offsets[idx]]
        if old != model.rigids[idx].mode:
            raise PMXError("刚体 %d 的 mode 偏移过期：字节里是 %d，解析记录是 %d"
                           % (idx, old, model.rigids[idx].mode))
    limits = _check_joint_limit(model, joint_limit)

    buf = bytearray(model.raw)
    for idx, mode in modes.items():
        buf[model.rigid_mode_offsets[idx]] = mode
    for idx, pos in (rigid_pos or {}).items():
        if not (0 <= idx < len(model.rigid_pos_offsets)):
            raise PMXError("刚体索引越界 %d" % idx)
        struct.pack_into("<3f", buf, model.rigid_pos_offsets[idx], *pos)
    for idx, pos in (joint_pos or {}).items():
        if not (0 <= idx < len(model.joint_pos_offsets)):
            raise PMXError("关节索引越界 %d" % idx)
        struct.pack_into("<3f", buf, model.joint_pos_offsets[idx], *pos)
    for _idx, fields in limits.items():
        for _name, (off, payload) in fields.items():
            buf[off:off + JOINT_LIMIT_WIDTH] = payload
    os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)
    with open(dst, "wb") as fh:
        fh.write(bytes(buf))
    return dst


# ---------------------------------------------------------------- 普查

def _collide_bitset(a: Rigid, b: Rigid) -> bool:
    """掩码 bit=1 视为"参与碰撞"。"""
    return bool((a.mask >> b.group) & 1) and bool((b.mask >> a.group) & 1)


def _collide_inverted(a: Rigid, b: Rigid) -> bool:
    """掩码 bit=1 视为"忽略"（mmd_tools 的 ignore 布尔语义）。"""
    return not ((a.mask >> b.group) & 1) and not ((b.mask >> a.group) & 1)


def census(model: PMXModel) -> dict:
    rigids = model.rigids
    modes: dict = {}
    groups: dict = {}
    masks: dict = {}
    for rb in rigids:
        modes[rb.mode] = modes.get(rb.mode, 0) + 1
        groups[rb.group] = groups.get(rb.group, 0) + 1
        masks[rb.mask] = masks.get(rb.mask, 0) + 1

    same_true = same_inv = 0
    all_true = all_inv = 0
    for i in range(len(rigids)):
        a = rigids[i]
        for j in range(i + 1, len(rigids)):
            b = rigids[j]
            if _collide_bitset(a, b):
                all_true += 1
                if a.group == b.group:
                    same_true += 1
            if _collide_inverted(a, b):
                all_inv += 1
                if a.group == b.group:
                    same_inv += 1

    referenced = set()
    joint_of: dict = {}
    for j in model.joints:
        for idx in (j.rigid_a, j.rigid_b):
            if 0 <= idx < len(rigids):
                referenced.add(idx)
                joint_of.setdefault(idx, []).append(j)

    frozen_suspects = []
    for rb in rigids:
        if rb.mode != 2:
            continue
        js = joint_of.get(rb.index)
        if js and all(j.limits_zero and j.springs_zero for j in js):
            frozen_suspects.append({"index": rb.index, "name": rb.name, "joints": len(js)})

    return {
        "name": model.name,
        "version": model.version,
        "encoding": model.encoding,
        "additional_uvs": model.additional_uvs,
        "vertices": model.vertex_count,
        "triangles": model.triangles,
        "bones": len(model.bones),
        "materials": len(model.materials),
        "morphs": len(model.morphs),
        "rigids": len(rigids),
        "joints": len(model.joints),
        "mode_distribution": dict(sorted(modes.items())),
        "group_distribution": dict(sorted(groups.items())),
        "distinct_masks": len(masks),
        "top_masks": [{"mask": m, "count": c} for m, c in
                      sorted(masks.items(), key=lambda kv: -kv[1])[:5]],
        "same_group_pairs_bitset": same_true,
        "same_group_pairs_inverted": same_inv,
        "all_pairs_bitset": all_true,
        "all_pairs_inverted": all_inv,
        "resolved_semantics": ("bit=1 参与碰撞"
                               if same_true <= same_inv
                               else "bit=1 表示忽略"),
        "joint_referenced_rigids": len(referenced),
        "frozen_suspects": frozen_suspects,
        "bytes_total": model.bytes_total,
        "bytes_consumed": model.bytes_consumed,
        "tail_error": model.tail_error,
    }
