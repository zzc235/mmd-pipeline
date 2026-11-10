"""dump 材质变形段，核对偏移长度。"""
import struct

PATH = r"E:/blender模型/绯樱/星穹铁道—绯英.pmx"
data = open(PATH, "rb").read()


def dump(base, n):
    print("=== %d ===" % base)
    for i in range(0, n, 16):
        row = data[base + i:base + i + 16]
        print("%8d  %s  %s" % (base + i,
                               " ".join("%02x" % x for x in row),
                               "".join(chr(x) if 32 <= x < 127 else "." for x in row)))


dump(4140430, 96)
print()
dump(4142080, 80)
print()

# 手工解析 morph 65 头
p = 4140439
for label in ("name", "name_en"):
    ln = struct.unpack_from("<i", data, p)[0]
    txt = data[p + 4:p + 4 + ln].decode("utf-16-le", "replace")
    print("%s len=%d %r  -> next %d" % (label, ln, txt, p + 4 + ln))
    p = p + 4 + ln
print("panel", data[p], "type", data[p + 1])
p += 2
n = struct.unpack_from("<i", data, p)[0]
print("offset_count", n, "offsets start", p + 4)
print("到 morph66 头还差", 4142110 - (p + 4), "字节")
for guess in (113, 112, 1 + 112):
    print("  若每条 %d 字节，n 应为 %.3f" % (guess, (4142110 - (p + 4)) / guess))
