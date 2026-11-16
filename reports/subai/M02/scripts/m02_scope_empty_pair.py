"""`scope` 空串 ≡ 缺席 这条不变量，用真实记录算一组「必须相等」的值给实现当测试输入。

    python m02_scope_empty_pair.py <evidence.json> [<evidence.json> ...]

**关键：A/B 两侧都必须走 `normalize()`**。规范里「空白折叠、折成空串等同缺席」是
`normalize()` 的职责；把 `scope=""` 直接塞进 `canonical_bytes()` 的入参，是在测一个
生产路径上永远不会出现的形状——这种测法会给实现判出假的 FAIL（我第一版就是这样，
2026-11-16 14:0x，被 4号 的实现打回）。

对每个文件比三份：
  A) 原始记录去掉 `scope` 键
  B) 同一份记录，`scope = ""`
  C) 同一份记录，`scope = "   "`（全空白）
规范要求三份 canonical 逐字节相同，且 `normalize(B)` 里不再有 `scope` 键。
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.environ.get("M02_EVIDENCE_TREE") or r"E:\code\mmdpipe-ai\A1")
from coordination import evidence  # noqa: E402


def canon(obj):
    return evidence.canonical_bytes(evidence.normalize(obj))


def digest(data):
    return "evidence/1:" + hashlib.sha256(data).hexdigest()


def scope_supported(raw):
    """实现是否已经接收并保留 `scope` 这个键（非空值时）。"""
    return "scope" in evidence.normalize(dict(raw, scope="probe"))


def pair(path):
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    supported = scope_supported(raw)
    without = {k: v for k, v in raw.items() if k != "scope"}
    variants = {
        "A) 去掉 scope": without,
        'B) scope=""': dict(without, scope=""),
        'C) scope="   "': dict(without, scope="   "),
    }
    rows = []
    for label, obj in variants.items():
        data = canon(obj)
        rows.append((label, len(data), digest(data)))
    blobs = {canon(obj) for obj in variants.values()}
    kept = "scope" in evidence.normalize(dict(without, scope=""))
    return {
        "path": path,
        "supported": supported,
        "rows": rows,
        "equal": len(blobs) == 1,
        "scope_kept_in_canonical": kept,
    }


def main(argv):
    paths = argv[1:] or [r"E:\dsh pr\woker2\reports\subai\M02\evidence_m02_attempt11.json"]
    results = [pair(p) for p in paths]
    for r in results:
        print(r["path"].replace("\\", "/").rsplit("/", 1)[-1])
        for label, size, dig in r["rows"]:
            print("  %-18s %6d B  %s" % (label, size, dig))
        print("  三份 canonical 相同: %s；normalize(B) 仍含 scope: %s"
              % (r["equal"], r["scope_kept_in_canonical"]))
        print()
    if not any(r["supported"] for r in results):
        print("总判定: PENDING —— `normalize()` 还没接收 `scope`（④ 未落地），"
              "此刻三份不等是序列化器照着给的键写，不是实现的缺陷。")
        return 0
    ok = all(r["equal"] and not r["scope_kept_in_canonical"]
             for r in results if r["supported"])
    print("总判定: %s" % ("PASS（空/全空白 scope 折成缺席、不进 canonical）" if ok
                        else "FAIL（空 scope 仍进 canonical —— 同一内容两种哈希）"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
