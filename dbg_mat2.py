"""扫描 morph66 真正起点，反推材质变形偏移块长度。"""
import struct

PATH = r"E:/blender模型/绯樱/星穹铁道—绯英.pmx"
data = open(PATH, "rb").read()
START = 4140451          # 照れ offsets 起点


def textbuf_ok(off, limit=64):
    if off + 4 > len(data):
        return None
    n = struct.unpack_from("<i", data, off)[0]
    if n < 0 or n > limit or n % 2:
        return None
    try:
        s = data[off + 4:off + 4 + n].decode("utf-16-le")
    except UnicodeDecodeError:
        return None
    return s


hits = []
for E in range(START + 1, 4146000):
    s = textbuf_ok(E)
    if s is None or not s:
        continue
    pos = E + 4 + len(s.encode("utf-16-le"))
    en = textbuf_ok(pos)
    if en is None:
        continue
    pos += 4 + len(en.encode("utf-16-le"))
    if pos + 6 > len(data):
        continue
    panel, mtype = data[pos], data[pos + 1]
    n = struct.unpack_from("<i", data, pos + 2)[0]
    if panel <= 9 and 0 <= mtype <= 10 and 0 <= n <= 50000:
        hits.append((E, s, panel, mtype, n, E - START))
        if len(hits) >= 8:
            break

for h in hits:
    print("morph66 @%d  %-14r panel=%d type=%d n=%d   bloc=%d 字节"
          % (h[0], h[1], h[2], h[3], h[4], h[5]))

if hits:
    bloc = hits[0][5]
    print("\n推算：若 1 条偏移，单条 %d 字节；若 %d 条，单条 %d"
          % (bloc, 1, bloc))
    for k in range(1, 20):
        if bloc % k == 0:
            print("   可被 %d 整除 -> 单条 %d 字节" % (k, bloc // k))
