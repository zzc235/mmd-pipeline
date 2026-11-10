"""表示枠 + 刚体段追踪。"""
import sys

sys.path.insert(0, r"E:/dsh pr/woker2")
from mmdpipe import pmx as P

PATH = r"E:/blender模型/绯樱/星穹铁道—绯英.pmx"
data = open(PATH, "rb").read()
enc = "utf-16-le"
vs, ts, ms, bs, mos, rs = 2, 1, 1, 2, 1, 2
MORPH_START = 3505609

for extra in (0, 1, 2):
    probe = P._Reader(data)
    probe.pos = MORPH_START
    try:
        morphs = P._parse_morphs(probe, enc, vs, bs, mos, rs, ms, extra)
        dc = probe.i32()
        print("extra=%d  morphs=%d  end=%d  disp_count=%d" % (extra, len(morphs), probe.pos - 4, dc))
        if 0 <= dc <= 200:
            r = probe
            for i in range(dc):
                nm = r.text(enc)
                en = r.text(enc)
                sp = r.u8()
                n = r.i32()
                print("  disp[%d] %-10s %-12s special=%d n=%d pos=%d" % (i, nm[:10], en[:12], sp, n, r.pos))
                for _ in range(n):
                    r.index(bs)
                    r.u8()
                print("       after entries pos=%d" % r.pos)
            rc = r.i32()
            print("  rigid_count=%d pos=%d" % (rc, r.pos))
            break
    except P.PMXError as exc:
        print("extra=%d 失败 %s" % (extra, exc))
