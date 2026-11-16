"""M02 · 已有 10 套动态样本的两两比对（不跑 Blender）。

    python m02_dyn_diff.py <out.json> <dirA> <dirB> [<dirC> <dirD> ...]

只比 `angle_deg` / `rot_x_deg` 两列（两套共有列），按 (frame, bone) 对齐。
输出每个目录的 `point_cache_baked`（从 meta.json 里读不到就写 null）、行数、文件 sha256，
以及每对的最大绝对差与不同行数。
"""
import hashlib
import json
import os
import sys


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(dirpath):
    rows = {}
    with open(os.path.join(dirpath, "frames.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            rows[(r["frame"], r["bone"])] = r
    return rows


def main():
    out_path = sys.argv[1]
    dirs = sys.argv[2:]
    info, data = {}, {}
    for d in dirs:
        meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
        fp = os.path.join(d, "frames.jsonl")
        data[d] = load(d)
        info[d] = {"rows": len(data[d]), "sha256": sha(fp),
                   "columns": meta.get("columns"), "blend": meta.get("blend", {}).get("path"),
                   "blend_sha256": meta.get("blend", {}).get("sha256"),
                   "point_cache_baked": meta.get("point_cache", {}).get("is_baked") if meta.get("point_cache") else None}

    pairs = []
    for i in range(0, len(dirs) - 1, 2):
        a, b = dirs[i], dirs[i + 1]
        da, db = data[a], data[b]
        keys = sorted(set(da) & set(db))
        dmax = 0.0
        dmax_at = None
        ndiff = 0
        for k in keys:
            for col in ("angle_deg", "rot_x_deg"):
                va, vb = da[k].get(col), db[k].get(col)
                if va is None or vb is None:
                    continue
                delta = abs(va - vb)
                if delta > dmax:
                    dmax, dmax_at = delta, {"frame": k[0], "bone": k[1], "column": col}
                if delta > 1e-6:
                    ndiff += 1
        pairs.append({"a": a, "b": b, "rows_compared": len(keys),
                      "max_abs_diff_deg": round(dmax, 9), "max_at": dmax_at,
                      "rows_over_1e-6": ndiff,
                      "frames_jsonl_identical": info[a]["sha256"] == info[b]["sha256"]})

    out = {"samples": info, "pairs": pairs,
           "note": "point_cache_baked 只有当 meta.json 里有 point_cache 字段时才有值；"
                   "早期采样的 meta 没记这项，写 null 而非猜 0/False。"}
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    for p in pairs:
        print("%-22s vs %-22s max|d|=%.9f deg  rows>1e-6=%d  identical=%s"
              % (os.path.basename(p["a"]), os.path.basename(p["b"]),
                 p["max_abs_diff_deg"], p["rows_over_1e-6"], p["frames_jsonl_identical"]))


main()
