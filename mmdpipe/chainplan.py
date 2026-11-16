"""多动作拼接的 dry-run 计划：只报不改。

    python -m mmdpipe.chainplan a.vmd b.vmd --pmx 模型.pmx [--gap 6] [--fps 30]

回答四个问题：
  1. 每段有哪些轨道、各占用多长
  2. 两段的骨集差在哪（具体骨名）
  3. 交接处姿态差多少（按严重度分级）
  4. 根链上的位移对不对得上

**不写任何文件**，除非显式给 --json。
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field

from . import pmx as pmx_mod
from . import vmd as vmd_mod
from .chain_defaults import DEFAULT_GAP

VMD_FPS = 30.0
ANGLE_WARN = 20.0
ANGLE_ERROR = 45.0
POS_WARN = 1.0          # PMX 单位（×0.08 ≈ 8 cm）
POS_ERROR = 2.5
NLA_MAX_SEGMENTS = 2    # chain_nla.concat_via_nla 的两段接口上限


def total_frames_for_gap(rep, gap: int) -> int:
    """同一份 segments 换一个 gap 时，时间轴一共多少帧。

    gap 只决定相邻段之间插多少空帧，不改段内帧数：
        total = Σ expected_count + gap × (段数 - 1)

    用途：把「预检按 gap=6」与「真拼接按 gap=0」这两个数**在读数那一刻**并列出来，
    而不是等成片和面板对不上时再回头查（D-040 的 188 vs 182 就是这么来的）。
    """
    counts = [s["expected_count"] for s in rep.get("segments") or []]
    if not counts:
        return 0
    return sum(counts) + int(gap) * (len(counts) - 1)


def nla_segments_check(n: int) -> tuple:
    """NLA 路线能不能接下 n 段。返回 (ok, reason)。

    N>2 必须在**写 chain.vmd 之前** BLOCK：只 WARN 然后继续用 paths[0]/paths[1]
    跑，等于把后面的段静默丢掉，state 还会报成功（2026-11-15 就是这种形态）。
    """
    n = int(n)
    if n == 2:
        return True, ""
    if n < 2:
        return False, "NLA 拼接至少需要 2 段（当前 %d 段）" % n
    return False, ("NLA 模式一次只支持 2 段（当前 %d 段）：在写 chain.vmd 之前 BLOCK，"
                   "不静默丢段。改用 --chain-mode splice，或拆成两次两段任务。" % n)


def _qangle(q1, q2):
    dot = abs(sum(a * b for a, b in zip(q1, q2)))
    dot = max(-1.0, min(1.0, dot))
    return math.degrees(2.0 * math.acos(dot))


def _bone_records(motion):
    """{骨名: {帧: (pos, rot)}}。大文件也只取首末帧，内存可控。"""
    out = {}
    d = motion.raw
    for i in range(motion.bone_count):
        s = motion.bone_start + i * vmd_mod.BONE_RECORD
        name = d[s:s + 15].split(b"\x00")[0].decode("cp932", "replace")
        frame = int.from_bytes(d[s + 15:s + 19], "little")
        pos = tuple(round(v, 5) for v in _unpack3(d, s + 19))
        rot = tuple(round(v, 5) for v in _unpack4(d, s + 31))
        slot = out.setdefault(name, {})
        slot[frame] = (pos, rot)
    return out


def _unpack3(d, off):
    return __import__("struct").unpack_from("<3f", d, off)


def _unpack4(d, off):
    return __import__("struct").unpack_from("<4f", d, off)


@dataclass
class Segment:
    path: str
    motion: object
    bones: dict
    offset: int = 0
    span: tuple = (0, 0)
    index: int = 0


def _track_summary(m):
    fr = m.frame_range
    return {
        "bone": [m.bone_count, list(fr)],
        "morph": [m.morph_count, [min(m.ik_frames) if False else 0, 0]],
        "camera": m.camera_count,
        "light": m.light_count,
        "shadow": m.shadow_count,
        "ik": [m.ik_count, [min(m.ik_frames), max(m.ik_frames)] if m.ik_frames else None],
        "tail_valid": m.tracks_valid,
    }


def _morph_range(m):
    if not m.morph_count:
        return None
    d = m.raw
    lo, hi = None, None
    for i in range(m.morph_count):
        s = m.morph_start + i * vmd_mod.MORPH_RECORD
        f = int.from_bytes(d[s + 15:s + 19], "little")
        lo = f if lo is None else min(lo, f)
        hi = f if hi is None else max(hi, f)
    return [lo, hi]


def plan(paths, pmx_path=None, gap=DEFAULT_GAP, fps=VMD_FPS, limit=12):
    """只读体检。

    能力边界（重要）：本模块纯 Python，没有骨架求值，**算不出世界位移**。
    下面出现的 `local_pos_delta` 是某根骨"局部位置数值"的逐轴最大差，
    父链不同时它不代表站位差，不要拿它当"会不会瞬移"的依据。
    真正的世界根位移由 `measure_align`（Blender 侧）测量。
    """
    segs = []
    for i, p in enumerate(paths):
        m = vmd_mod.load(p)
        segs.append(Segment(path=p, motion=m, bones=_bone_records(m), index=i))

    cursor = 0
    for s in segs:
        first, last = s.motion.frame_range
        s.offset = cursor
        # 与 vmd.concat 的自动排布同一口径：段起点对准 cursor，段内保留源首帧偏移。
        # 两处必须一致，否则 plan 报 337、实际文件 244（2026-11-15 的丢段就是这个）。
        s.span = (cursor + first, cursor + last)
        cursor = cursor + last + 1 + gap

    report = {
        "inputs": paths,
        "gap": gap,
        "fps": fps,
        "segments": [],
        "bone_sets": {},
        "overlaps": [],
        "joint_gaps": [],
        "junctions": [],
        "pose_diff": [],
        "roots": [],
        "key_additions": {},
    }

    for i, s in enumerate(segs):
        m = s.motion
        report["segments"].append({
            "index": i, "path": s.path,
            "bones": m.bone_count, "bone_range": list(m.frame_range),
            "morphs": m.morph_count, "morph_range": _morph_range(m),
            "camera": m.camera_count, "light": m.light_count,
            "shadow": m.shadow_count, "ik": m.ik_count,
            "ik_range": [min(m.ik_frames), max(m.ik_frames)] if m.ik_frames else None,
            "tail_valid": m.tracks_valid,
            "offset": s.offset, "timeline": [s.span[0], s.span[1]],
            "expected_count": s.span[1] - s.span[0] + 1,
            "gap_after": gap,
            "duration_s": round(s.span[1] / fps, 3),
        })

    ordered = sorted(segs, key=lambda x: x.span[0])
    for a, b in zip(ordered, ordered[1:]):
        if b.span[0] <= a.span[1]:
            report["overlaps"].append([a.path, b.path])

    if len(segs) >= 2:
        sets = [set(s.bones) for s in segs]
        common = set.intersection(*sets)
        union = set.union(*sets)
        report["bone_sets"] = {
            "union": len(union),
            "common": len(common),
            "per_segment": [len(x) for x in sets],
            "missing_in": {str(i): sorted(union - x)[:limit] for i, x in enumerate(sets)},
            "missing_counts": {str(i): len(union - x) for i, x in enumerate(sets)},
        }

        # 每个相邻对都要有 junction：只比较 segs[0]/segs[1] 会让三段拼接的
        # 第 2/3 段交接完全没人检查，也看不出中间整段被压掉。
        for a, b in zip(ordered, ordered[1:]):
            a_end = max(a.motion.bone_last_frame.values()) if a.motion.bone_last_frame else 0
            b_start = min(b.motion.bone_first_frame.values()) if b.motion.bone_first_frame else 0
            pose_diff = []
            for name in sorted(common):
                ra = a.bones.get(name, {}).get(a_end)
                rb = b.bones.get(name, {}).get(b_start)
                if not ra or not rb:
                    ra = ra or _nearest(a.bones.get(name), a_end)
                    rb = rb or _nearest(b.bones.get(name), b_start)
                if not ra or not rb:
                    continue
                ang = _qangle(ra[1], rb[1])
                pos = max(abs(ra[0][k] - rb[0][k]) for k in range(3))
                sev = "error" if (ang > ANGLE_ERROR or pos > POS_ERROR) else \
                      "warn" if (ang > ANGLE_WARN or pos > POS_WARN) else "info"
                pose_diff.append({
                    "bone": name, "angle_deg": round(ang, 2), "pos_delta": round(pos, 3),
                    "pos_delta_mm": round(pos * 80.0, 1),
                    "severity": sev,
                })
            pose_diff.sort(key=lambda x: -x["angle_deg"])
            report["junctions"].append({
                "pair": [a.index, b.index],
                "a_path": a.path, "b_path": b.path,
                "a_last_frame": a_end, "b_first_frame": b_start,
                "timeline": [a.span[1], b.span[0]],
                "gap": gap,
                "over_threshold": sum(1 for p_ in pose_diff if p_["severity"] != "info"),
                "max_angle_deg": pose_diff[0]["angle_deg"] if pose_diff else 0.0,
                "pose_diff": pose_diff,
            })
        # 兼容旧字段：pose_diff 仍指第一个交接对（两段拼接时完全等价）
        report["pose_diff"] = report["junctions"][0]["pose_diff"] if report["junctions"] else []

        # 根链：必须按段算。用并集会出错——全ての親 只在 B 段动，
        # 并集视角下 センター 就被判成"有动画祖先"，而它其实是 A 段的根。
        if pmx_path:
            a, b = ordered[0], ordered[1]
            a_end = report["junctions"][0]["a_last_frame"]
            b_start = report["junctions"][0]["b_first_frame"]
            model = pmx_mod.load(pmx_path)
            parent = {b.index: b.parent for b in model.bones}
            name_of = {b.index: b.name for b in model.bones}
            idx_of = {}
            for bone in model.bones:
                idx_of.setdefault(bone.name, bone.index)

            def roots_of(seg):
                animated = {n for n in seg.bones if n in model.bone_names}
                found = []
                for n in sorted(animated):
                    i = idx_of.get(n)
                    if i is None:
                        continue
                    cur, seen, has = parent.get(i, -1), 0, False
                    while 0 <= cur < len(model.bones) and seen <= len(model.bones):
                        if name_of.get(cur) in animated:
                            has = True
                            break
                        cur = parent.get(cur, -1)
                        seen += 1
                    if not has:
                        found.append(n)
                return found

            per_seg = [roots_of(s) for s in segs]
            report["roots_per_segment"] = per_seg
            report["roots"] = sorted({r for rs in per_seg for r in rs})[:limit]

            diffs = []
            root_union = {r for rs in per_seg for r in rs}
            for name in sorted(root_union):
                pa = _nearest(a.bones.get(name), a_end)
                pb = _nearest(b.bones.get(name), b_start)
                if pa and pb:
                    diffs.append({"bone": name,
                                  "local_pos_delta": round(max(abs(pa[0][k] - pb[0][k])
                                                               for k in range(3)), 3),
                                  "a_pos": list(pa[0]), "b_pos": list(pb[0])})
            report["local_root_pos_delta"] = diffs

        # 位置差单独看（角度小但位移大的骨会被角度排序埋掉）
        movers = sorted([p for p in report["pose_diff"] if p["pos_delta"] > 1e-6],
                        key=lambda x: -x["pos_delta"])[:limit]
        report["pos_movers"] = movers

        # 需要补的键：某段缺失的骨 × 段跨度（估算，dry-run 不改文件）
        adds = {}
        for i, s in enumerate(segs):
            miss = union - set(s.bones)
            adds[str(i)] = {"missing_bones": len(miss),
                            "would_add_keys": len(miss) * 2}
        report["key_additions"] = adds

    last = max(s.span[1] for s in segs) if segs else 0
    # 过渡速度建议：舞蹈类观感阈值取 5°/帧。多个交接取最差的那个。
    mx = max((j["max_angle_deg"] for j in report["junctions"]), default=0.0)
    report["max_junction_angle"] = mx
    report["deg_per_frame"] = round(mx / (gap + 1), 2) if gap >= 0 else None
    report["recommended_gap"] = max(0, math.ceil(mx / 5.0) - 1)

    report["last_frame"] = last
    report["total_frames"] = last + 1          # 0..last 共 last+1 帧
    report["total_duration_s"] = round(report["total_frames"] / fps, 3)
    # 同一份 segments 若换成"默认 gap"真拼接会得到多少帧。M07 只吃 JSON，
    # 所以这列必须进 JSON，不能只打在文本里——面板要显示的就是"预检 vs 成片"的差。
    report["frames_if_default_gap"] = total_frames_for_gap(report, DEFAULT_GAP)
    return report


def _nearest(slot, frame):
    if not slot:
        return None
    key = min(slot, key=lambda f: abs(f - frame))
    return slot[key]


def render_text(rep, limit=10):
    lines = ["多动作拼接 dry-run（只报不改）"]
    lines.append("  输入 %d 段，gap %d 帧，按 %.0f fps 换算" % (len(rep["inputs"]), rep["gap"], rep["fps"]))
    for s in rep["segments"]:
        ik = s["ik_range"]
        lines.append("  [%d] %s" % (s["index"], s["path"].split("/")[-1][:40]))
        lines.append("      骨骼 %d 条 %s ｜ 表情 %d %s ｜ 相机 %d ｜ 灯光 %d ｜ 阴影 %d ｜ IK %d%s"
                     % (s["bones"], s["bone_range"], s["morphs"], s["morph_range"],
                        s["camera"], s["light"], s["shadow"], s["ik"],
                        (" %s" % ik) if ik else ""))
        lines.append("      时间轴 %d..%d（%.2f s）  尾部解析=%s"
                     % (s["timeline"][0], s["timeline"][1], s["duration_s"], s["tail_valid"]))

    bs = rep.get("bone_sets") or {}
    if bs:
        lines.append("")
        lines.append("  骨集：并集 %d，交集 %d，各段 %s"
                     % (bs["union"], bs["common"], bs["per_segment"]))
        for k, v in bs["missing_counts"].items():
            if v:
                sample = bs["missing_in"][k][:6]
                lines.append("    段%s 缺 %d 根：%s%s" % (k, v, ", ".join(sample),
                                                       " …" if v > len(sample) else ""))

    if rep["pose_diff"]:
        lines.append("")
        bad = [p for p in rep["pose_diff"] if p["severity"] != "info"]
        lines.append("  交接姿态差：共有骨 %d 根，超阈值 %d 根" % (len(rep["pose_diff"]), len(bad)))
        for p in rep["pose_diff"][:limit]:
            lines.append("    %-6s %-16s 角度 %6.1f°  位置 %6.3f"
                         % (p["severity"].upper(), p["bone"][:16], p["angle_deg"], p["pos_delta"]))

    junctions = rep.get("junctions") or []
    if len(junctions) > 1:
        lines.append("")
        lines.append("  交接对（%d 段 → %d 个交接，每对都要查）：" % (len(rep["segments"]), len(junctions)))
        for j in junctions:
            lines.append("    段%s→段%s  源帧 %s→%s  时间轴 %d..%d  超阈值 %d 根  最大 %.1f°"
                         % (j["pair"][0], j["pair"][1], j["a_last_frame"], j["b_first_frame"],
                            j["timeline"][0], j["timeline"][1],
                            j["over_threshold"], j["max_angle_deg"]))

    if rep.get("pos_movers"):
        lines.append("")
        lines.append("  位置差最大（角度可能很小但会瞬移）：")
        for p in rep["pos_movers"][:6]:
            lines.append("    %-16s 位置 %6.3f（%5.1f mm）  角度 %6.1f°"
                         % (p["bone"][:16], p["pos_delta"], p["pos_delta_mm"], p["angle_deg"]))

    if rep.get("local_root_pos_delta"):
        lines.append("")
        lines.append("  根链局部位置差（**不是世界位移**，仅供参考；世界位移见 measure_align）：")
        for d in rep["local_root_pos_delta"][:6]:
            lines.append("    %-16s %s → %s  局部差 %.3f"
                         % (d["bone"][:16], d["a_pos"], d["b_pos"], d["local_pos_delta"]))
        pss = rep.get("roots_per_segment")
        if pss:
            lines.append("    各段根链：%s" % [[r for r in rs][:4] for rs in pss])
    elif rep.get("roots") is not None:
        lines.append("")
        lines.append("  根链候选：%s" % (", ".join(rep["roots"]) if rep["roots"] else "（需要 --pmx 才能算）"))

    ka = rep.get("key_additions") or {}
    if ka:
        lines.append("")
        lines.append("  估算补键（本次不改文件）：")
        for k, v in ka.items():
            lines.append("    段%s 缺 %d 根骨 → 若补两端约 %d 个键"
                         % (k, v["missing_bones"], v["would_add_keys"]))

    if rep["overlaps"]:
        lines.append("")
        lines.append("  !! 时间轴重叠：%s" % rep["overlaps"])
    lines.append("")
    dpg = rep.get("deg_per_frame")
    if dpg is not None and rep.get("max_junction_angle"):
        lines.append("")
        lines.append("  过渡速度：gap %d → %.1f°/帧（建议 gap ≥ %d，约 5°/帧）"
                     % (rep["gap"], dpg, rep["recommended_gap"]))
    lines.append("  合计 %d 帧（末帧 %d）/ %.2f s" % (rep["total_frames"], rep["last_frame"], rep["total_duration_s"]))

    # 帧账校核：预检用的 gap 与"没传 --gap 时真拼接用的默认 gap"并列给出来。
    # 188 vs 182 这种差必须在读数那一刻看得见，否则面板与成片永远对不上还查不出原因。
    default_total = total_frames_for_gap(rep, DEFAULT_GAP)
    if default_total != rep["total_frames"]:
        lines.append("  帧账校核：本段 gap=%d → %d 帧；不传 --gap 真拼接会是 %d 帧（差 %d 帧）"
                     % (rep["gap"], rep["total_frames"], default_total,
                        abs(default_total - rep["total_frames"])))
        lines.append("    → 面板/脚本必须显式对齐 --gap，否则预检与成片永远差这么多帧")
    else:
        lines.append("  帧账校核：本段 gap=%d → %d 帧，与默认 gap=%d 的真拼接一致"
                     % (rep["gap"], rep["total_frames"], DEFAULT_GAP))
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mmdpipe.chainplan")
    ap.add_argument("motions", nargs="+")
    ap.add_argument("--pmx", help="用它的骨骼层级判断根链")
    ap.add_argument("--gap", type=int, default=DEFAULT_GAP,
                    help="段间空帧数（默认 %d，与 concatvmd 同一常量）" % DEFAULT_GAP)
    ap.add_argument("--fps", type=float, default=VMD_FPS)
    ap.add_argument("--json")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    try:
        rep = plan(args.motions, args.pmx, args.gap, args.fps)
    except (vmd_mod.VMDError, pmx_mod.PMXError, OSError) as exc:
        print("dry-run 失败：%s" % exc, file=sys.stderr)
        return 1
    if not args.quiet:
        print(render_text(rep))
    if args.json:
        from .report import dump
        dump(rep, args.json)
    return 0 if not rep["overlaps"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
