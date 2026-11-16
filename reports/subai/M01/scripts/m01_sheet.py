"""把同帧同机位的对比图拼成一张带标注的对照表（PIL）。

    python m01_sheet.py
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

FONT = r"C:\Windows\Fonts\msyh.ttc"


def font(size):
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default()


def build(out_path, title, rows, cols, cells, note=""):
    """cells[(row, col)] = png 路径。"""
    tile = 400
    pad = 12
    head = 54
    left = 250
    top = head + 40
    bottom = 70 if note else 30
    w = left + len(cols) * (tile + pad) + pad
    h = top + len(rows) * (tile + pad) + bottom
    sheet = Image.new("RGB", (w, h), (30, 32, 36))
    d = ImageDraw.Draw(sheet)
    d.text((pad, 14), title, font=font(26), fill=(240, 240, 240))
    for ci, cname in enumerate(cols):
        x = left + ci * (tile + pad)
        d.text((x + 6, head + 6), cname, font=font(20), fill=(180, 210, 250))
    for ri, rname in enumerate(rows):
        y = top + ri * (tile + pad)
        d.text((pad, y + tile // 2 - 14), rname, font=font(20), fill=(220, 220, 220))
        for ci in range(len(cols)):
            path = cells.get((ri, ci))
            x = left + ci * (tile + pad)
            if path and os.path.exists(path):
                im = Image.open(path).convert("RGB")
                im.thumbnail((tile, tile))
                sheet.paste(im, (x, y))
            else:
                d.rectangle([x, y, x + tile, y + tile], outline=(90, 90, 90))
                d.text((x + 10, y + 10), "missing", font=font(16), fill=(200, 120, 120))
            d.rectangle([x, y, x + tile - 1, y + tile - 1], outline=(70, 72, 78))
    if note:
        d.text((pad, h - bottom + 10), note, font=font(17), fill=(200, 200, 200))
    sheet.save(out_path)
    print("SHEET", out_path, sheet.size)
    return out_path


def main():
    base = r"E:\dsh pr\woker2\out\subai\M01"
    chest = os.path.join(base, "shots_chest3")
    rows = ["f1", "f40"]
    cols = ["baseline（原 PMX, mode2, 物理开）", "static（关物理 = 纯跟随）",
            "mode0（补丁, mode 2→0, 物理开）"]
    cells = {}
    for ri, fr in enumerate((1, 40)):
        for ci, label in enumerate(("baseline", "static", "mode0")):
            cells[(ri, ci)] = os.path.join(chest, "sheet_%s_f%04d.png" % (label, fr))
    build(os.path.join(base, "compare_chest.png"),
          "M01 · 飞霄胸口 S3（EMO_Sway 动作，同帧同机位，中性灰材质只比形状）",
          rows, cols, cells,
          "判据：mode0 与 static 的胸口顶点逐帧差 = 0.00000；baseline 与 static 差 0.233 m（均值）。"
          "视觉终审待用户确认。")

    sleeve = os.path.join(base, "shots_sleeve")
    rows2 = ["f30", "f45"]
    cols2 = ["base（physics-policy=off）", "static（physics-policy=strict，静音袖筒 48 骨）"]
    cells2 = {}
    for ri, fr in enumerate((30, 45)):
        for ci, label in enumerate(("base", "static")):
            cells2[(ri, ci)] = os.path.join(sleeve, "sheet_%s_f%04d.png" % (label, fr))
    build(os.path.join(base, "compare_sleeve.png"),
          "M01 · 卡芙卡袖筒 S5（PERF_Wushu 动作，同帧同机位）",
          rows2, cols2, cells2,
          "判据：静态策略把袖筒骨 >45°/帧 从 35 次降到 0 次、最大逐帧转角 343.3°→12.6°，"
          "但袖筒被拉成刚性长条（f45 包围盒 1.10×0.63 m）；base 在 f45 反而塌缩成 0.13×0.34 m——"
          "两边都不对，视觉终审待用户确认。")


if __name__ == "__main__":
    main()
