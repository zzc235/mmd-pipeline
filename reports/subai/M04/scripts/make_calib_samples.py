"""M04-calib 合成坏样本生成器（只改 JSONL，绝不碰 .blend）

四个合成样本，每个只改一个量，`evidence_mode` 一律 `synthetic`：
  B1 overshoot-spike  : p95 不超 120，但 5 帧抬到 150° → 尖峰判据单独生效
  B2 overshoot-tail   : 多数帧 130°、少数 260° → p95>120 且 max>200
  B3 frozen           : 18 根骨 angle_deg 恒 0.0，父链 parent_delta_deg 恒 60° ≥ 15°
  B4 penetration-deep : 穿透 JSONL 某帧改成 −0.25 m（口径 mesh）

用法：
  python make_calib_samples.py --dynamics <frames.jsonl> --outdir <dir>
产物：<outdir>/<name>.dynamics.jsonl（+ B4 另给 .penetration.jsonl）与 manifest.json
"""
import argparse
import hashlib
import json
import os


def load(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def dump(rows, path):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return sha256(path)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def build(rows, which):
    out = [dict(r) for r in rows]
    frames = sorted({int(r["frame"]) for r in out})
    if which == "B1_overshoot_spike":
        picks = set(frames[::max(1, len(frames) // 5)][:5])
        for r in out:
            if int(r["frame"]) in picks:
                r["angle_deg"] = 150.0
    elif which == "B2_overshoot_tail":
        for r in out:
            f = int(r["frame"])
            r["angle_deg"] = 260.0 if f <= frames[min(3, len(frames) - 1)] else 130.0
    elif which == "B3_frozen":
        for r in out:
            r["angle_deg"] = 0.0
            r["parent_delta_deg"] = 60.0
    return out


def penetration_rows(rows, deep_value):
    """B4：每帧一条 ROI 记录，其中一帧改成深穿。"""
    frames = sorted({int(r["frame"]) for r in rows})
    mid = frames[len(frames) // 2]
    out = []
    for f in frames:
        out.append({"frame": f, "roi": "18_skirt_capsule", "max_depth_m": 0.0,
                    "bone": None, "basis": "capsule"})
    for r in out:
        if r["frame"] == mid:
            r["max_depth_m"] = deep_value
    return out, mid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dynamics", required=True)
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    rows = load(a.dynamics)
    manifest = {"source": {"path": a.dynamics, "sha256": sha256(a.dynamics),
                           "rows": len(rows)},
                "note": "合成样本只用于 M04-calib 的结构验证，不得用于宣称门限有效",
                "samples": []}
    for name in ("B1_overshoot_spike", "B2_overshoot_tail", "B3_frozen"):
        p = os.path.join(a.outdir, name + ".dynamics.jsonl")
        digest = dump(build(rows, name), p)
        manifest["samples"].append({"name": name, "kind": "dynamics", "path": p,
                                    "sha256": digest, "evidence_mode": "synthetic",
                                    "changed": "angle_deg" if name != "B3_frozen"
                                    else "angle_deg+parent_delta_deg"})
    pen, mid = penetration_rows(rows, -0.25)
    pp = os.path.join(a.outdir, "B4_penetration_deep.penetration.jsonl")
    digest = dump(pen, pp)
    manifest["samples"].append({"name": "B4_penetration_deep", "kind": "penetration",
                                "path": pp, "sha256": digest, "evidence_mode": "synthetic",
                                "changed": "max_depth_m@frame=%d -> -0.25" % mid,
                                "basis": "capsule"})
    mp = os.path.join(a.outdir, "manifest.json")
    with open(mp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    print("manifest:", mp, sha256(mp))
    for s in manifest["samples"]:
        print(" ", s["name"], s["sha256"][:16])


main()
