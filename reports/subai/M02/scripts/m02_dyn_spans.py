"""M02 · 10 套动态样本的每套角度跨度（判断哪几套真的在动 / 是不是同一段轨迹）。

    python m02_dyn_spans.py <out.json> <dir> [<dir> ...]
"""
import json
import os
import sys


def main():
    out_path, dirs = sys.argv[1], sys.argv[2:]
    out = {}
    for d in dirs:
        meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
        per = {}
        with open(os.path.join(d, "frames.jsonl"), encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                per.setdefault(r["bone"], []).append(r["angle_deg"])
        spans = {b: round(max(v) - min(v), 6) for b, v in per.items()}
        worst = max(spans.items(), key=lambda kv: kv[1])
        out[d] = {"bones": len(spans), "max_span_deg": worst[1], "max_span_bone": worst[0],
                  "span_下擺_0_0": spans.get("下擺_0_0"),
                  "point_cache_baked_meta": (meta.get("point_cache") or {}).get("is_baked"),
                  "elapsed_s": meta.get("elapsed_s")}
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    for d, r in out.items():
        print("%-24s bones=%2d max_span=%8.3f deg (%s) 下擺_0_0=%8.3f"
              % (os.path.basename(d), r["bones"], r["max_span_deg"], r["max_span_bone"],
                 r["span_下擺_0_0"] or 0.0))


main()
