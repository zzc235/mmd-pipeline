"""表情段逐条追踪。"""
import sys

sys.path.insert(0, r"E:/dsh pr/woker2")
from mmdpipe import pmx as P

PATH = r"E:/blender模型/绯樱/星穹铁道—绯英.pmx"
data = open(PATH, "rb").read()
enc = "utf-16-le"
vs, ts, ms, bs, mos, rs = 2, 1, 1, 2, 1, 2

r = P._Reader(data)
r.pos = 3505613          # 骨骼段之后
morph_count = P._Reader(data)
r.pos = 3505609
mc = r.i32()
print("morph_count", mc, "pos", r.pos)

for i in range(mc):
    start = r.pos
    try:
        name = r.text(enc)
        en = r.text(enc)
        panel = r.u8()
        mtype = r.u8()
        n = r.i32()
        print("morph[%2d] %-12s type=%-2d n=%-5d pos=%d" % (i, name[:12], mtype, n, start))
        if n < 0 or n > 200000:
            print("   !! n 不合理，停止")
            break
        for _ in range(n):
            if mtype == 0:
                r.index(mos); r.f32()
            elif mtype == 1:
                r.index(vs); r.f32n(3)
            elif mtype == 2:
                r.index(bs); r.f32n(3); r.f32n(4)
            elif 3 <= mtype <= 7:
                r.index(vs); r.f32n(4)
            elif mtype == 8:
                r.index(ms)
                r.f32n(4); r.f32n(3); r.f32(); r.f32n(3)
                r.f32n(4); r.f32()
                r.f32n(4); r.f32n(4); r.f32n(4)
            elif mtype == 9:
                r.index(mos); r.f32()
            elif mtype == 10:
                r.index(rs); r.u8(); r.f32n(3); r.f32n(3)
            else:
                print("   !! 未知类型")
                raise SystemExit
    except Exception as exc:
        print("FAIL at morph", i, exc)
        break

print("end pos", r.pos, "file", len(data))
