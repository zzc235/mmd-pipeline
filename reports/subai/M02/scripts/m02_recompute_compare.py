"""把两份 `m02_recompute_verify.py` 的记录合成一条 `recomputed` 判据（纯 Python，无 bpy）。

为什么要有这一层：两件事必须分开说，合起来就会把 `T3` 写出来
--------------------------------------------------------------
1. **跨会话可重建**（主判据）：同一份冻结件、同一段顺序步进，跑在**两个独立 Blender 会话**里，
   逐帧 `pass_a_sequential` 的 pose sha 必须相同 ⇒ 「场景可确定性重建」这句话成立。
2. **顺序 vs 冷跳**（已知事实，不是失败）：同一次会话里 A（顺序步进）与 B（缓存释放后冷跳重读）
   不一致是**已知的**——解算依赖遍历方式（早上那条实测）。这一项**只记量级**，不参与判定；
   把它当判据会把「引擎特性」判成「场景不确定」。

用法：
    python reports/subai/M02/scripts/m02_recompute_compare.py --run1 a.json --run2 b.json --out verdict.json
"""

import argparse
import json
import os
import sys


def load(path):
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def main(argv=None):
    ap = argparse.ArgumentParser(description="recomputed 判据合成")
    ap.add_argument("--run1", required=True)
    ap.add_argument("--run2", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    a, b = load(args.run1), load(args.run2)
    rec = {
        "stage": "recompute-compare-v1",
        "inputs": {
            "run1": {"path": os.path.abspath(args.run1), "verdict": a.get("verdict"),
                     "blend_sha256": (a.get("blend") or {}).get("sha256")},
            "run2": {"path": os.path.abspath(args.run2), "verdict": b.get("verdict"),
                     "blend_sha256": (b.get("blend") or {}).get("sha256")},
        },
    }
    problems = []
    if (a.get("blend") or {}).get("sha256") != (b.get("blend") or {}).get("sha256"):
        problems.append("两遍跑的不是同一份件（blend sha 不同）")
    if a.get("targets") != b.get("targets"):
        problems.append("目标帧不同：%r vs %r" % (a.get("targets"), b.get("targets")))
    if a.get("bodies") != b.get("bodies"):
        problems.append("刚体数不同：%r vs %r" % (a.get("bodies"), b.get("bodies")))
    if a.get("blender") != b.get("blender"):
        problems.append("Blender 版本不同：%r vs %r" % (a.get("blender"), b.get("blender")))

    sa = a.get("pass_a_sequential") or {}
    sb = b.get("pass_a_sequential") or {}
    frames = sorted(set(sa) | set(sb), key=lambda x: int(x))
    per_frame = {}
    diff_frames = []
    for frame in frames:
        same = sa.get(frame) is not None and sa.get(frame) == sb.get(frame)
        per_frame[frame] = {"run1": sa.get(frame), "run2": sb.get(frame), "same": same}
        if not same:
            diff_frames.append(frame)
    rec["cross_session"] = {
        "criterion": "pass_a_sequential 的 pose sha 在两次独立会话里逐帧相同",
        "frames": frames, "per_frame": per_frame,
        "diff_frames": diff_frames,
        "consistent": not diff_frames and not problems,
    }
    rec["order_dependence"] = {
        "note": ("同一次会话里 A（顺序步进）与 B（缓存释放后冷跳重读）的差 —— **已知**："
                 "解算依赖遍历方式。只记量级，不参与判定。"),
        "run1": {"over_tol_total": (a.get("compare") or {}).get("over_tol_total"),
                 "max_delta": (a.get("compare") or {}).get("max_delta")},
        "run2": {"over_tol_total": (b.get("compare") or {}).get("over_tol_total"),
                 "max_delta": (b.get("compare") or {}).get("max_delta")},
    }
    rec["problems"] = problems
    rec["verdict"] = "RECOMPUTE_CONSISTENT" if not diff_frames and not problems \
        else "RECOMPUTE_INCONSISTENT"
    rec["scope"] = ("通过 = 场景可在任意新会话里确定性重建到同一姿态（`T2` 的立足点）。"
                    "不证明交付件自带可回放缓存（`D-218`/`D-219` 已定：缓存没出门），"
                    "两句不许合并。")

    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("RECOMPUTED verdict=%s frames=%s diff=%s problems=%s order_dep_max_delta=%r"
          % (rec["verdict"], ",".join(frames), diff_frames, problems,
             (rec["order_dependence"]["run1"] or {}).get("max_delta")))
    return 0 if rec["verdict"] == "RECOMPUTE_CONSISTENT" else 5


if __name__ == "__main__":
    sys.exit(main())
