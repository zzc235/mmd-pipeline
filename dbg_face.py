"""用硬约束反推 face_count 字段位置：
   i32(F) * 3 * vs == TEX_COUNT_POS - (F + 4)
"""
import struct

PATH = r"E:/blender模型/绯樱/星穹铁道—绯英.pmx"
data = open(PATH, "rb").read()
TEX = 3481635          # 纹理数组计数所在位置（由 颜.png TextBuf 前推得到）
VERT_START = 901
NVERTS = 39242

print("size", len(data), "tex_count_pos", TEX)
print("i32@TEX =", struct.unpack_from("<i", data, TEX)[0])

found = []
for vs in (2, 4, 1):
    for F in range(VERT_START, TEX):
        span = TEX - (F + 4)
        if span <= 0 or span % (3 * vs):
            continue
        fc = span // (3 * vs)
        if struct.unpack_from("<i", data, F)[0] == fc and 1000 < fc < 800000:
            found.append((vs, F, fc, F - VERT_START))

print("found", found[:8])
for vs, F, fc, vbytes in found[:3]:
    print("  vs=%d  face_count@%d = %d   顶点段字节 %d = %.3f B/vert"
          % (vs, F, fc, vbytes, vbytes / NVERTS))
    # 抽查前 20 个索引是否都 < NVERTS
    ok = True
    for k in range(60):
        idx = struct.unpack_from("<H" if vs == 2 else "<I", data, F + 4 + k * vs)[0]
        if idx >= NVERTS:
            ok = False
            break
    print("   前60个索引均 < 顶点数：", ok)
