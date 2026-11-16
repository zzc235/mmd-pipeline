"""M02 · S8 阶段 E 离线比对（判据见 s8_hypothesis.md，跑前已落盘）。

    python m02_s8_compare.py <A_dir> <B_dir> <out.json> [--targets s2_targets.json] [--label ...]

主判据：18 根下摆骨（`下擺_0_0 … 下擺_0_17`）上 D = max_{帧,骨} |posA − posB|，阈值 1.0 mm。
次判据：全 324 刚体上的同一个 D（只补记，不参与判定）。
重复性：A1 vs A2 用同一个函数跑一遍；A1≠A2 超阈值则主结论作废。
"""
import json
import os
import sys


def load(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def bone_matches(obj_name, bone):
    """刚体对象名是 `<seq>_<骨名>`，例如 `042_下擺_0_0`。"""
    return obj_name.split("_", 1)[-1] == bone


def compare(a_dir, b_dir, hem_bones):
    fa = load(os.path.join(a_dir, "frames.jsonl"))
    fb = load(os.path.join(b_dir, "frames.jsonl"))
    if len(fa) != len(fb) or any(x["frame"] != y["frame"] for x, y in zip(fa, fb)):
        return {"verdict": "UNKNOWN", "reason": "frame sets differ"}
    names = sorted(fa[0]["pos"].keys())
    hem = {b: [n for n in names if bone_matches(n, b)] for b in hem_bones}
    missing = [b for b, ns in hem.items() if len(ns) != 1]
    hem_names = [ns[0] for ns in hem.values() if len(ns) == 1]

    per_frame_hem = []
    per_bone = {n: 0.0 for n in names}
    first_over = None
    max_at = None
    for xa, xb in zip(fa, fb):
        f = xa["frame"]
        best = 0.0
        for n in names:
            pa, pb = xa["pos"][n], xb["pos"][n]
            d = sum((pa[i] - pb[i]) ** 2 for i in range(3)) ** 0.5
            if d > per_bone[n]:
                per_bone[n] = d
            if d > best:
                best = d
                if d > 0.001 and n in hem_names and first_over is None:
                    first_over = f
        if best > (max_at[1] if max_at else -1):
            max_at = (f, best)
        hem_best = max(sum((xa["pos"][n][i] - xb["pos"][n][i]) ** 2 for i in range(3)) ** 0.5
                       for n in hem_names)
        per_frame_hem.append({"frame": f, "max_hem_m": round(hem_best, 9)})

    D_hem = max(r["max_hem_m"] for r in per_frame_hem)
    D_all = max(per_bone.values())
    return {"frames": len(fa), "objects": len(names),
            "hem_bones_missing": missing, "hem_objects": len(hem_names),
            "D_hem_m": round(D_hem, 9), "D_all_m": round(D_all, 9),
            "first_frame_over_1mm_hem": first_over,
            "max_at_frame_all": max_at[0] if max_at else None,
            "per_frame": per_frame_hem}


def pct(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def main():
    a_dir, b_dir, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    targets = None
    label = ""
    argv = sys.argv[4:]
    i = 0
    while i < len(argv):
        if argv[i] == "--targets":
            targets = argv[i + 1]
            i += 2
        elif argv[i] == "--label":
            label = argv[i + 1]
            i += 2
        else:
            i += 1
    with open(targets, encoding="utf-8") as fh:
        td = json.load(fh)
    if isinstance(td, dict) and "bones" in td:
        hem_bones = td["bones"]
    else:  # s2_targets.json：{"targets": [{"joint_name": ...}, ...]}
        hem_bones = [t["joint_name"] for t in td["targets"]]

    main = compare(a_dir, b_dir, hem_bones)
    out = {"stage": "E-s8", "label": label, "a_dir": a_dir, "b_dir": b_dir,
           "criterion": {"threshold_m": 0.001,
                         "primary_set": "s2_targets.json 的 %d 根下摆骨" % len(hem_bones)},
           "main": {k: v for k, v in main.items() if k != "per_frame"}}
    if "D_hem_m" in main:
        d_hem = main["D_hem_m"]
        out["verdict"] = ("EFFECTIVE" if d_hem >= 0.001 else
                          ("NO_EFFECT" if d_hem <= 1e-6 else "UNKNOWN"))
        vals = [r["max_hem_m"] for r in main["per_frame"]]
        out["distribution_hem_m"] = {"p50": round(pct(vals, 0.5), 9), "p95": round(pct(vals, 0.95), 9),
                                     "p99": round(pct(vals, 0.99), 9), "max": round(max(vals), 9),
                                     "nonzero_frames": sum(1 for v in vals if v > 1e-6)}
        out["per_frame_hem_m"] = main["per_frame"]
    else:
        out["verdict"] = main.get("verdict", "UNKNOWN")

    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    if "D_hem_m" in main:
        print("%s verdict=%s D_hem=%.9f m D_all=%.9f m first_over=%s"
              % (label or "cmp", out["verdict"], main["D_hem_m"], main["D_all_m"],
                 main["first_frame_over_1mm_hem"]))
    else:
        print("%s verdict=%s %s" % (label or "cmp", out["verdict"], main))


main()
