"""把 120 字节材质变形偏移按各种对齐解成 float，找出干净的那一种。"""
import struct

PATH = r"E:/blender模型/绯樱/星穹铁道—绯英.pmx"
data = open(PATH, "rb").read()
START = 4140451
BLOC = 120
raw = data[START:START + BLOC]
print("raw bytes:", " ".join("%02x" % b for b in raw))
print()

CLEAN = (0.0, 1.0, 0.5, 0.25, 0.75, -1.0)


def clean(v):
    return any(abs(v - c) < 1e-6 for c in CLEAN)


for align in range(0, 8):
    vals = []
    for k in range((BLOC - align) // 4):
        v = struct.unpack_from("<f", data, START + align + 4 * k)[0]
        vals.append(v)
    score = sum(1 for v in vals if clean(v))
    head = " ".join(("%.3g" % v) for v in vals[:14])
    print("align=%d  float数=%2d  干净值=%2d  %s" % (align, len(vals), score, head))

print()
print("=== 按 int32 / int8 看头部 12 字节 ===")
for k in range(3):
    v = struct.unpack_from("<i", data, START + 4 * k)[0]
    print("  i32[%d] = %d" % (k, v))
print("  bytes[0:12]", " ".join("%02x" % b for b in raw[:12]))
