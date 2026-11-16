"""通用比对：一份 probe JSON 的刚体坐标 vs 某个 `frames.jsonl` 的同一帧。

    python m02_frame_cmp.py <probe.json> <frames.jsonl> <frame> <label> <out.json> [<probe.json> ...]

支持传多份 probe（每份与同一参考帧比），也支持同一份 probe 与多份参考比：用
`--ref <frames.jsonl>:<frame>:<label>` 的形式重复给出。
"""
import json
import os
import sys


def load_probe(path):
    with open(path, "r", encoding="utf-8") as fh:
        obj = json.load(fh)
    return obj, obj["pos"]


def load_frame(path, frame):
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec["frame"] == frame:
                return rec["pos"]
    raise SystemExit("frame %d 不在 %s" % (frame, path))


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
    hem = [d[k] for k in HEM if k in d]
    return {"label": label,
            "bodies_compared": len(common),
            "only_in_a": sorted(set(a) - set(b))[:5],
            "only_in_b": sorted(set(b) - set(a))[:5],
            "D_all": round(sum(vals), 6),
            "D_max": round(vals[-1], 6),
            "D_max_bone": max(d, key=lambda k: d[k]),
            "D_hem_max": round(max(hem), 6) if hem else None,
            "D_hem_sum": round(sum(hem), 6) if hem else None,
            "nonzero": sum(1 for v in vals if v > 0.0),
            "bitwise_identical": all(v == 0.0 for v in vals)}


def main():
    argv = sys.argv[1:]
    probe_path = argv[0]
    refs = []
    out_path = None
    i = 1
    while i < len(argv):
        if argv[i] == "--ref":
            frames, frame, label = argv[i + 1].split("|")
            refs.append((frames, int(frame), label))
            i += 2
        else:
            out_path = argv[i]
            i += 1
    if not refs or out_path is None:
        raise SystemExit("usage: m02_frame_cmp.py <probe.json> --ref <frames.jsonl>|<frame>|<label> … <out.json>")

    probe, pos = load_probe(probe_path)
    results = []
    for frames, frame, label in refs:
        results.append(diff(pos, load_frame(frames, frame), "%s（%s@%d）" % (label, os.path.basename(frames), frame)))

    obj = {"probe": probe_path, "frame": probe.get("frame"),
           "cache_at_open": probe.get("cache_at_open"),
           "cache_after_step": probe.get("cache_after_step"),
           "cold_jump": probe.get("cold_jump"),
           "bodies": probe.get("bodies"),
           "comparisons": results}
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")

    for r in results:
        if "error" in r:
            print("%-34s ERROR %s" % (r["label"], r["error"]))
            continue
        print("%-34s D_all=%.6f D_max=%.6f(%s) hem_max=%s nonzero=%d/%d bitwise=%s"
              % (r["label"], r["D_all"], r["D_max"], r["D_max_bone"], r["D_hem_max"],
                 r["nonzero"], r["bodies_compared"], r["bitwise_identical"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
