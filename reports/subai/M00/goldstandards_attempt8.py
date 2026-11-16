# -*- coding: utf-8 -*-
"""M00 attempt 8 · 六道验收输入的实测面板（随本笔 artifacts 入库）。

口径：全部用**规范实现** `coordination.evidence` 算，不自己拼 json.dumps；
输入是盘上 **2号 的真实 M04 记录**逐层剥键，不是构造的样本。

能独立复算的在这里算；算不出来的（M02 `b837f933…` 需要 1号 生成器那份 dict）
如实打印"未验"，不假装。
"""
import json
import sys

sys.path.insert(0, r"E:\code\mmdpipe-ai\A4")
from coordination import evidence as e

M04 = r"E:\dsh pr\woker2\reports\subai\M04\evidence_m04_attempt11.json"
M02_CANDIDATES = [r"E:\dsh pr\woker2\reports\subai\M02\evidence_m02_attempt11.json"]


def show(tag, obj, expect_hex=None, expect_bytes=None):
    try:
        normal = e.normalize(obj)
        blob = e.canonical_bytes(normal)
        hexd = e.digest(obj).split(":")[1]
    except e.EvidenceError as exc:
        print("%-44s REJECTED (%s): %s" % (tag, exc.reason_code, exc))
        return False
    ok = True
    if expect_hex:
        ok = ok and hexd.startswith(expect_hex)
    if expect_bytes:
        ok = ok and len(blob) == expect_bytes
    dropped = sorted(set(obj) - set(normal))
    print("%-44s %s…  %5d B  dropped=%-6s %s"
          % (tag, hexd[:16], len(blob), dropped or "-", "OK" if ok else "MISMATCH"))
    return ok


base = json.load(open(M04, encoding="utf-8"))
print("== 逐层剥键（盘上 2号 的真实记录）==")
ok1 = show("M04 含三键（2号 终值）", base, "0be68a45", 5291)
no_scope = {k: v for k, v in base.items() if k != "scope"}
ok2 = show("M04 + measurements + commit（无 scope）", no_scope, "37a40240", 4827)
only_meas = {k: v for k, v in no_scope.items() if k != "commit"}
ok3 = show("M04 + 仅 measurements", only_meas, "22356081", 4808)
none = {k: v for k, v in only_meas.items() if k != "measurements"}
ok4 = show("M04 无三键（旧基数）", none, "3c4489f6", 3791)

print("\n== scope 空串 vs 缺席：canonical 必须相同 ==")
a = dict(no_scope)
b = dict(no_scope)
b["scope"] = ""
same = e.canonical_bytes(e.normalize(a)) == e.canonical_bytes(e.normalize(b))
print("A 缺席 : %s… %d B" % (e.digest(a).split(":")[1][:16], len(e.canonical_bytes(e.normalize(a)))))
print("B 空串 : %s… %d B" % (e.digest(b).split(":")[1][:16], len(e.canonical_bytes(e.normalize(b)))))
print("A == B : %s   'scope' in normalize(B) : %s"
      % (same, "scope" in e.normalize(b)))

print("\n== 应当被拒的输入（不给它应当被拒的输入，等于没验）==")
CASES = [
    ("commit 空串（不按缺席处理）", "commit", ""),
    ("commit 大写 hex", "commit", "F3FD0E1"),
    ("commit 前置空格（不 strip）", "commit", " f3fd0e1"),
    ("commit 太短（6 位）", "commit", "f3fd0e"),
    ("commit 非字符串", "commit", 1234567),
    ("scope 是列表", "scope", ["a.py"]),
]
rejects_ok = True
for tag, key, value in CASES:
    payload = json.loads(json.dumps(base))
    payload[key] = value
    try:
        e.digest(payload)
        print("%-44s NOT REJECTED  <-- 缺陷" % tag)
        rejects_ok = False
    except e.EvidenceError as exc:
        print("%-44s %s" % (tag, exc.reason_code))

print("\n== M02 记录（1号 的 b837f933… / 22465 B）==")
seen = False
for path in M02_CANDIDATES:
    try:
        obj = json.load(open(path, encoding="utf-8"))
    except OSError:
        continue
    seen = True
    show(path.rsplit("\\", 1)[-1], obj, "b837f933", 22465)
if not seen:
    print("未验：盘上还没有这份记录——它需要 1号 生成器的那份 dict，只能自证。")

all_ok = all([ok1, ok2, ok3, ok4, same, rejects_ok])
print("\n总判定: %s" % ("PASS" if all_ok else "FAIL"))
raise SystemExit(0 if all_ok else 1)
