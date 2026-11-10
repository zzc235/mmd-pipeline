"""今晚的验证：PMX 写回是否字节安全 + 净空修复能否复现你的 fixH。"""
import hashlib
import os
import sys

sys.path.insert(0, r"E:/dsh pr/woker2")

from mmdpipe import clearance as C
from mmdpipe import pmx as P

SRC = r"E:/blender模型/星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309/星穹铁道—卡芙卡无外套/卡芙卡3.0.pmx"
REF = r"E:/code/Blender/kafuka_short/01_pmx/卡芙卡3.0_fixH.pmx"
OUT = r"E:/dsh pr/woker2/out/卡芙卡3.0_fixH_mine.pmx"


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def diff_positions(a, b):
    n = min(len(a.rigids), len(b.rigids))
    rows = []
    for i in range(n):
        pa, pb = a.rigids[i].position, b.rigids[i].position
        d = max(abs(pa[k] - pb[k]) for k in range(3))
        if d > 1e-7:
            rows.append((i, a.rigids[i].name, d, pa, pb))
    return rows


m = P.load(SRC)
print("解析 %s  刚体 %d 关节 %d" % (os.path.basename(SRC), len(m.rigids), len(m.joints)))

# 1 往返一致
P.patch_save(m, OUT + ".roundtrip.pmx")
print("往返字节一致:", sha(SRC) == sha(OUT + ".roundtrip.pmx"))

# 2 净空扫描
rep = C.scan(m)
print("头部胶囊来源 %s，扫到 %d 条记录，侵入 %d 条，其中可碰撞且非关节连 %d 条"
      % (rep.head_source, len(rep.hits), len(rep.penetrating), len(rep.collidable_penetrating)))
for h in rep.penetrating[:6]:
    print("  %-16s vs %-10s 深度 %+.2f mm  可碰撞=%s 关节连=%s"
          % (h.body_name[:16], h.capsule_name[:10], C.to_mm(h.depth), h.collidable, h.jointed))

# 3 修复
plan = C.plan_fix(m, margin=0.06)
print("修复：动了 %d 个刚体 %s，同步 %d 个关节，%d 轮，收敛=%s"
      % (len(plan["moved"]), plan["moved"], len(plan["joint_pos"]),
         plan["rounds"], plan["complete"]))
if plan["remaining"]:
    print("  残留:", plan["remaining"])
for idx in plan["moved"]:
    rb = m.rigids[idx]
    print("  动 %-16s -> %s" % (rb.name, tuple(round(v, 5) for v in rb.position)))

# 4 写回 + 重载校验
P.patch_save(m, OUT, plan["rigid_pos"], plan["joint_pos"])
m2 = P.load(OUT)
print("写回后重载：刚体 %d 关节 %d，字节对齐 %s"
      % (len(m2.rigids), len(m2.joints), m2.bytes_consumed == m2.bytes_total))
rep2 = C.scan(m2)
print("写回后再扫：可碰撞侵入 %d 条" % len(rep2.collidable_penetrating))

# 5 和你的 fixH 对答案
if os.path.exists(REF):
    ref = P.load(REF)
    rows = diff_positions(ref, m2)
    print()
    print("vs 你的 fixH：位置不同的刚体 %d 个" % len(rows))
    for i, name, d, pa, pb in rows[:10]:
        print("  #%-3d %-16s 你的 %s  我的 %s  差 %.2f mm"
              % (i, name[:16], tuple(round(v, 4) for v in pa),
                 tuple(round(v, 4) for v in pb), d * 1000))
    # 反向：你动了但我没动的
    ref_moved = {i for i, *_ in rows}
    print("  我动了 %s" % plan["moved"])
    print("  你动了 %s" % sorted(ref_moved))
else:
    print("参考文件不存在：%s" % REF)
