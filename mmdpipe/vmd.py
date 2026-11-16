"""VMD 解析器 —— 纯 Python，不依赖 bpy。

只回答三件事：这个动作动了哪些骨、动了多少帧、有没有表情轨。
另外提供字节级合并：动作的骨骼段 + 表情文件的表情段。
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field

MAGIC_V2 = b"Vocaloid Motion Data 0002"
MAGIC_V1 = b"Vocaloid Motion Data file"

BONE_RECORD = 111
MORPH_RECORD = 23
CAMERA_RECORD = 61
LIGHT_RECORD = 28
SHADOW_RECORD = 9
IK_RECORD = 21


class VMDError(Exception):
    """VMD 结构异常。"""


@dataclass
class VMDMotion:
    path: str
    magic: str
    model_name: str
    bone_tracks: dict = field(default_factory=dict)       # 骨名 -> 关键帧条数
    bone_last_frame: dict = field(default_factory=dict)   # 骨名 -> 最后一帧
    bone_first_frame: dict = field(default_factory=dict)
    morph_tracks: dict = field(default_factory=dict)      # 表情名 -> 条数
    bytes_total: int = 0
    # 段偏移（用于字节级拼接，避免重新编码帧数据）
    raw: bytes = b""
    bone_count: int = 0
    morph_count: int = 0
    bone_start: int = 0
    morph_start: int = 0
    tail_start: int = 0
    tail_end: int = 0
    tracks_valid: bool = False
    camera_count: int = 0
    camera_start: int = 0
    camera_frames: list = field(default_factory=list)
    light_count: int = 0
    light_start: int = 0
    shadow_count: int = 0
    shadow_start: int = 0
    ik_count: int = 0
    ik_start: int = 0
    ik_frames: list = field(default_factory=list)
    camera_records: list = field(default_factory=list)   # [(frame, bytes)]
    light_records: list = field(default_factory=list)
    shadow_records: list = field(default_factory=list)
    ik_records: list = field(default_factory=list)

    @property
    def bone_end(self) -> int:
        return self.bone_start + self.bone_count * BONE_RECORD

    @property
    def morph_end(self) -> int:
        return self.morph_start + self.morph_count * MORPH_RECORD

    @property
    def bone_names(self) -> set:
        return set(self.bone_tracks)

    @property
    def frame_range(self) -> tuple:
        if not self.bone_last_frame:
            return (0, 0)
        return (min(self.bone_first_frame.values()),
                max(self.bone_last_frame.values()))

    @property
    def keyframes(self) -> int:
        return sum(self.bone_tracks.values())


def load(path: str) -> VMDMotion:
    with open(path, "rb") as fh:
        data = fh.read()
    return parse(data, path)


def parse(data: bytes, path: str = "<memory>") -> VMDMotion:
    if len(data) < 40:
        raise VMDError("文件太小，不是 VMD")
    head = data[0:30]
    if head.startswith(MAGIC_V2):
        name_len = 20
        magic = "0002"
    elif head.startswith(MAGIC_V1):
        name_len = 10
        magic = "0001"
    else:
        raise VMDError("magic 不符: %r" % head[:26])

    model_name = data[30:30 + name_len].split(b"\x00")[0].decode("cp932", "replace")
    pos = 30 + name_len

    def u32(p):
        if p + 4 > len(data):
            raise VMDError("越界读取计数 @%d" % p)
        return struct.unpack_from("<I", data, p)[0], p + 4

    bone_count, pos = u32(pos)
    if bone_count * BONE_RECORD + pos > len(data):
        raise VMDError("骨骼帧数 %d 超出文件长度" % bone_count)

    motion = VMDMotion(path=path, magic=magic, model_name=model_name,
                       bytes_total=len(data), raw=data,
                       bone_count=bone_count, bone_start=pos)

    for _ in range(bone_count):
        raw_name = data[pos:pos + 15].split(b"\x00")[0]
        name = raw_name.decode("cp932", "replace")
        frame = struct.unpack_from("<I", data, pos + 15)[0]
        pos += BONE_RECORD
        motion.bone_tracks[name] = motion.bone_tracks.get(name, 0) + 1
        if name in motion.bone_last_frame:
            motion.bone_last_frame[name] = max(motion.bone_last_frame[name], frame)
            motion.bone_first_frame[name] = min(motion.bone_first_frame[name], frame)
        else:
            motion.bone_last_frame[name] = frame
            motion.bone_first_frame[name] = frame

    if pos + 4 > len(data):
        motion.tail_start = pos
        return motion

    morph_count, pos = u32(pos)
    motion.morph_count = morph_count
    motion.morph_start = pos
    if pos + morph_count * MORPH_RECORD <= len(data):
        for _ in range(morph_count):
            raw_name = data[pos:pos + 15].split(b"\x00")[0]
            name = raw_name.decode("cp932", "replace")
            pos += MORPH_RECORD
            motion.morph_tracks[name] = motion.morph_tracks.get(name, 0) + 1
    motion.tail_start = pos
    _parse_tail(motion, data, pos, u32)
    return motion


def _parse_tail(motion, data, pos, u32):
    """读相机 / 灯光 / 阴影 / IK 开关四段。

    这四段以前被忽略，但 IK 开关表丢了会让"作者特意关掉某条腿 IK"的动作在 IK 常开下解算，
    腿部姿态直接错。所以必须读出来、并在拼接时一起重映射。
    读不通就标 tracks_valid=False，不假装成功。
    """
    motion.tracks_valid = False
    try:
        cam_count, pos = u32(pos)
        motion.camera_count = cam_count
        motion.camera_start = pos
        cams, cams_raw = [], []
        for _ in range(cam_count):
            rec = data[pos:pos + CAMERA_RECORD]
            frame = struct.unpack_from("<I", rec, 0)[0]
            cams.append(frame)
            cams_raw.append((frame, bytes(rec)))
            pos += CAMERA_RECORD
        motion.camera_frames = cams
        motion.camera_records = cams_raw

        light_count, pos = u32(pos)
        motion.light_count = light_count
        motion.light_start = pos
        for _ in range(light_count):
            rec = data[pos:pos + LIGHT_RECORD]
            motion.light_records.append(
                (struct.unpack_from("<I", rec, 0)[0], bytes(rec)))
            pos += LIGHT_RECORD

        shadow_count, pos = u32(pos)
        motion.shadow_count = shadow_count
        motion.shadow_start = pos
        for _ in range(shadow_count):
            rec = data[pos:pos + SHADOW_RECORD]
            motion.shadow_records.append(
                (struct.unpack_from("<I", rec, 0)[0], bytes(rec)))
            pos += SHADOW_RECORD

        ik_count, pos = u32(pos)
        motion.ik_count = ik_count
        motion.ik_start = pos
        ik_frames = []
        for _ in range(ik_count):
            start_ik = pos
            frame = struct.unpack_from("<I", data, pos)[0]
            ik_frames.append(frame)
            pos += 4 + 1
            n, pos = u32(pos)
            pos += n * IK_RECORD
            motion.ik_records.append((frame, bytes(data[start_ik:pos])))
        motion.ik_frames = ik_frames
        motion.tail_end = pos
        motion.tracks_valid = (pos == len(data))
    except (struct.error, IndexError):
        motion.tracks_valid = False


def _make_bone_record(name: str, frame: int, pos, rot, interp=None) -> bytes:
    """构造一条 111 字节骨骼记录。interp 为 None 时写全 0（常量段，不影响插值）。"""
    raw = name.encode("cp932", "replace")[:15]
    rec = bytearray(111)
    rec[0:len(raw)] = raw
    struct.pack_into("<I", rec, 15, int(frame))
    struct.pack_into("<3f", rec, 19, *pos)
    struct.pack_into("<4f", rec, 31, *rot)
    if interp:
        rec[47:111] = interp
    return bytes(rec)


def _fill_missing(bones, spans, motions, fill: str):
    """给"本段缺键"的骨补键，避免端点保持把别段的姿态拖过来。

    fill="hold"：补上该骨最近的键值（等于 Blender 本来就会保持的值）→ 视觉等价，只是显式化
    fill="rest"：补绑定姿势（identity）→ 保真「每段独立播放」，但 D/IK 骨会弹回原点
    """
    if fill not in ("hold", "rest"):
        return 0
    by_name = {}
    for frame, rec in bones:
        name = rec[0:15].split(b"\x00")[0].decode("cp932", "replace")
        by_name.setdefault(name, []).append((frame, rec))

    added = 0
    for idx, (motion, span) in enumerate(zip(motions, spans)):
        own = motion.bone_tracks
        lo, hi = span["dst_range"]
        for name, recs in by_name.items():
            if name in own:
                continue
            if fill == "rest":
                pos, rot = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)
            else:
                nearest = min(recs, key=lambda fr: min(abs(fr[0] - lo), abs(fr[0] - hi)))
                pos = struct.unpack_from("<3f", nearest[1], 19)
                rot = struct.unpack_from("<4f", nearest[1], 31)
            for f in (lo, hi):
                bones.append((f, _make_bone_record(name, f, pos, rot)))
                added += 1
    return added


def concat(motions, dst: str, offsets=None, gap: int = 0,
           model_name: str | None = None, fill: str = "none") -> dict:
    """把多个动作按时间轴首尾拼接成一份 VMD。

    同样不重新编码帧数据：复制每条记录的原始字节，只改其中的帧号字段。
    offsets 为 None 时自动排：第一段从 0 开始，下一段接在上一段结束帧 + gap 之后。
    """
    if not motions:
        raise VMDError("没有可拼接的动作")
    for m in motions:
        if not m.raw:
            raise VMDError("拼接需要带原始字节的 VMD：%s" % m.path)

    if offsets is None:
        offsets = []
        cursor = 0
        for m in motions:
            _first, end = m.frame_range if m.bone_last_frame else (0, 0)
            offsets.append(cursor)
            # 必须累加自身偏移：只写 end+1+gap 会让第 2 段之后的 cursor 停在同一处，
            # 三段 91/91/151 gap=2 时 offsets 变成 [0,93,93]，第 3 段整段压在
            # 第 2 段上，时间轴从 337 帧缩成 244 帧（记录没丢，时间被吞）。
            cursor = cursor + end + 1 + gap
    if len(offsets) != len(motions):
        raise VMDError("offsets 数量 %d 与动作数 %d 不一致" % (len(offsets), len(motions)))

    bones = []
    morphs = []
    spans = []
    for motion, off in zip(motions, offsets):
        data = motion.raw
        for i in range(motion.bone_count):
            start = motion.bone_start + i * BONE_RECORD
            rec = bytearray(data[start:start + BONE_RECORD])
            frame = struct.unpack_from("<I", rec, 15)[0] + int(off)
            struct.pack_into("<I", rec, 15, frame)
            bones.append((frame, bytes(rec)))
        for i in range(motion.morph_count):
            start = motion.morph_start + i * MORPH_RECORD
            rec = bytearray(data[start:start + MORPH_RECORD])
            frame = struct.unpack_from("<I", rec, 15)[0] + int(off)
            struct.pack_into("<I", rec, 15, frame)
            morphs.append((frame, bytes(rec)))
        fr = motion.frame_range
        spans.append({"path": motion.path, "offset": int(off),
                      "src_range": [int(fr[0]), int(fr[1])],
                      "dst_range": [int(fr[0]) + int(off), int(fr[1]) + int(off)],
                      "bone_records": motion.bone_count,
                      "morph_records": motion.morph_count})

    fill_added = _fill_missing(bones, spans, motions, fill)

    # 排序：VMD 本身不要求有序，但求值器按帧插值，有序更稳
    bones.sort(key=lambda x: x[0])
    morphs.sort(key=lambda x: x[0])

    # 相机 / 灯光 / 阴影 / IK 开关：全轨道都要搬，且帧号跟随段偏移。
    # 丢掉 IK 开关表会让"作者特意关掉某条腿 IK"的动作在 IK 常开下解算，腿部直接错。
    def _shift(rec, off):
        b = bytearray(rec)
        struct.pack_into("<I", b, 0, struct.unpack_from("<I", b, 0)[0] + int(off))
        return bytes(b)

    tracks_ok = all(m.tracks_valid for m in motions)
    cams, lights, shadows, iks = [], [], [], []
    if tracks_ok:
        for motion, off in zip(motions, offsets):
            for frame, rec in motion.camera_records:
                cams.append((frame + off, _shift(rec, off)))
            for frame, rec in motion.light_records:
                lights.append((frame + off, _shift(rec, off)))
            for frame, rec in motion.shadow_records:
                shadows.append((frame + off, _shift(rec, off)))
            for frame, rec in motion.ik_records:
                iks.append((frame + off, _shift(rec, off)))
        cams.sort(key=lambda x: x[0])
        lights.sort(key=lambda x: x[0])
        shadows.sort(key=lambda x: x[0])
        iks.sort(key=lambda x: x[0])

    name_len = 20 if motions[0].magic == "0002" else 10
    head = bytearray(motions[0].raw[:30 + name_len])
    if model_name:
        enc = model_name.encode("cp932", "replace")[:name_len]
        head[30:30 + name_len] = enc + b"\x00" * (name_len - len(enc))

    out = bytearray(head)
    out += struct.pack("<I", len(bones))
    out += b"".join(rec for _, rec in bones)
    out += struct.pack("<I", len(morphs))
    out += b"".join(rec for _, rec in morphs)

    if tracks_ok:
        for group in (cams, lights, shadows, iks):
            out += struct.pack("<I", len(group))
            out += b"".join(rec for _, rec in group)
    else:
        # 有段解析不出尾部 → 原样沿用第一段的尾部，并标记不完整，不假装成功
        tail = (motions[0].raw[motions[0].tail_start:]
                if motions[0].tail_start < len(motions[0].raw) else b"")
        if len(tail) < 16:
            tail = struct.pack("<4I", 0, 0, 0, 0)
        out += tail

    parent = os.path.dirname(os.path.abspath(dst))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(dst, "wb") as fh:
        fh.write(bytes(out))

    overlaps = []
    ordered = sorted(spans, key=lambda s: s["dst_range"][0])
    for a, b in zip(ordered, ordered[1:]):
        if b["dst_range"][0] <= a["dst_range"][1]:
            overlaps.append([a["path"], b["path"]])

    total_frames = (spans and max(s["dst_range"][1] for s in spans) + 1) or 0
    return {"out": dst, "bytes": len(out), "spans": spans,
            "bone_records": len(bones), "morph_records": len(morphs),
            "fill": fill, "fill_added": fill_added,
            "camera_records": len(cams), "light_records": len(lights),
            "shadow_records": len(shadows), "ik_records": len(iks),
            "tracks_complete": tracks_ok,
            "frame_range": [bones[0][0] if bones else 0, bones[-1][0] if bones else 0],
            "total_frames": int(total_frames),
            "overlaps": overlaps}


def merge(motion, expression, dst: str, model_name: str | None = None,
          offset: int = 0) -> str:
    """把「动作的骨骼段」和「表情的表情段」按字节拼成一个 VMD。

    不重新编码任何帧数据：分别取两边的原始字节段，拼上动作的尾部（相机/灯光/阴影/IK）。

    offset：给表情段整体加帧偏移。多动作拼接后，表情必须落在它所属那一段的时间轴上，
    否则会跑到第一段去（这个坑实测存在）。
    """
    md, ed = motion.raw, expression.raw
    if not md or not ed:
        raise VMDError("合并需要带原始字节的 VMD（用 load 而非手工构造）")

    name_len = 20 if motion.magic == "0002" else 10
    head = bytearray(md[:30 + name_len])
    if model_name:
        enc = model_name.encode("cp932", "replace")[:name_len]
        head[30:30 + name_len] = enc + b"\x00" * (name_len - len(enc))

    if offset:
        morph_blob = bytearray()
        for i in range(expression.morph_count):
            start = expression.morph_start + i * MORPH_RECORD
            rec = bytearray(ed[start:start + MORPH_RECORD])
            frame = struct.unpack_from("<I", rec, 15)[0] + int(offset)
            struct.pack_into("<I", rec, 15, frame)
            morph_blob += rec
        morph_blob = bytes(morph_blob)
    else:
        morph_blob = ed[expression.morph_start:expression.morph_end]

    out = bytearray(head)
    out += struct.pack("<I", motion.bone_count)
    out += md[motion.bone_start:motion.bone_end]
    out += struct.pack("<I", expression.morph_count)
    out += morph_blob
    tail = md[motion.tail_start:] if motion.tail_start < len(md) else b""
    if len(tail) < 16:
        tail = struct.pack("<4I", 0, 0, 0, 0)      # 相机/灯光/阴影/IK 四个空段
    out += tail

    parent = os.path.dirname(os.path.abspath(dst))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(dst, "wb") as fh:
        fh.write(bytes(out))
    return dst
