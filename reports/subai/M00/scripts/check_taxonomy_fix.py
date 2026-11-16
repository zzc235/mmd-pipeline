# -*- coding: utf-8 -*-
"""只读复算：补词表要改哪几处（在 main 的副本上跑，`coordination/` 一个字节都不写）。

    python out/subai/M00/scripts/check_taxonomy_fix.py

三种改法各跑一次 `taxonomy.check_history(path=副本, doc=改过的词表)`：
① 不动（对照）；② 只补 5 个 `allowed_reason_code`；③ 再给 `allowed_decision` 加 `RULING`。
"""
import io
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
sys.path.insert(0, ROOT)

from coordination import taxonomy as tax  # noqa: E402

WANT_REASONS = ["DISPATCH_DOUBLE_ASSIGNED_SPLIT_BY_FILE", "DIGEST_CHANGES_AT_BAKE",
                "GATE_INPUT_NOT_RETRIEVABLE", "INSTANCE_SHA_UNRECOVERABLE",
                "CODE_READY_NOT_END_TO_END"]


def _from_git(ref: str, path: str) -> bytes:
    proc = subprocess.run(["git", "-C", ROOT, "show", "%s:%s" % (ref, path)],
                          capture_output=True)
    if proc.returncode != 0:
        raise SystemExit("git show 失败：%s %s" % (ref, path))
    return proc.stdout


def main() -> int:
    ref = sys.argv[1] if len(sys.argv) > 1 else "main"
    base = json.loads(_from_git(ref, "coordination/decision_taxonomy.json").decode("utf-8"))
    decisions = _from_git(ref, "coordination/decisions.jsonl")
    tmp = tempfile.mkdtemp(prefix="a4_tax_")
    dec_path = os.path.join(tmp, "decisions.jsonl")
    with open(dec_path, "wb") as fh:
        fh.write(decisions)

    print("ref=%s  allowed_decision=%d  allowed_reason_code=%d  legacy_map=%d"
          % (ref, len(base["allowed_decision"]), len(base["allowed_reason_code"]),
             len(base["legacy_map"])))

    def run(label, mutate):
        doc = json.loads(json.dumps(base))
        mutate(doc)
        report = tax.check_history(path=dec_path, doc=doc)
        missing = report.get("missing_mapping") or []
        print("[%s] missing_mapping=%d %s" % (label, len(missing), missing))
        return missing

    control = run("对照（不动）", lambda d: None)
    only_reason = run("只补 5 个 reason_code", lambda d: d["allowed_reason_code"].extend(WANT_REASONS))

    def both(d):
        d["allowed_reason_code"].extend(WANT_REASONS)
        if "RULING" not in d["allowed_decision"]:
            d["allowed_decision"].append("RULING")
    fixed = run("补 5 个 reason_code + allowed_decision += RULING", both)

    # 这条是给「以后有人想用 legacy_map 走后门」的实证：塞进 legacy_map 也能绿，但那是另一条路
    def via_legacy(d):
        for did in control:
            d["legacy_map"][did] = "走后门（只作反例，不是建议）"
    legacy_way = run("（反例）把 5 条塞进 legacy_map", via_legacy)

    print()
    print("结论：")
    print("  只补 reason_code 仍红 %d 条 ⇒ %s" % (
        len(only_reason), "补一半" if only_reason else "一次到位"))
    print("  两处一起改 ⇒ %s" % ("全绿" if not fixed else "还红 %s" % fixed))
    print("  legacy_map 那条路也能绿（%d 条），但它是给冻结点之前的老记录用的 —— 不作建议"
          % len(legacy_way))
    return 0 if (control and only_reason and not fixed) else 1


if __name__ == "__main__":
    sys.exit(main())
