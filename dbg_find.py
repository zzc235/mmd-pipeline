"""在原始字节里找已知贴图名/材质名的 UTF-16LE 位置，反推真实段边界。"""
PATH = r"E:/blender模型/绯樱/星穹铁道—绯英.pmx"
data = open(PATH, "rb").read()
print("size", len(data))

for probe in ["衣.png", "颜.png", "髪.png", "2.bmp", "衣", "髪", "顏", "肌"]:
    b = probe.encode("utf-16-le")
    idx = data.find(b)
    print("%-8s -> %s" % (probe, idx), end="  ")
    if idx > 0:
        # 往前看 4 字节应该是长度
        import struct
        ln = struct.unpack_from("<i", data, idx - 4)[0]
        print("len_prefix=%d (probe_bytes=%d)" % (ln, len(b)))
    else:
        print()

print()
print("=== hex 3652320..3652420 ===")
chunk = data[3652320:3652420]
for i in range(0, len(chunk), 16):
    row = chunk[i:i + 16]
    print("%8d  %s  %s" % (3652320 + i,
                           " ".join("%02x" % x for x in row),
                           "".join(chr(x) if 32 <= x < 127 else "." for x in row)))
