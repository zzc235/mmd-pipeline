"""M01 阶段 C/D 判据：比较三个变体在相同帧的胸口顶点世界坐标。

    python m01_compare.py [probe_dir]

读 probe_<variant>.json，输出 comparison.json + comparison.md。
判据（不靠肉眼）：
  * baseline(物理+mode2) vs static(关物理)：差异越大 = 硬约束把胸口拽离纯跟随越明显
  * mode0(物理+mode0)  vs static：只应剩浮点噪声 → 说明 mode0 回到纯跟随
  * mode0 vs baseline：修复前后到底改了多少
"""
from __future__ import annotations

import json
import math
import os
import sys

PROBE = os.environ.get("M01_PROBE_DIR", r"E:\dsh pr\woker2\out\subai\M01\probe")
PAIRS = [("baseline", "static"), ("mode0", "static"), ("mode0", "baseline")]


def load(variant: str) -> dict:
    with open(os.path.join(PROBE, "probe_%s.json" % variant), encoding="utf-8") as fh:
        return json.load(fh)


def dist_stats(a, b) -> dict:
    d = [math.dist(p, q) for p, q in zip(a, b)]
    d.sort()
    n = len(d)
    return {"n": n, "max": round(d[-1], 6), "mean": round(sum(d) / n, 6),
            "p95": round(d[min(n - 1, int(n * 0.95))], 6),
            "min": round(d[0], 6)}


def main() -> int:
    global PROBE
    if len(sys.argv) > 1:
        PROBE = sys.argv[1]
    variants = {}
    for v in ("baseline", "static", "mode0"):
        p = os.path.join(PROBE, "probe_%s.json" % v)
        if os.path.exists(p):
            variants[v] = load(v)
    if len(variants) < 2:
        print("至少需要两个变体的 probe json")
        return 2

    out = {"variants": {}, "frames": {}}
    for v, data in variants.items():
        out["variants"][v] = {
            "physics": data["physics"], "is_built": data["is_built"],
            "rigids": data["after_build"]["rigids"],
            "chest_cons_total": data["after_build"]["chest_cons_total"],
            "chest_constraints": {k: [(c["type"], c["target_type"]) for c in vv]
                                  for k, vv in data["after_build"]["chest_constraints"].items()},
            "constraints": data["after_build"]["constraints"],
            "engine": data["engine"], "camera": data["camera"],
            "roi": data["roi"], "action_range": data["action_range"],
            "rigid_types": data["rigid_types"],
        }

    frame_rows = {}
    for v, data in variants.items():
        for row in data["frames"]:
            frame_rows.setdefault(row["frame"], {})[v] = row

    for f in sorted(frame_rows):
        rows = frame_rows[f]
        rec = {"present": sorted(rows), "metrics": {}}
        for v, row in rows.items():
            rec["metrics"][v] = {
                "chest_extent": row["chest"]["extent"],
                "chest_centroid": row["chest"]["centroid"],
                "chest_hip_ratio": row.get("chest_hip_ratio"),
                "torso_centroid": (row["torso"]["centroid"] if row["torso"] else None),
            }
        for a, b in PAIRS:
            if a in rows and b in rows:
                rec["%s_vs_%s" % (a, b)] = dist_stats(rows[a]["chest_verts"], rows[b]["chest_verts"])
        out["frames"][str(f)] = rec

    # 物理活性：跟踪刚体在首/末帧的位移（证明动力学真在跑，而不是整体静止）
    live = {}
    for v, data in variants.items():
        if not data["physics"]:
            continue
        fr = data["frames"]
        first, last = fr[0], fr[-1]
        rows = []
        for name, p0 in first["rigids"].items():
            p1 = last["rigids"].get(name)
            if p1 is None:
                continue
            rows.append({"rigid": name,
                         "move": round(math.dist(p0, p1), 5),
                         "from": p0, "to": p1})
        rows.sort(key=lambda r: -r["move"])
        live[v] = rows[:12]
    out["rigid_motion"] = live

    with open(os.path.join(PROBE, "comparison.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)

    md = ["# M01 胸口三变体对照", ""]
    md.append("| 变体 | 物理 | is_built | 刚体 | 胸口 COPY_* 约束 | 约束总数 |")
    md.append("|---|---|---|---:|---:|---|")
    for v, meta in out["variants"].items():
        md.append("| %s | %s | %s | %d | %d | %s |"
                  % (v, meta["physics"], meta["is_built"], meta["rigids"],
                     meta["chest_cons_total"], meta["constraints"]))
    md.append("")
    md.append("| 帧 | 变体 | 胸 extent(x,y,z) | 胸/髋 |")
    md.append("|---:|---|---|---:|")
    for f in sorted(frame_rows, key=int):
        for v in ("baseline", "mode0", "static"):
            m = out["frames"][str(f)]["metrics"].get(v)
            if m:
                md.append("| f%s | %s | %s | %s |"
                          % (f, v, m["chest_extent"], m["chest_hip_ratio"]))
    md.append("")
    md.append("| 帧 | 对 | n | mean | p95 | max |")
    md.append("|---:|---|---:|---:|---:|---:|")
    for f in sorted(frame_rows, key=int):
        rec = out["frames"][str(f)]
        for a, b in PAIRS:
            key = "%s_vs_%s" % (a, b)
            if key not in rec:
                continue
            md.append("| f%s | %s | %d | %.5f | %.5f | %.5f |"
                      % (f, key, rec[key]["n"], rec[key]["mean"],
                         rec[key]["p95"], rec[key]["max"]))
    md.append("")
    if live:
        md.append("## 物理活性（首帧→末帧刚体世界位移，top）")
        md.append("")
        for v, rows in live.items():
            md.append("- %s: " % v + ", ".join("%s %.4f" % (r["rigid"], r["move"]) for r in rows[:6]))
        md.append("")
    with open(os.path.join(PROBE, "comparison.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")

    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
