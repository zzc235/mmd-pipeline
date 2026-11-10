"""净空修复 + 验证：对任意 PMX 跑一遍（默认在副本上）。"""
import os
import sys

sys.path.insert(0, r"E:/dsh pr/woker2")

from mmdpipe import clearance as C
from mmdpipe import pmx as P
from mmdpipe import verify_pmx as V

if len(sys.argv) < 2:
    print("用法: python test_fix_model.py <pmx> [outdir]")
    raise SystemExit(1)

SRC = sys.argv[1]
OUTDIR = sys.argv[2] if len(sys.argv) > 2 else r"E:/dsh pr/woker2/out"
stem = os.path.splitext(os.path.basename(SRC))[0]
DST = os.path.join(OUTDIR, stem + "_fixH.pmx")

orig = P.load(SRC)
rep0 = C.scan(orig)
print("源：%s" % os.path.basename(SRC))
print("  头部胶囊 %d 个（识别来源 %s）" % (len(C.head_capsules(orig)[0]), rep0.head_source))
print("  可碰撞侵入 %d 个" % len(rep0.collidable_penetrating))
for h in sorted(rep0.collidable_penetrating, key=lambda x: -x.depth)[:6]:
    print("    %-16s vs %-10s %+.2f mm" % (h.body_name[:16], h.capsule_name[:10], C.to_mm(h.depth)))

plan = C.plan_fix(orig, margin=0.06)
print("修复：动了 %d 个刚体，同步 %d 个关节，%d 轮，收敛=%s"
      % (len(plan["moved"]), len(plan["joint_pos"]), plan["rounds"], plan["complete"]))
if plan["remaining"]:
    print("  残留：", plan["remaining"])

P.patch_save(orig, DST, plan["rigid_pos"], plan["joint_pos"])
fixed = P.load(DST)
print("写回：%s（%d 字节，对齐 %s）"
      % (DST, os.path.getsize(DST), fixed.bytes_consumed == fixed.bytes_total))
print()
print(V.verify(P.load(SRC), fixed, plan).text())
