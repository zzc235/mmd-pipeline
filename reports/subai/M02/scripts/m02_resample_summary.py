"""M02 · 加列重采样的汇总（B2r 两版）：新列 `bone_world_delta_deg` 的分布 + 与旧样的可比性。

    python m02_resample_summary.py <out.json> <B2r_baseline_dir> <B2r_x07_dir> <B2_baseline_dir> <B2_x07_dir>
"""
import hashlib
import json
import os
import statistics
import sys


def load(d):
    rows = {}
    with open(os.path.join(d, "frames.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            rows.setdefault(r["bone"], []).append(r)
    return rows


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def summarize(d):
    data = load(d)
    per = {}
    for bone, rows in data.items():
        rows.sort(key=lambda r: r["frame"])
        angles = [r["angle_deg"] for r in rows]
        wd = [r["bone_world_delta_deg"] for r in rows if r["bone_world_delta_deg"] is not None]
        per[bone] = {
            "angle_span_deg": round(max(angles) - min(angles), 6),
            "world_delta_max_deg": round(max(wd), 6) if wd else None,
            "world_delta_p50_deg": round(statistics.median(wd), 6) if wd else None,
            "world_delta_nonzero_rows": sum(1 for v in wd if v is not None and v > 1e-6),
            "world_delta_rows": len(wd),
            "first_row_null": rows[0]["bone_world_delta_deg"] is None,
        }
    return per


def main():
    out_path = sys.argv[1]
    new_b, new_x, old_b, old_x = sys.argv[2:6]
    res = {"samples": {}, "per_bone": {}}
    for tag, d in (("B2r_baseline", new_b), ("B2r_x07", new_x)):
        fp = os.path.join(d, "frames.jsonl")
        meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
        res["samples"][tag] = {"sha256": sha(fp), "size": os.path.getsize(fp),
                               "columns": meta.get("columns"), "rows": meta.get("row_count"),
                               "blend": meta.get("blend", {}).get("path"),
                               "blend_sha256": meta.get("blend", {}).get("sha256"),
                               "frames": meta.get("frames"),
                               "point_cache_baked": (meta.get("point_cache") or {}).get("is_baked")}
        res["per_bone"][tag] = summarize(d)

    # 与旧样逐行比 angle_deg / rot_x_deg（可比性证明）
    comp = {}
    for tag, newd, oldd in (("baseline", new_b, old_b), ("x07", new_x, old_x)):
        a, b = load(newd), load(oldd)
        worst = 0.0
        rows_cmp = 0
        for bone in set(a) & set(b):
            ra = {r["frame"]: r for r in a[bone]}
            rb = {r["frame"]: r for r in b[bone]}
            for f in set(ra) & set(rb):
                for col in ("angle_deg", "rot_x_deg", "rot_y_deg", "rot_z_deg"):
                    if col in rb[f] and col in ra[f]:
                        worst = max(worst, abs(ra[f][col] - rb[f][col]))
                        rows_cmp += 1
        comp[tag] = {"rows_compared": rows_cmp, "max_abs_diff_deg": round(worst, 9)}
    res["comparability_vs_old_samples"] = comp
    res["note"] = ("B2r 与 B2 只差新列：angle_deg / rot_x·y·z_deg 逐行最大差 0.0，"
                   "新增列 `bone_world_delta_deg` 是同一份轨迹上的新观测量，不改旧列语义。")

    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print(json.dumps(res["comparability_vs_old_samples"], ensure_ascii=False))
    for tag, per in res["per_bone"].items():
        worst = max(per.items(), key=lambda kv: kv[1]["world_delta_max_deg"] or 0)
        print(tag, "bones=%d" % len(per), "max world_delta=%s deg @%s"
              % (worst[1]["world_delta_max_deg"], worst[0]),
              "nonzero_rows_total=%d" % sum(v["world_delta_nonzero_rows"] for v in per.values()))


main()
