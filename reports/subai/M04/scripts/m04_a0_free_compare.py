# -*- coding: utf-8 -*-
"""M04 A0 v2 三对比较的逐帧分布（只读产物，不开 Blender）。

三对：
  sens   : R_free（位不动）  vs A0_free（位全清）      —— 仪器灵敏度
  repro  : A240（缓存回放）  vs R_free（重解）         —— 烘焙能否被重解重现
  determ : R_free            vs R_free2（再解一遍）    —— 重解是否确定性
"""
import io
import json
import statistics
import sys

sys.stdout.reconfigure(encoding="utf-8")

PEN = r"out\subai\M04\penetration"


def load(name):
    with io.open("%s\\%s.meta.json" % (PEN, name), encoding="utf-8") as fh:
        meta = json.load(fh)
    out = {}
    for r in meta["per_frame"]:
        out[int(r["frame"])] = (float(r["max_depth_m"]), int(r.get("overlapping_pairs") or 0),
                                float(r.get("raw_depth_m") or 0.0))
    return meta, out


def compare(tag, na, nb, la, lb):
    ma, fa = load(na)
    mb, fb = load(nb)
    frames = sorted(set(fa) & set(fb))
    d = {f: fa[f][0] - fb[f][0] for f in frames}          # a - b
    nz = [f for f in frames if abs(d[f]) > 0]
    deeper_b = [f for f in frames if d[f] > 0]            # b 更负 = b 更深
    deeper_a = [f for f in frames if d[f] < 0]
    ov_a = sum(fa[f][1] for f in frames)
    ov_b = sum(fb[f][1] for f in frames)
    print("\n=== %s : %s  vs  %s ===" % (tag, la, lb))
    print("  frames=%d  完全相同帧=%d  A更深帧=%d  B更深帧=%d"
          % (len(frames), len(frames) - len(nz), len(deeper_a), len(deeper_b)))
    if nz:
        ad = [abs(d[f]) for f in frames]
        print("  |Δ max_depth| 中位=%.6f m  均值=%.6f m  最大=%.6f m @frame %d"
              % (statistics.median(ad), statistics.mean(ad), max(ad), max(frames, key=lambda f: abs(d[f]))))
        top = sorted(frames, key=lambda f: -abs(d[f]))[:5]
        print("  差最大的 5 帧: " + ", ".join("#%d Δ=%+.6f" % (f, d[f]) for f in top))
    print("  overlapping_pairs 合计: %s=%d  %s=%d  (差 %+d)"
          % (la, ov_a, lb, ov_b, ov_b - ov_a))
    print("  窗口内 raw_depth 最深: %s=%.6f  %s=%.6f"
          % (la, min(fa[f][2] for f in frames), lb, min(fb[f][2] for f in frames)))
    print("  pose_source: %s=%r  %s=%r"
          % (la, ma.get("pose_source", "(未记录)"), lb, mb.get("pose_source", "(未记录)")))
    print("  cache_state.is_baked: %s=%r  %s=%r"
          % (la, (ma.get("cache_state") or {}).get("is_baked"),
             lb, (mb.get("cache_state") or {}).get("is_baked")))
    return {
        "tag": tag, "a": la, "b": lb, "frames": len(frames),
        "identical_frames": len(frames) - len(nz),
        "a_deeper_frames": len(deeper_a), "b_deeper_frames": len(deeper_b),
        "max_abs_delta_m": (max(abs(d[f]) for f in frames) if nz else 0.0),
        "max_delta_frame": (max(frames, key=lambda f: abs(d[f])) if nz else None),
        "overlapping_pairs": {la: ov_a, lb: ov_b},
        "raw_depth_min": {la: min(fa[f][2] for f in frames), lb: min(fb[f][2] for f in frames)},
    }


def main():
    rows = [compare("灵敏度", "R_free", "A0_free", "R_free(位不动,重解)", "A0_free(位全清,重解)"),
            compare("可重现", "A240", "R_free", "A240(缓存回放)", "R_free(重解)"),
            compare("确定性", "R_free", "R_free2", "R_free", "R_free2")]
    out = r"%s\a0_free_perframe_compare.json" % PEN
    with io.open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({"spec": "m04_a0_free_compare/1", "rows": rows},
                            ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print("\nwritten %s" % out)


if __name__ == "__main__":
    main()
