"""在四个角色模型上跑判断器，看它能不能自己认出"袖子焊死 / 头发可动"。"""
import glob
import os
import sys

sys.path.insert(0, r"E:/dsh pr/woker2")

from mmdpipe import pmx as P
from mmdpipe import physics as PH

TARGETS = [
    r"E:/blender模型/没有外套本家模型/星穹铁道—飞霄（无外套）.pmx",
    r"E:/blender模型/绯樱/星穹铁道—绯英.pmx",
    r"E:/blender模型/星穹铁道—赛飞儿（含武器）_by_崩坏：星穹铁道_16381d4bdeb9a77130eb411af091b02f/星穹铁道—赛飞儿3.pmx",
    r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309/星穹铁道—卡芙卡无外套/卡芙卡3.0.pmx",
    r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309/星穹铁道—卡芙卡无外套/刀.pmx",
]

for path in TARGETS:
    if not os.path.exists(path):
        print("缺失：%s" % path)
        continue
    m = P.load(path)
    rep = PH.classify(m)
    print(PH.render_text(rep))
    print()
