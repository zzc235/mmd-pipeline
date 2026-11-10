"""尾段追踪：morph / display / rigid 三段游标。"""
import sys

sys.path.insert(0, r"E:/dsh pr/woker2")
from mmdpipe import pmx as P

PATH = r"E:/blender模型/绯樱/星穹铁道—绯英.pmx"
data = open(PATH, "rb").read()
enc = "utf-16-le"
add_uv, vs, ts, ms, bs, mos, rs = 2, 2, 1, 1, 2, 1, 2

r = P._Reader(data)
r.pos = 901
vc = 39242
for _ in range(vc):
    r.f32n(3); r.f32n(3); r.f32n(2)
    if add_uv:
        r.f32n(add_uv * 4)
    wt = r.u8()
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
    r.f32()

field = r.i32()
_, tri = P._skip_faces(r, data, r.pos, field, vs)
print("faces field=%d triangles=%d pos=%d" % (field, tri, r.pos))

tc = r.i32()
for _ in range(tc):
    r.text(enc)
print("textures=%d pos=%d" % (tc, r.pos))

mc = r.i32()
for _ in range(mc):
    r.text(enc); r.text(enc)
    r.f32n(4); r.f32n(3); r.f32(); r.f32n(3)
    r.u8(); r.f32n(4); r.f32()
    r.index(ts); r.index(ts); r.u8()
    tf = r.u8()
    if tf == 1:
        r.index(ts)
    else:
        r.u8()
    r.text(enc)
    r.i32()
print("materials=%d pos=%d" % (mc, r.pos))

bc = r.i32()
names = []
for i in range(bc):
    nm = r.text(enc)
    names.append(nm)
    r.text(enc)
    r.f32n(3)
    r.index(bs)
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
print("bones=%d pos=%d  last=%s" % (bc, r.pos, names[-3:]))

morph_count = r.i32()
print("morph_count=%d pos=%d" % (morph_count, r.pos))

disp_count = r.i32()
print("disp_count=%d pos=%d" % (disp_count, r.pos))
for i in range(disp_count):
    dname = r.text(enc)
    den = r.text(enc)
    sp = r.u8()
    n = r.i32()
    for _ in range(n):
        r.index(bs)
        r.u8()
    print("  disp[%d] %-10s / %-14s special=%d frames=%d pos=%d"
          % (i, dname[:10], den[:14], sp, n, r.pos))

rigid_count = r.i32()
print("rigid_count=%d pos=%d" % (rigid_count, r.pos))
