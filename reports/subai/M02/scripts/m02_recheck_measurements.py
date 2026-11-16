"""独立复算：把另一席位记录里被 `normalize()` 丢掉的可选键按规范路径塞回 canonical。

    python m02_recheck_measurements.py <evidence.json> [<expected-digest-hex>] [--all]

`--all`：把 `measurements` / `commit` / `scope` 三个键都塞回去（④ 落地后的终值口径）；
不带：只塞 `measurements`（② 单件的金标口径）。

方法（与 D0 / 2号 相同，但由第三方独立实现）：
  normalize() → 手动插入可选键 → json.dumps(sort_keys=True, separators=(",",":"),
  ensure_ascii=False) → sha256。
"""
import hashlib
import json
import sys

sys.path.insert(0, r"E:\code\mmdpipe-ai\A1")
from coordination import evidence  # noqa: E402

OPTIONAL_KEYS = ("measurements", "commit", "scope")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    all_keys = "--all" in sys.argv
    path = args[0]
    expected = args[1] if len(args) > 1 else None
    raw = json.load(open(path, encoding="utf-8"))
    normalized = evidence.normalize(raw)
    dropped = sorted(set(raw) - set(normalized))
    keys = [k for k in OPTIONAL_KEYS if k in raw] if all_keys else ["measurements"]

    without = evidence.canonical_bytes(normalized)
    filled = dict(normalized)
    for key in keys:
        if key in raw:
            filled[key] = raw[key]
    data = evidence.canonical_bytes(filled)
    digest = hashlib.sha256(data).hexdigest()

    print("input        :", path)
    print("normalize() 丢掉的键:", dropped)
    print("塞回的键      :", [k for k in keys if k in raw])
    print("无可选键      : %d B  %s" % (len(without), hashlib.sha256(without).hexdigest()))
    print("有可选键      : %d B  %s" % (len(data), digest))
    if expected:
        ok = digest == expected.replace("evidence/1:", "")
        print("期望          : %s" % expected)
        print("一致          :", ok)
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
