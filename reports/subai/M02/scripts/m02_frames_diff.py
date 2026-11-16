"""比两段 frames.jsonl（M02 S8 变体）：逐帧最大位移、以及指定帧逐刚体最大距离。

    python m02_frames_diff.py <a.jsonl> <b.jsonl> [frame ...]
"""
import json
import math
import sys


def load(path):
    rows = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            rows[row["frame"]] = row["pos"]
    return rows


def dist(p, q):
    return math.sqrt(sum((p[i] - q[i]) ** 2 for i in range(3)))


def main(argv):
    a, b = argv[1], argv[2]
    frames = [int(x) for x in argv[3:]] or [109, 240]
    ra, rb = load(a), load(b)
    common = sorted(set(ra) & set(rb))
    worst_frame, worst = None, -1.0
    for f in common:
        names = set(ra[f]) & set(rb[f])
        m = max((dist(ra[f][n], rb[f][n]) for n in names), default=0.0)
        if m > worst:
            worst_frame, worst = f, m
    print("frames=%d 全程逐帧最大位移 %.6f m @f%s"
          % (len(common), worst, worst_frame))
    for f in frames:
        if f not in ra or f not in rb:
            print("  f%-4d 缺帧" % f)
            continue
        names = set(ra[f]) & set(rb[f])
        m = max((dist(ra[f][n], rb[f][n]) for n in names), default=0.0)
        moved = sum(1 for n in names if dist(ra[f][n], rb[f][n]) > 1e-6)
        print("  f%-4d 逐刚体最大距离 %.6f m  （>1e-6 的刚体 %d/%d）"
              % (f, m, moved, len(names)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
