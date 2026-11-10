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

VMD_FPS = 30.0
ANGLE_WARN = 20.0
ANGLE_ERROR = 45.0
POS_WARN = 1.0          # PMX 单位（×0.08 ≈ 8 cm）
POS_ERROR = 2.5


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


def plan(paths, pmx_path=None, gap=6, fps=VMD_FPS, limit=12):
    """只读体检。

    能力边界（重要）：本模块纯 Python，没有骨架求值，**算不出世界位移**。
    下面出现的 `local_pos_delta` 是某根骨"局部位置数值"的逐轴最大差，
    父链不同时它不代表站位差，不要拿它当"会不会瞬移"的依据。
    真正的世界根位移由 `measure_align`（Blender 侧）测量。
    """
    segs = []
    for p in paths:
        m = vmd_mod.load(p)
        segs.append(Segment(path=p, motion=m, bones=_bone_records(m)))

    cursor = 0
    for s in segs:
        s.offset = cursor
        end = s.motion.frame_range[1] if s.motion.bone_last_frame else 0
        s.span = (cursor, cursor + end)
        cursor = cursor + end + 1 + gap

    report = {
        "inputs": paths,
        "gap": gap,
        "fps": fps,
        "segments": [],
        "bone_sets": {},
        "overlaps": [],
        "joint_gaps": [],
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

        a, b = segs[0], segs[1]
        a_end = max(a.motion.bone_last_frame.values()) if a.motion.bone_last_frame else 0
        b_start = min(b.motion.bone_first_frame.values()) if b.motion.bone_first_frame else 0
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
            report["pose_diff"].append({
                "bone": name, "angle_deg": round(ang, 2), "pos_delta": round(pos, 3),
                "pos_delta_mm": round(pos * 80.0, 1),
                "severity": sev,
            })
        report["pose_diff"].sort(key=lambda x: -x["angle_deg"])

        # 根链：必须按段算。用并集会出错——全ての親 只在 B 段动，
        # 并集视角下 センター 就被判成"有动画祖先"，而它其实是 A 段的根。
        if pmx_path:
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
    # 过渡速度建议：舞蹈类观感阈值取 5°/帧
    mx = report["pose_diff"][0]["angle_deg"] if report["pose_diff"] else 0.0
    report["max_junction_angle"] = mx
    report["deg_per_frame"] = round(mx / (gap + 1), 2) if gap >= 0 else None
    report["recommended_gap"] = max(0, math.ceil(mx / 5.0) - 1)

    report["last_frame"] = last
    report["total_frames"] = last + 1          # 0..last 共 last+1 帧
    report["total_duration_s"] = round(report["total_frames"] / fps, 3)
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
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mmdpipe.chainplan")
    ap.add_argument("motions", nargs="+")
    ap.add_argument("--pmx", help="用它的骨骼层级判断根链")
    ap.add_argument("--gap", type=int, default=6)
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
