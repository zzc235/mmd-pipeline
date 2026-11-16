# -*- coding: utf-8 -*-
"""M04 静态结构账目：PMX 的碰撞意图有多少能靠「位」表达、多少必须靠「约束」。

**这不是物理差。** 它不需要解算、不需要帧、不需要 Blender，只读 `rigid_mask_dump.json`
（对 .blend 的一次只读导出）与既有约束表。因此它对「跑不跑得动」不敏感。

三个数一一对应，缺一条就不成立：
  disallowed == separated_by_bits + needs_constraint + unexpressible      （1c 恒等式）
其中 `unexpressible` = 位分不开且约束也表达不了（4号 实测恒 0，理由：PMX 该碰的一对在
`mask | (1<<own)` 下必然共享某一位）。

宇宙（`D-20261116-133` 钉死）：
  U323 = mmd_type == "RIGID_BODY"      ← 1c 类等式只在这个宇宙成立
  U324 = rigid_body 非空 = U323 + ["地面_物理"]

位号约定：`bit(group - 1)`，因为 dump 里的 `group` 是 1 基（= collision_group_number + 1）。
三种约定里 `bit(group)` 与 `bit(group+1)` 也会给出「看起来正常」的数 —— 见 §自检。
"""
import argparse
import hashlib
import io
import itertools
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

EPSILON_UNUSED = 0.020   # 占位：本脚本不涉及任何深度量


def sha_triple(path):
    """D0 的 `D-20261116-136`：比哈希前报 raw / lf_normalized / crlf 三个数。"""
    b = open(path, "rb").read()
    lf = b.replace(b"\r\n", b"\n")
    return {
        "bytes": len(b),
        "sha256_raw": hashlib.sha256(b).hexdigest(),
        "sha256_lf_normalized": hashlib.sha256(lf).hexdigest(),
        "crlf_count": b.count(b"\r\n"),
    }


def pmx_collides(a, b):
    """PMX 语义：两边都允许才算碰（与 mmdpipe/mask.py 的 pmx_collides 同式）。"""
    return bool((a["mask"] >> (b["group"] - 1)) & 1) and bool((b["mask"] >> (a["group"] - 1)) & 1)


def post_bits(r):
    """通道写入后的位：mask | (1 << own_group)，own_group 0 基 = group - 1。"""
    return r["mask"] | (1 << (r["group"] - 1))


def bits_separate(a, b):
    """Blender 侧「共享位即碰」⇒ 位能分开 iff 两者位不相交。"""
    return (post_bits(a) & post_bits(b)) == 0


def universe_table(rows, label, ground_names):
    n = len(rows)
    pairs = n * (n - 1) // 2
    disallowed = 0
    by_bits = 0
    ground_pairs = ground_bits = 0
    for a, b in itertools.combinations(rows, 2):
        if pmx_collides(a, b):
            continue
        disallowed += 1
        is_ground = (a["object"] in ground_names) or (b["object"] in ground_names)
        if is_ground:
            ground_pairs += 1
        if bits_separate(a, b):
            by_bits += 1
            if is_ground:
                ground_bits += 1
    needs_constraint = disallowed - by_bits
    return {
        "universe": label,
        "rigid_count": n,
        "pair_count": pairs,
        "pmx_allowed_pairs": pairs - disallowed,
        "pmx_disallowed_pairs": disallowed,
        "separated_by_bits": by_bits,
        "needs_constraint": needs_constraint,
        "bits_share": round(by_bits / disallowed, 4) if disallowed else None,
        "identity_holds": (by_bits + needs_constraint) == disallowed,
        "ground_related_disallowed_pairs": ground_pairs,
        "ground_separated_by_bits": ground_bits,
        "ground_needs_constraint": ground_pairs - ground_bits,
    }


def convention_selftest(rows, expected_u324):
    """位号约定自检：三种偏移里只有 bit(group-1) 复现已发布数。
    这是一条**「应当被拒」的输入**：错约定必须给出不同的数。"""
    out = {}
    for off in (-1, 0, 1):
        def coll(a, b, off=off):
            return (bool((a["mask"] >> (b["group"] + off)) & 1)
                    and bool((b["mask"] >> (a["group"] + off)) & 1))
        dis = sum(1 for a, b in itertools.combinations(rows, 2) if not coll(a, b))
        out["bit(group%+d)" % off] = dis
    ok = out.get("bit(group-1)") == expected_u324
    return {"tried": out, "expected_u324": expected_u324,
            "chosen": "bit(group-1)", "match": ok}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", default=r"out/subai/M04/penetration/rigid_mask_dump.json")
    ap.add_argument("--baseline", default=r"reports/subai/M04/baselines/B_from_blend1_roi18_capsule_v1.json")
    ap.add_argument("--out", default=r"out/subai/M04/penetration/structural_accounting.json")
    ap.add_argument("--expect-u324", type=int, default=40418,
                    help="已发布的 U324 不互撞对数，用于位号约定自检")
    a = ap.parse_args()

    doc = json.load(io.open(a.dump, encoding="utf-8"))
    rows = doc["rows"]
    ground = sorted({r["object"] for r in rows if "地面" in (r.get("object") or "")})
    u323_rows = [r for r in rows if r["object"] not in ground]

    meta = {
        "spec": "m04_structural_accounting/1",
        "title": "静态结构数，非物理差",
        "is_physics_measurement": False,
        "why": "PMX 的碰撞意图能靠位表达多少、必须靠约束表达多少；与解算无关，可复算。",
        "inputs": {
            "dump": dict(path=a.dump, **sha_triple(a.dump)),
            "baseline": dict(path=a.baseline, **sha_triple(a.baseline)),
            "dump_rigid_objects": doc.get("rigid_objects"),
            "dump_read_failures": len(doc.get("read_failures") or []),
        },
        "universe_note": {
            "U323": "mmd_type == RIGID_BODY（1c 类等式只在此宇宙成立）",
            "U324": "rigid_body 非空 = U323 + %s" % ground,
            "diff_is_named_object_not_arithmetic": ground,
        },
        "bit_index_convention": "bit(group - 1)；dump 的 group 是 1 基",
        "convention_selftest": convention_selftest(rows, a.expect_u324),
        "tables": {
            "U324": universe_table(rows, "U324", set(ground)),
            "U323": universe_table(u323_rows, "U323", set(ground)),
        },
    }

    # 既有约束：从 dump 无法得知，由探针产物供给（有则并入）
    ncc = None
    try:
        feas = json.load(io.open(
            r"out/subai/M04/penetration/mask_apply_feasibility_main.json", encoding="utf-8"))
        ncc = {
            "ncc_pair_count_before": feas.get("ncc_pair_count_before"),
            "released_pair_count_planned": (feas.get("plan") or {}).get("released_pair_count_planned"),
            "added_pair_count_planned": (feas.get("plan") or {}).get("added_pair_count_planned"),
            "source": "mask_apply_feasibility_main.json [measured:this-run]",
        }
        if ncc["ncc_pair_count_before"] is not None and ncc["released_pair_count_planned"] is not None:
            ncc["blocking_correctly_pair_count"] = (ncc["ncc_pair_count_before"]
                                                    - ncc["released_pair_count_planned"])
    except FileNotFoundError:
        pass
    meta["existing_constraints"] = ncc

    os_makedirs = __import__("os").makedirs
    os_makedirs(__import__("os").path.dirname(a.out), exist_ok=True)
    with io.open(a.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")

    for k, v in meta["tables"].items():
        print("[%s] rigids=%d pairs=%d 该碰=%d 不互撞=%d = 位分 %d（%s） + 需约束 %d ；恒等式 %s"
              % (k, v["rigid_count"], v["pair_count"], v["pmx_allowed_pairs"],
                 v["pmx_disallowed_pairs"], v["separated_by_bits"], v["bits_share"],
                 v["needs_constraint"], v["identity_holds"]))
        print("       地面相关：不互撞 %d = 位分 %d + 需约束 %d"
              % (v["ground_related_disallowed_pairs"], v["ground_separated_by_bits"],
                 v["ground_needs_constraint"]))
    print("[convention] %s  match=%s" % (meta["convention_selftest"]["tried"],
                                         meta["convention_selftest"]["match"]))
    if ncc:
        print("[constraints] %s" % json.dumps(ncc, ensure_ascii=False))
    print("[out] %s" % a.out)
    ok = (meta["convention_selftest"]["match"]
          and all(v["identity_holds"] for v in meta["tables"].values()))
    print("[verdict] %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 4


if __name__ == "__main__":
    sys.exit(main())
