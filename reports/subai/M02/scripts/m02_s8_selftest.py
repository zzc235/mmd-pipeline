import json
import math
import sys

p = sys.argv[1]
rows = [json.loads(l) for l in open(p, encoding="utf-8")]
names = sorted(rows[0]["pos"])
hem = [n for n in names if n.split("_", 1)[-1].startswith("下擺_0_")]
print("frames", len(rows), "objects", len(names), "hem", len(hem))


def dist(a, b):
    return math.dist(a, b)


for n in hem[:4] + hem[-2:]:
    p0 = rows[0]["pos"][n]
    span = max(dist(p0, r["pos"][n]) for r in rows)
    print(n, "f1", [round(v, 4) for v in p0], "f240", [round(v, 4) for v in rows[-1]["pos"][n]],
          "span_m", round(span, 4))

moved = [n for n in names if max(dist(rows[0]["pos"][n], r["pos"][n]) for r in rows) > 1e-3]
print("objects moved >1mm:", len(moved))
print("sample moved:", moved[:5])
