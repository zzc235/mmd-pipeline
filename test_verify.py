"""净空修复 + 8 项验证，一条命令跑完。"""
import sys

sys.path.insert(0, r"E:/dsh pr/woker2")

from mmdpipe import clearance as C
from mmdpipe import pmx as P
from mmdpipe import verify_pmx as V

SRC = r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309/星穹铁道—卡芙卡无外套/卡芙卡3.0.pmx"
OUT = r"E:/dsh pr/woker2/out/卡芙卡3.0_fixH_mine.pmx"

orig = P.load(SRC)
plan = C.plan_fix(orig, margin=0.06)
P.patch_save(orig, OUT, plan["rigid_pos"], plan["joint_pos"])
fixed = P.load(OUT)

print("动了 %d 个刚体 %s，同步 %d 个关节，%d 轮"
      % (len(plan["moved"]), plan["moved"], len(plan["joint_pos"]), plan["rounds"]))
print()
print(V.verify(P.load(SRC), fixed, plan).text())
