"""表示枠条目索引宽度：试四种策略，以 rigid_count==270 定案。"""
import sys

sys.path.insert(0, r"E:/dsh pr/woker2")
from mmdpipe import pmx as P

PATH = r"E:/blender模型/绯樱/星穹铁道—绯英.pmx"
data = open(PATH, "rb").read()
enc = "utf-16-le"
vs, ts, ms, bs, mos, rs = 2, 1, 1, 2, 1, 2
MORPH_START = 3505609

probe = P._Reader(data)
probe.pos = MORPH_START
P._parse_morphs(probe, enc, vs, bs, mos, rs, ms, 1)
dc = probe.i32()
DISP_START = probe.pos
print("disp_count", dc, "start", DISP_START)

POLICIES = {
    "总是骨骼宽度": lambda sp: bs,
    "总是表情宽度": lambda sp: mos,
    "特殊枠→表情": lambda sp: (mos if (sp & 1) else bs),
    "特殊枠→骨骼": lambda sp: (bs if (sp & 1) else mos),
}

for label, fn in POLICIES.items():
    r = P._Reader(data)
    r.pos = DISP_START
    try:
        for i in range(dc):
            nm = r.text(enc)
            r.text(enc)
            sp = r.u8()
            n = r.i32()
            w = fn(sp)
            for _ in range(n):
                r.index(w)
                r.u8()
        rc = r.i32()
        print("%-12s -> 15 框解析完 pos=%d  rigid_count=%d" % (label, r.pos, rc))
    except P.PMXError as exc:
        print("%-12s -> 失败 %s" % (label, exc))
