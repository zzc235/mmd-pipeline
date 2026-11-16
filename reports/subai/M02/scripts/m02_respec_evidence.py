"""把已有的证据 JSON 转成**规范实现可验**的形态（`coordination.evidence.digest()`）。

    python m02_respec_evidence.py <in.json> <out.json> [<attempt>]

做三件事，**不改任何实测内容**：
  1. `interface`（我原先放的是 dict）→ 压成字符串（`json.dumps(..., sort_keys=True)`），
     这是 `coordination/evidence.py:129` 的要求：「interface 必须是字符串或 null」；
  2. 把 `normalize()` 会丢掉的未知键（`attempt_label` / `supersedes`）折进 `known_risks`，不静默消失；
  3. 用规范实现算 digest，并把 `canonical_bytes(normalize(obj))` 原样写盘 —— 文件 sha256 == digest。

`attempt` 默认沿用原值。
"""
import hashlib
import json
import sys

sys.path.insert(0, r"E:\code\mmdpipe-ai\A1")
from coordination import evidence  # noqa: E402


def main():
    in_path, out_path = sys.argv[1], sys.argv[2]
    raw = json.load(open(in_path, encoding="utf-8"))
    obj = dict(raw)

    if len(sys.argv) > 3:
        obj["attempt"] = int(sys.argv[3])

    interface = obj.get("interface")
    if isinstance(interface, dict):
        obj["interface"] = json.dumps(interface, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":"))

    extras = []
    label = obj.pop("attempt_label", None)
    supersedes = obj.pop("supersedes", None)
    if label:
        extras.append("attempt_label（规范化会丢掉，折在此处）：%s" % label)
    if supersedes:
        extras.append("supersedes（规范化会丢掉，折在此处）：%s" % supersedes)
    if extras:
        obj["known_risks"] = list(obj.get("known_risks") or []) + extras

    normalized = evidence.normalize(obj)          # 不合规会在这里抛
    data = evidence.canonical_bytes(normalized)
    digest_hex = hashlib.sha256(data).hexdigest()
    with open(out_path, "wb") as fh:
        fh.write(data)

    checked = evidence.digest(json.loads(data))
    print("in  %s" % in_path)
    print("out %s bytes=%d" % (out_path, len(data)))
    print("digest  evidence/1:%s" % digest_hex)
    print("re-derive from written file: %s" % checked)
    print("file sha256: %s" % hashlib.sha256(open(out_path, "rb").read()).hexdigest())
    print("match:", checked == "evidence/1:" + digest_hex
          == "evidence/1:" + hashlib.sha256(open(out_path, "rb").read()).hexdigest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
