"""两序列逐帧 PSNR / SSIM 对比。"""
import os
import sys

import numpy as np
from PIL import Image


def load(path):
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float64)


def psnr(a, b):
    mse = float(((a - b) ** 2).mean())
    if mse == 0:
        return float("inf")
    return 10 * np.log10(255.0 ** 2 / mse)


def ssim_global(a, b):
    ma, mb = a.mean(), b.mean()
    va, vb = a.var(), b.var()
    cov = ((a - ma) * (b - mb)).mean()
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    return ((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma ** 2 + mb ** 2 + c1) * (va + vb + c2))


def compare(dir_a, dir_b, n):
    rows = []
    missing = 0
    for i in range(1, n + 1):
        pa = os.path.join(dir_a, "s_%04d.png" % i)
        pb = os.path.join(dir_b, "s_%04d.png" % i)
        if not (os.path.exists(pa) and os.path.exists(pb)):
            missing += 1
            continue
        A, B = load(pa), load(pb)
        if A.shape != B.shape:
            print("尺寸不一致 @%d" % i)
            return
        rows.append((i, np.abs(A - B).mean(), psnr(A, B), ssim_global(A, B)))

    if not rows:
        print("无可比帧")
        return
    mad = np.array([r[1] for r in rows])
    ps = np.array([r[2] for r in rows])
    ss = np.array([r[3] for r in rows])
    identical = int((mad == 0).sum())
    finite = ps[np.isfinite(ps)]
    print("  帧数 %d（缺 %d）｜逐像素完全相同 %d" % (len(rows), missing, identical))
    print("  平均绝对差   %.4f / 255" % mad.mean())
    print("  PSNR         均值 %.2f dB（最低 %.2f）"
          % (finite.mean() if finite.size else float("inf"),
             finite.min() if finite.size else float("inf")))
    print("  SSIM         均值 %.6f（最低 %.6f）" % (ss.mean(), ss.min()))
    worst = rows[int(np.argmin(ps))] if finite.size else rows[0]
    print("  最差帧       #%d  PSNR %.2f dB  SSIM %.6f  差 %.4f"
          % (worst[0], worst[2], worst[3], worst[1]))
    best = rows[int(np.argmax(ps))] if finite.size else rows[0]
    print("  最像帧       #%d  PSNR %s  差 %.4f"
          % (best[0], "inf" if not np.isfinite(best[2]) else "%.2f dB" % best[2], best[1]))
    return rows


if __name__ == "__main__":
    print("A=%s\nB=%s" % (sys.argv[1], sys.argv[2]))
    compare(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 480)
