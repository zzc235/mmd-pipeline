"""列出 3.30M..3.60M 区间内所有"像 TextBuf"的地方，看清段结构。"""
import struct

PATH = r"E:/blender模型/绯樱/星穹铁道—绯英.pmx"
data = open(PATH, "rb").read()

print("=== hex 3481560..3481800 ===")
base = 3481560
chunk = data[base:base + 240]
for i in range(0, len(chunk), 16):
    row = chunk[i:i + 16]
    print("%8d  %s  %s" % (base + i,
                           " ".join("%02x" % x for x in row),
                           "".join(chr(x) if 32 <= x < 127 else "." for x in row)))

print()
print("=== TextBuf 候选（len 2..80 偶数，内容可解码）===")
hits = []
for off in range(3300000, 3600000):
    n = struct.unpack_from("<i", data, off)[0]
    if n < 2 or n > 80 or n % 2:
        continue
    try:
        s = data[off + 4:off + 4 + n].decode("utf-16-le")
    except UnicodeDecodeError:
        continue
    if not s or not all((" " <= ch <= "~") or ("\u4e00" <= ch <= "\u9fff")
                        or ch in "\u3000\u30fb\u30a2" for ch in s):
        continue
    hits.append((off, n, s))

print("候选数", len(hits))
for off, n, s in hits[:60]:
    print("%8d  len=%-4d %r" % (off, n, s))
