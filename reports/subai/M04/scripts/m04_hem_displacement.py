"""D0 任务 3：`下擺_0_*` 这 18 根的位移量级（纯观测，不取锁）。

数据：`out/subai/M02/s8/P0/frames.jsonl`，一行一帧：{"frame": n, "pos": {对象名: [x,y,z]}}。
只回答「在不在动、动多少」，不推断驱动来源。
"""
import json
import os

P = r"E:\dsh pr\woker2\out\subai\M02\s8\P0\frames.jsonl"
if not os.path.exists(P):
    raise SystemExit("missing: " + P)

frames = []
with open(P, encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if line:
            frames.append(json.loads(line))
print("frames", len(frames), "objects per frame", len(frames[0]["pos"]))

sample_key = next(iter(frames[0]["pos"]))
print("sample entry:", sample_key, frames[0]["pos"][sample_key])

names = set()
for f in frames:
    names |= set(f["pos"].keys())
target = sorted(n for n in names if "\u4e0b\u64fa_0_" in n)

out = []
for n in target:
    xs, ys, zs = [], [], []
    for f in frames:
        v = f["pos"].get(n)
        if not v:
            continue
        p = v if isinstance(v, list) else v.get("pos") or list(v.values())[:3]
        xs.append(float(p[0])); ys.append(float(p[1])); zs.append(float(p[2]))
    if not xs:
        continue
    rng = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    out.append({"obj": n, "frames": len(xs), "range_m": round(rng, 6)})
out.sort(key=lambda d: -d["range_m"])
summary = {
    "objects_matched": len(target),
    "frames": len(frames),
    "range_max_m": out[0]["range_m"] if out else None,
    "range_median_m": out[len(out) // 2]["range_m"] if out else None,
    "range_min_m": out[-1]["range_m"] if out else None,
    "top5": out[:5],
    "bottom3": out[-3:],
}
json.dump(summary, open(r"E:\dsh pr\woker2\out\subai\M04\penetration\hem_displacement.json",
                        "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=2)
print("[hem] " + json.dumps(summary, ensure_ascii=True))
