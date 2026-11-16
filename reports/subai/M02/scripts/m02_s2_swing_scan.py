"""M02 · S2 前置：在现有 VMD 里筛「摆动够大」的候选动作（纯 Python，不开 Blender）。

    python m02_s2_swing_scan.py <vmd 或目录> ... [--top N] [--json out.json]

为什么先做这一步：S2 现在的结论是「±0.7 rad 限位从未被触及」，因为躺姿场景下摆骨的
X 轴峰值只有 0.5788 rad（且只有两根超 0.5）。D0 定的默认路径是**换一个更大摆幅的场景**
重测。66 个 VMD 里哪个够大，先在这里按动画曲线的 X 轴峰值筛一遍，再去开 Blender——
不然每个都建场景跑一遍，锁窗口和几十分钟全花在明确不够的动作上。

口径（写死）：
    * 只看骨骼旋转轨，四元数 (x,y,z,w) → 欧拉 XYZ，取 X 分量
    * 报每个文件的「骨架级」峰值：X 峰值最大的前 N 根骨
    * 同时报腿/裙骨集合的峰值（名字含 足 / ひざ / もも / 下擺 / 下摆 / 裙），
      因为它们才是真的会推动下摆的输入
    * 同一份内容（sha256 相同）只算一次——66 个文件里大量是 `chain.vmd` 的副本
"""
import hashlib
import json
import math
import os
import struct
import sys

sys.path.insert(0, os.environ.get("MMDPIPE_TREE") or r"E:\code\mmdpipe-ai\A1")
from mmdpipe import vmd as vmdmod  # noqa: E402

SKIRT_KEYS = ("下擺", "下摆", "裙", "スカート")
LEG_KEYS = ("足", "ひざ", "もも", "太もも", "脚")
# IK 骨的**旋转**不是腿的摆幅（IK 骨靠位置驱动解算），它的旋转值多是动画数据里的噪声，
# 实测能到 π。算进「腿摆幅」会把一个躺姿动作也算成大幅摆动，所以显式排除。
IK_MARKS = ("ＩＫ", "IK")


def quat_to_euler_xyz(x, y, z, w):
    """与 Blender 的 `to_euler('XYZ')` 同序：先绕 X、再 Y、再 Z 的静态组合。"""
    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    rx = math.atan2(sinr_cosp, cosr_cosp)
    sinp = 2.0 * (w * y - z * x)
    ry = math.copysign(math.pi / 2.0, sinp) if abs(sinp) >= 1.0 else math.asin(sinp)
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    rz = math.atan2(siny_cosp, cosy_cosp)
    return rx, ry, rz


def parse_bones(path):
    """返回 {bone_name: [(frame, x, y, z, w), ...]}。

    `mmdpipe.vmd` 只留 `bone_tracks = {骨名: 关键帧条数}`（见 `vmd.py:32`），**不保留旋转**
    ——那条路走不通。但它的 `bone_start` / `bone_count` 已经解析好了，所以这里只按
    `BONE_RECORD`（111 B = 15 名 + 4 帧 + 12 位移 + 16 旋转 + 64 插值）取旋转，
    不重复实现整个解析器。布局有 `len(data)` 边界检查，读越界直接抛。

    **这是对 `mmdpipe/vmd.py` 的临时旁路，不是接口**：只为一次筛选取旋转，不为它改 M01 的
    公开接口（那要走接口验收）。若将来别处也要逐帧旋转，正确做法是给 `VMDMotion` 加字段
    并走 M01 的验收流程，而不是复制这段。
    """
    with open(path, "rb") as fh:
        data = fh.read()
    motion = vmdmod.load(path)
    if not data[:30].rstrip(b"\x00").startswith(b"Vocaloid Motion Data"):
        raise SystemExit("不是 VMD：%s" % path)
    start = motion.bone_start
    count = motion.bone_count
    if start + count * vmdmod.BONE_RECORD > len(data):
        raise ValueError("骨骼段越界：start=%d count=%d len=%d" % (start, count, len(data)))
    tracks = {}
    for i in range(count):
        off = start + i * vmdmod.BONE_RECORD
        raw_name = data[off:off + 15].split(b"\x00")[0]
        name = raw_name.decode("cp932", "replace")
        frame = int.from_bytes(data[off + 15:off + 19], "little", signed=True)
        rx, ry, rz, rw = struct.unpack_from("<4f", data, off + 31)
        tracks.setdefault(name, []).append((frame, rx, ry, rz, rw))
    return tracks


def scan(path):
    tracks = parse_bones(path)
    best = []
    skirt_peak = 0.0
    leg_peak = 0.0
    frames = 0
    for name, rows in tracks.items():
        peak = 0.0
        for _f, x, y, z, w in rows:
            rx, _ry, _rz = quat_to_euler_xyz(x, y, z, w)
            if abs(rx) > peak:
                peak = abs(rx)
            if _f > frames:
                frames = _f
        best.append((peak, name, len(rows)))
        is_ik = any(m in name for m in IK_MARKS)
        if any(k in name for k in SKIRT_KEYS):
            skirt_peak = max(skirt_peak, peak)
        elif not is_ik and any(k in name for k in LEG_KEYS):
            leg_peak = max(leg_peak, peak)
    best.sort(reverse=True)
    return {
        "path": path.replace("\\", "/"),
        "bones": len(tracks),
        "last_frame": frames,
        "skirt_peak_x_rad": round(skirt_peak, 4),
        "leg_peak_x_rad": round(leg_peak, 4),
        "top_bones": [{"bone": n, "peak_x_rad": round(p, 4), "keys": k}
                      for p, n, k in best[:8]],
    }


def collect(targets):
    paths = []
    for target in targets:
        if os.path.isdir(target):
            for dirpath, _dirnames, filenames in os.walk(target):
                for name in filenames:
                    if name.lower().endswith(".vmd"):
                        paths.append(os.path.join(dirpath, name))
        else:
            paths.append(target)
    return sorted(set(paths))


def main(argv):
    args = [a for a in argv[1:]]
    top = 8
    out_path = None
    targets = []
    i = 0
    while i < len(args):
        if args[i] == "--top" and i + 1 < len(args):
            top = int(args[i + 1])
            i += 2
            continue
        if args[i] == "--json" and i + 1 < len(args):
            out_path = args[i + 1]
            i += 2
            continue
        targets.append(args[i])
        i += 1
    if not targets:
        print("用法: python m02_s2_swing_scan.py <vmd|目录> ... [--top N] [--json out.json]")
        return 2

    seen = {}
    rows = []
    for path in collect(targets):
        try:
            digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
        except OSError as exc:
            print("SKIPPED %s：%s" % (path, exc))
            continue
        if digest in seen:
            continue
        seen[digest] = path
        try:
            row = scan(path)
        except Exception as exc:                      # noqa: BLE001 —— 解析失败必须可见
            print("SKIPPED %s：%s: %s" % (path, exc.__class__.__name__, exc))
            continue
        row["sha256"] = digest
        rows.append(row)
    rows.sort(key=lambda r: -(r["skirt_peak_x_rad"] or r["leg_peak_x_rad"]))
    print("%-46s %6s %6s %7s %7s" % ("file", "bones", "frames", "裙X", "腿X"))
    for r in rows[:top]:
        name = r["path"].rsplit("/", 1)[-1][:44]
        print("%-46s %6d %6d %7.4f %7.4f"
              % (name, r["bones"], r["last_frame"], r["skirt_peak_x_rad"],
                 r["leg_peak_x_rad"]))
        for b in r["top_bones"][:3]:
            print("      %-24s peak=%.4f keys=%d" % (b["bone"], b["peak_x_rad"], b["keys"]))
    print("唯一动作数=%d（去重后），文件数=%d" % (len(rows), len(collect(targets))))
    print("S2 判据提醒：0.7 rad 要「被触及」，裙/腿的 X 峰值必须真的超过 0.7；"
          "0.5–0.7 之间只咬到一部分。")
    if out_path:
        with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=1, sort_keys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
