"""定位 PMX 解析偏移：逐段打印字节游标。"""
import sys

sys.path.insert(0, r"E:/dsh pr/woker2")
from mmdpipe.pmx import _Reader

PATH = r"E:/blender模型/绯樱/星穹铁道—绯英.pmx"
data = open(PATH, "rb").read()
print("size", len(data))
r = _Reader(data)
print("magic", r.take(4))
print("version", r.f32())
gc = r.u8()
g = list(r.take(gc))
print("globals", g)
enc = "utf-16-le" if g[0] == 0 else "utf-8"
add_uv, vs, ts, ms, bs, mos, rs = g[1], g[2], g[3], g[4], g[5], g[6], g[7]
print("enc", enc, "add_uv", add_uv, "idx", vs, ts, ms, bs, mos, rs)
print("name", r.text(enc), "| en", r.text(enc))
print("comment len", len(r.text(enc)), len(r.text(enc)), "pos", r.pos)

vc = r.i32()
print("verts", vc, "pos", r.pos)
wt_hist = {}
for i in range(vc):
    r.f32n(3); r.f32n(3); r.f32n(2)
    if add_uv:
        r.f32n(add_uv * 4)
    wt = r.u8()
    wt_hist[wt] = wt_hist.get(wt, 0) + 1
    if wt == 0:
        r.index(vs)
    elif wt == 1:
        r.index(vs); r.index(vs); r.f32()
    elif wt == 2:
        for _ in range(4):
            r.index(vs)
        r.f32n(4)
    elif wt == 3:
        r.index(vs); r.index(vs); r.f32()
        r.f32n(3); r.f32n(3); r.f32n(3)
    elif wt == 4:
        for _ in range(4):
            r.index(vs)
        r.f32n(4)
    else:
        print("BAD WEIGHT", wt, "at vert", i, "pos", r.pos)
        break
    r.f32()
print("vert done pos", r.pos, "wt_hist", wt_hist)

fc = r.i32()
print("faces", fc, "pos", r.pos)
r.take(fc * 3 * ts)
print("face done pos", r.pos)

tc = r.i32()
print("textures", tc, "pos", r.pos)
for i in range(tc):
    r.text(enc)
print("tex done pos", r.pos)

mc = r.i32()
print("materials", mc, "pos", r.pos)
for i in range(mc):
    r.text(enc); r.text(enc)
    r.f32n(4); r.f32n(3); r.f32(); r.f32n(3)
    r.u8()
    r.f32n(4); r.f32()
    r.index(ts); r.index(ts)
    r.u8()
    tf = r.u8()
    if tf == 1:
        r.index(ts)
    else:
        r.u8()
    r.text(enc)
    fcnt = r.i32()
    if i < 3 or i == mc - 1:
        print("  mat", i, "toon_flag", tf, "faces", fcnt, "pos", r.pos)
print("mat done pos", r.pos)

bc = r.i32()
print("bones", bc, "pos", r.pos)
for i in range(bc):
    start = r.pos
    name = r.text(enc)
    try:
        r.text(enc)
        r.f32n(3)
        parent = r.index(bs)
        r.i32()
        flag = r.u16()
        if flag & 0x0001:
            r.index(bs)
        else:
            r.f32n(3)
        if flag & (0x0100 | 0x0200):
            r.index(bs); r.f32()
        if flag & 0x0400:
            r.f32n(3)
        if flag & 0x0800:
            r.f32n(3); r.f32n(3)
        if flag & 0x2000:
            r.i32()
        if flag & 0x0020:
            r.index(bs); r.i32(); r.f32()
            n = r.i32()
            for _ in range(n):
                r.index(bs)
                if r.u8() == 1:
                    r.f32n(3); r.f32n(3)
    except Exception as exc:
        print("BONE FAIL at", i, name[:20], "flag?", "pos", start, exc)
        raise
print("bone done pos", r.pos)
