"""批量预检：把手上所有 PMX 过一遍纯 Python 解析，看泛化边界在哪。"""
import glob
import os
import sys

sys.path.insert(0, r"E:/dsh pr/woker2")

from mmdpipe import pmx as P
from mmdpipe import vmd as V
from mmdpipe import match as M

ROOT = r"E:/blender模型"
models = sorted(glob.glob(os.path.join(ROOT, "**", "*.pmx"), recursive=True))
motions = sorted(glob.glob(os.path.join(ROOT, "**", "*.vmd"), recursive=True))

print("%-34s %6s %6s %5s %5s %5s %5s %6s %6s" %
      ("模型", "顶点", "骨", "材质", "表情", "刚体", "关节", "掩码", "对齐"))
print("-" * 100)
ok_models = []
for path in models:
    name = os.path.basename(path)[:32]
    try:
        m = P.load(path)
        c = P.census(m)
        aligned = "✓" if c["bytes_consumed"] == c["bytes_total"] else "%d/%d" % (
            c["bytes_consumed"], c["bytes_total"])
        sem = "碰撞" if "参与碰撞" in c["resolved_semantics"] else "忽略"
        print("%-34s %6d %6d %5d %5d %5d %5d %6d %6s%s" %
              (name, c["vertices"], c["bones"], c["materials"], c["morphs"],
               c["rigids"], c["joints"], c["same_group_pairs_bitset"], sem, aligned))
        if c["tail_error"]:
            print("      !! tail_error: %s" % c["tail_error"])
        ok_models.append((path, m, c))
    except Exception as exc:
        print("%-34s  解析失败：%s" % (name, exc))

print()
print("VMD：")
for path in motions:
    try:
        v = V.load(path)
        fr = v.frame_range
        print("  %-42s 骨轨 %3d 关键帧 %6d 帧 %d..%d 表情 %d" %
              (os.path.basename(path)[:40], len(v.bone_tracks), v.keyframes, fr[0], fr[1],
               len(v.morph_tracks)))
    except Exception as exc:
        print("  %-42s 解析失败：%s" % (os.path.basename(path)[:40], exc))

if ok_models:
    print()
    print("交叉匹配（第一个 VMD 对各模型）：")
    try:
        motion = V.load(motions[0])
        for path, m, c in ok_models:
            r = M.build(m, motion)
            print("  %-30s 覆盖 %.1f%%  缺失骨 %d  %s" %
                  (m.name[:28], r.coverage_frames * 100, len(r.bone_miss),
                   r.verdict.upper()))
            if r.bone_miss:
                print("      缺：%s" % ", ".join(r.bone_miss[:6]))
    except Exception as exc:
        print("  跳过：%s" % exc)
