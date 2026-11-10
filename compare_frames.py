"""逐帧比对两次渲染，判断"稳定复现"是否成立。"""
import os
import sys

import numpy as np
from PIL import Image


def compare(a_dir: str, b_dir: str, n: int):
    total = 0.0
    identical = 0
    worst = (0.0, None)
    missing = 0
    for i in range(1, n + 1):
        pa = os.path.join(a_dir, "s_%04d.png" % i)
        pb = os.path.join(b_dir, "s_%04d.png" % i)
        if not (os.path.exists(pa) and os.path.exists(pb)):
            missing += 1
            continue
        A = np.asarray(Image.open(pa).convert("RGB"), dtype=np.int16)
        B = np.asarray(Image.open(pb).convert("RGB"), dtype=np.int16)
        if A.shape != B.shape:
            print("尺寸不一致 @%d: %s vs %s" % (i, A.shape, B.shape))
            return
        diff = np.abs(A - B)
        m = float(diff.mean())
        total += m
        if m == 0.0:
            identical += 1
        if m > worst[0]:
            worst = (m, i)

    checked = n - missing
    print("比对帧数      %d（缺 %d）" % (checked, missing))
    print("逐像素完全相同  %d / %d" % (identical, checked))
    print("平均绝对差    %.6f / 255" % (total / checked if checked else 0))
    print("最差帧        %s  差 %.6f" % (worst[1], worst[0]))
    if worst[1]:
        pa = os.path.join(a_dir, "s_%04d.png" % worst[1])
        pb = os.path.join(b_dir, "s_%04d.png" % worst[1])
        A = np.asarray(Image.open(pa).convert("RGB"), dtype=np.float64)
        B = np.asarray(Image.open(pb).convert("RGB"), dtype=np.float64)
        mse = float(((A - B) ** 2).mean())
        if mse == 0:
            print("最差帧 PSNR   inf（完全相同）")
        else:
            print("最差帧 PSNR   %.2f dB" % (10 * np.log10(255.0 ** 2 / mse)))


if __name__ == "__main__":
    compare(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 360)
