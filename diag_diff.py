"""定位两帧差异的来源：整体位移？还是内容不同？"""
import sys

import numpy as np
from PIL import Image

OLD = r"E:/code/Blender/feiying_short/04_render/sample/s_%04d.png"
NEW = r"E:/dsh pr/woker2/repro360/frames/s_%04d.png"


def load(fmt, i):
    return np.asarray(Image.open(fmt % i).convert("RGB"), dtype=np.float64)


def report(i):
    A, B = load(OLD, i), load(NEW, i)
    d = np.abs(A - B)
    print("frame %d  尺寸 %s" % (i, A.shape))
    print("  平均绝对差 %.3f" % d.mean())
    print("  差值>20 的像素占比 %.2f%%" % ((d.max(axis=2) > 20).mean() * 100))
    # 上/中/下三段分布
    h = d.shape[0]
    for name, sl in (("上部", slice(0, h // 3)), ("中部", slice(h // 3, 2 * h // 3)),
                     ("下部", slice(2 * h // 3, h))):
        print("    %s 平均差 %.3f" % (name, d[sl].mean()))
    # 整体平移搜索
    best = (d.mean(), 0, 0)
    for dy in range(-8, 9, 2):
        for dx in range(-8, 9, 2):
            Bs = np.roll(np.roll(B, dy, axis=0), dx, axis=1)
            m = np.abs(A - Bs).mean()
            if m < best[0]:
                best = (m, dx, dy)
    print("  最佳平移 (dx=%d, dy=%d) 后平均差 %.3f（原 %.3f）" % (best[1], best[2], best[0], d.mean()))
    # 亮度对比
    print("  平均亮度 old=%.2f new=%.2f" % (A.mean(), B.mean()))


for i in (1, 90, 180, 270, 360):
    report(i)
    print()
