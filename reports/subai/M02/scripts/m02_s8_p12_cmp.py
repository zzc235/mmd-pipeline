"""M02 · P12 离线判定：I_fresh 冷跳 f109 是否等于 P0[109]。

    python m02_s8_p12_cmp.py

比较三组：
  probe.pos      （新进程打开 I_fresh.blend，直接 frame_set(109)）
  make.seq_pos["109"]（同一进程顺序跑到 109）
  P0[109]        （已知的重算基准）
另落 make.seq_pos["240"] vs P0[240]，确认顺序整段走完也对得上。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S8 = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(ROOT))), "out", "subai", "M02", "s8")
REP = ROOT


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_frame(frames_path, frame):
    with open(frames_path, "r", encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec["frame"] == frame:
                return rec["pos"]
    raise SystemExit("frame %d not found in %s" % (frame, frames_path))


HEM = ["%03d_下擺_0_%d" % (42 + i, i) for i in range(18)]


def diff(a, b, label):
    common = sorted(set(a) & set(b))
    if not common:
        return {"label": label, "error": "no common bodies", "na": len(a), "nb": len(b)}
    d = {}
    for k in common:
        pa, pb = a[k], b[k]
        d[k] = ((pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2 + (pa[2] - pb[2]) ** 2) ** 0.5
    vals = sorted(d.values())
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    hem_vals = [d[k] for k in HEM if k in d]
    out = {"label": label,
           "bodies_compared": len(common),
           "only_in_a": len(only_a), "only_in_b": len(only_b),
           "D_all": round(sum(vals), 6),
           "D_max": round(vals[-1], 6),
           "D_max_bone": max(d, key=lambda k: d[k]),
           "D_hem_max": round(max(hem_vals), 6) if hem_vals else None,
           "D_hem_sum": round(sum(hem_vals), 6) if hem_vals else None,
           "nonzero": sum(1 for v in vals if v > 0.0),
           "bitwise_identical": sum(1 for v in vals if v == 0.0) == len(vals)}
    if only_a:
        out["only_in_a_sample"] = only_a[:5]
    if only_b:
        out["only_in_b_sample"] = only_b[:5]
    return out


def main():
    mk = load_json(os.path.join(REP, "p12_make.json"))
    pr = load_json(os.path.join(REP, "p12_probe.json"))
    p0_path = os.path.join(S8, "P0", "frames.jsonl")

    results = []
    seq109 = mk["seq_pos"]["109"]
    seq240 = mk["seq_pos"]["240"]
    p0_109 = load_frame(p0_path, 109)
    p0_240 = load_frame(p0_path, 240)

    results.append(diff(seq109, p0_109, "seq@109 vs P0[109]"))
    results.append(diff(pr["pos"], p0_109, "probe(冷跳)@109 vs P0[109]"))
    results.append(diff(seq240, p0_240, "seq@240 vs P0[240]"))

    # 顺序跑 vs 冷跳：同一份文件、同一个帧
    results.append(diff(pr["pos"], seq109, "probe(冷跳)@109 vs seq@109"))

    obj = {"point": "P12",
           "src": mk["src"], "src_untouched": mk["src_untouched"],
           "dst": mk["dst"], "dst_sha256": mk["dst_sha256"],
           "walk": mk["walk"], "bodies": mk["bodies"],
           "cache_at_open": mk["cache_at_open"],
           "cache_after_free": mk["cache_after_free"],
           "cache_after_walk": mk["cache_after_walk"],
           "probe_cache_at_open": pr["cache_at_open"],
           "probe_cache_after_step": pr["cache_after_step"],
           "probe_cold_jump": pr["cold_jump"],
           "comparisons": results}

    key = results[1]
    obj["verdict"] = ("EQUAL_TO_P0" if key["bitwise_identical"]
                      else ("MEASURED_DIFFERENT" if key.get("bodies_compared") else "NOT_MEASURED"))
    out_path = os.path.join(REP, "p12_cmp.json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")

    print("verdict:", obj["verdict"])
    print("cache after free :", mk["cache_after_free"])
    print("cache after walk :", mk["cache_after_walk"])
    print("cache at reopen  :", pr["cache_at_open"])
    for r in results:
        if "error" in r:
            print(" ", r["label"], "ERROR", r["error"])
            continue
        print("  %-28s D_all=%.6f D_max=%.6f(%s) hem_max=%s nonzero=%d/%d bitwise=%s"
              % (r["label"], r["D_all"], r["D_max"], r["D_max_bone"],
                 r["D_hem_max"], r["nonzero"], r["bodies_compared"], r["bitwise_identical"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
