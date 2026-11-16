"""M02 · S8 阶段 E 的比对总表（把各次 m02_s8_compare.py 的产物并成一张索引）。

    python m02_s8_index.py <out.json> <reports/subai/M02>
"""
import hashlib
import json
import os
import sys

PAIRS = [
    ("A vs B（烘焙回放：集合全关）", "s8_ab_result.json", "作废：回放缓存"),
    ("A vs C（烘焙回放：effector 重力 0）", "s8_control_C.json", "作废：回放缓存"),
    ("A vs E（烘焙回放：scene 重力归零）", "s8_control_E.json", "作废：回放缓存"),
    ("A vs D（烘焙回放：全 kinematic）", "s8_control_D.json", "回放被破坏，仅作机制参照"),
    ("A vs F（烘焙回放：挪 1 cm）", "s8_control_F.json", "回放指纹：恰好 1.000 cm 全段恒定"),
    ("A vs A2（烘焙回放重复性）", "s8_control_A1A2.json", "回放重复性，无意义"),
    ("P0 vs P1（真解算重复性）", "s8_P0_P1_repeat.json", "重算可重复：0.0"),
    ("A vs P0（回放 vs 重算）", "s8_A_vs_P0.json", "交付烘焙 != 本项目重算"),
    ("P0 vs P2（真 A/B：集合全关）", "s8_ab_cachefree.json", "主结论"),
    ("P0 vs P5（真解算：只断地面接触）", "s8_P5_noground.json", "分离地面接触"),
    ("P0 vs P3（真解算：挪 1 cm 指纹反证）", "s8_P0_P3_fingerprint.json", "非刚性平移 = 真在算"),
    ("P0 vs P4（真解算：限位 ±1.5708 → ±0.7）", "s2_cachefree_limit.json", "S2 的真答案"),
    ("P0 vs P6（真解算：限位 ±1.5708 → ±0.001）", "s2_cachefree_limit_absurd.json", "限位是活的"),
    ("P0 vs P8（真解算：限位 ±1.5708 → ±0.5）", "s2_cachefree_limit_05.json", "0.5 会咬，但亚毫米"),
    ("P0 vs P10（真解算：只隔离 11 个占位刚体）", "s8_P10_placeholder_isolated.json", "跨骨架静态碰撞体 5.71 mm"),
]


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    out_path, rep = sys.argv[1], sys.argv[2]
    table = []
    for label, fname, note in PAIRS:
        p = os.path.join(rep, fname)
        rec = {"label": label, "file": fname, "note": note, "exists": os.path.exists(p)}
        if rec["exists"]:
            d = json.load(open(p, encoding="utf-8"))
            rec.update({"verdict": d.get("verdict"),
                        "D_hem_m": d.get("main", {}).get("D_hem_m"),
                        "D_all_m": d.get("main", {}).get("D_all_m"),
                        "first_frame_over_1mm_hem": d.get("main", {}).get("first_frame_over_1mm_hem"),
                        "distribution_hem_m": d.get("distribution_hem_m"),
                        "sha256": sha(p)})
        table.append(rec)

    s8 = os.path.join(os.path.dirname(rep), "..", "..", "out", "subai", "M02", "s8")
    frames = {}
    for name in ("A_FINAL", "B_FINAL", "C", "D", "E", "F", "A1", "A2", "P0", "P1", "P2", "P3", "P4", "P5", "P6", "P8", "P10"):
        d = os.path.normpath(os.path.join(rep, "..", "..", "..", "out", "subai", "M02", "s8", name))
        f = os.path.join(d, "frames.jsonl")
        if os.path.exists(f):
            m = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
            frames[name] = {"frames_sha256": sha(f),
                            "variant": m.get("variant"),
                            "baked_before": (m.get("point_cache_before") or {}).get("is_baked"),
                            "baked_after_free": (m.get("point_cache_after_free_bake") or {}).get("is_baked"),
                            "changed_bodies": m.get("changed_bodies"),
                            "limits_changed_count": m.get("limits_changed_count"),
                            "source_untouched": m.get("source_untouched")}

    out = {"stage": "E-s8", "comparisons": table, "samples": frames,
           "criterion": "预注册于 s8_hypothesis.md：18 根下摆骨 D_hem >= 1.0 mm 判 EFFECTIVE"}
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    for r in table:
        print("%-46s %-11s D_hem=%s D_all=%s"
              % (r["label"], r.get("verdict"), r.get("D_hem_m"), r.get("D_all_m")))


main()
