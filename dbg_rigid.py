"""找刚体段起点：扫"数字_名字"格式的 TextBuf。"""
import re
import struct

PATH = r"E:/blender模型/绯樱/星穹铁道—绯英.pmx"
data = open(PATH, "rb").read()
PAT = re.compile(r"^\d{2,3}_")

hits = []
for off in range(4150000, len(data) - 4):
    n = struct.unpack_from("<i", data, off)[0]
    if n < 6 or n > 64 or n % 2:
        continue
    try:
        s = data[off + 4:off + 4 + n].decode("utf-16-le")
    except UnicodeDecodeError:
        continue
    if PAT.match(s):
        hits.append((off, s))

print("命中 %d 条，前 12 条：" % len(hits))
for off, s in hits[:12]:
    print("  %8d  %r" % (off, s))

if hits:
    first = hits[0][0]
    print()
    print("首个刚体名 TextBuf 在 %d，rigid_count 应在 %d" % (first, first - 4))
    print("  i32@%d = %d" % (first - 4, struct.unpack_from("<i", data, first - 4)[0]))
    print()
    print("=== 往前 96 字节 ===")
    base = first - 96
    for i in range(0, 96, 16):
        row = data[base + i:base + i + 16]
        print("%8d  %s  %s" % (base + i,
                               " ".join("%02x" % x for x in row),
                               "".join(chr(x) if 32 <= x < 127 else "." for x in row)))
