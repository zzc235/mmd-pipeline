"""按 fc 反推 F，找近似命中以暴露系统性偏移。"""
import struct

PATH = r"E:/blender模型/绯樱/星穹铁道—绯英.pmx"
data = open(PATH, "rb").read()
TEX = 3481635
VERT_START = 901
NVERTS = 39242

for vs in (2, 4, 1):
    near = []
    for fc in range(1000, 600000):
        F = TEX - 4 - fc * 3 * vs
        if F <= VERT_START:
            break
        v = struct.unpack_from("<i", data, F)[0]
        if abs(v - fc) < 6:
            near.append((fc, F, v, v - fc))
    print("vs=%d  近似命中 %d 条" % (vs, len(near)))
    for t in near[:6]:
        print("   fc=%d F=%d read=%d delta=%d  顶点段字节=%d (%.3f B/vert)"
              % (t[0], t[1], t[2], t[3], t[1] - VERT_START, (t[1] - VERT_START) / NVERTS))
