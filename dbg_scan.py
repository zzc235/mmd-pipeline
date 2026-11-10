"""暴力定位：在可疑字节区间找"纹理/材质/骨骼数都合理"的真实段起点。"""
import sys

sys.path.insert(0, r"E:/dsh pr/woker2")
from mmdpipe.pmx import _Reader, PMXError

PATH = r"E:/blender模型/绯樱/星穹铁道—绯英.pmx"
data = open(PATH, "rb").read()
enc = "utf-16-le"
vs, ts, ms, bs, mos, rs = 2, 1, 1, 2, 1, 2

print("size", len(data))


def sane_text(r, limit=400):
    n = r.i32()
    if n < 0 or n > limit or n % 2:
        return None
    return r.take(n).decode(enc, "replace")


hits = []
for off in range(3640000, 3665000):
    r = _Reader(data)
    r.pos = off
    try:
        tc = r.i32()
        if not (0 < tc <= 300):
            continue
        tex = []
        for _ in range(tc):
            t = sane_text(r)
            if t is None:
                raise PMXError("tex")
            tex.append(t)
        mc = r.i32()
        if not (0 < mc <= 500):
            continue
        names = []
        for _ in range(mc):
            n1 = sane_text(r)
            n2 = sane_text(r)
            if n1 is None or n2 is None:
                raise PMXError("mat")
            r.f32n(4); r.f32n(3); r.f32(); r.f32n(3)
            r.u8(); r.f32n(4); r.f32()
            r.index(ts); r.index(ts); r.u8()
            tf = r.u8()
            if tf == 1:
                r.index(ts)
            else:
                r.u8()
            memo = sane_text(r, 2000)
            if memo is None:
                raise PMXError("memo")
            r.i32()
            names.append(n1)
        bc = r.i32()
        if not (0 < bc <= 3000):
            continue
        b0 = sane_text(r)
        if not b0:
            continue
        hits.append((off, tc, mc, bc, tex[:3], names[:3], b0))
    except (PMXError, Exception):
        continue

print("hits", len(hits))
for h in hits[:10]:
    print(h)
