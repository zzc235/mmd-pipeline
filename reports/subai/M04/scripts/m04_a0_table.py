# -*- coding: utf-8 -*-
"""M04 A0 正控 v2 的读数整理（只读产物，不开 Blender，不碰锁）。

三对臂（全部来自 `out/subai/M04/penetration/*.meta.json`）：
  sens   : R_free（位不动、清缓存、顺序重解）   vs A0_free（位全清、清缓存、顺序重解）
  repro  : A240（缓存回放，is_baked=true）      vs R_free（重解）
  determ : R_free                               vs R_free2（再解一遍，独立会话）

为什么要这支：旧的 `a0_free_perframe_compare.json` 只存了 `max_abs_delta_m`，
中位数只印在 stdout、没落盘；而「中位 10.878 mm」这句话正在被写进预注册。
本支把**分布**（中位/均值/分位）与**读数前提**（`is_baked`、`eval_policy`、
meta 文件三数哈希）一起落成 JSON，并与既有判词文件逐项对账。

退出码：0 全对；1 有对不上的项（selftest 或 cross-check）；2 算不出（产物缺/读不出）。
"""
import hashlib
import io
import json
import os
import statistics
import sys

sys.stdout.reconfigure(encoding="utf-8")

PEN = os.path.join("out", "subai", "M04", "penetration")
OUT_JSON = os.path.join("reports", "subai", "M04", "a0_v2_table.json")
SPEC = "m04_a0_table/1"

# 产物在**主工作树**的 out/（不随 git），报告落**自己 worktree**的 reports/。
# 所以两个路径都可显式给：`--pen <dir> --out <file>`，默认相对当前目录。
for _i, _a in enumerate(sys.argv):
    if _a == "--pen" and _i + 1 < len(sys.argv):
        PEN = sys.argv[_i + 1]
    elif _a == "--out" and _i + 1 < len(sys.argv):
        OUT_JSON = sys.argv[_i + 1]
QUANT = 6                      # 探针输出精度：6 位小数（D-143：先量化再比）

# tag, 臂 A, 臂 B, A 的中文名, B 的中文名, 既有判词文件
PAIRS = [
    ("sens", "R_free", "A0_free", "R_free(位不动,清缓存,重解)", "A0_free(位全清,清缓存,重解)",
     "a0_free_sensitivity.json"),
    ("repro", "A240", "R_free", "A240(缓存回放)", "R_free(重解)",
     "a0_free_reproducibility.json"),
    ("determ", "R_free", "R_free2", "R_free", "R_free2(再解一遍)",
     "a0_free_determinism.json"),
]


def sha_set(path):
    """D-136 的惯例：raw / lf_normalized / crlf 三个数一起给。"""
    with io.open(path, "rb") as fh:
        raw = fh.read()
    lf = raw.replace(b"\r\n", b"\n")
    crlf = lf.replace(b"\n", b"\r\n")
    return {
        "bytes": len(raw),
        "sha256_raw": hashlib.sha256(raw).hexdigest(),
        "sha256_lf_normalized": hashlib.sha256(lf).hexdigest(),
        "sha256_crlf": hashlib.sha256(crlf).hexdigest(),
    }


def load(name):
    path = os.path.join(PEN, name + ".meta.json")
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with io.open(path, encoding="utf-8") as fh:
        meta = json.load(fh)
    frames = {}
    for r in meta.get("per_frame") or []:
        frames[int(r["frame"])] = {
            "max_depth_m": float(r["max_depth_m"]),
            "overlapping_pairs": int(r.get("overlapping_pairs") or 0),
            "raw_depth_m": float(r.get("raw_depth_m") or 0.0),
        }
    return meta, frames, path


def quant(x):
    return round(x, QUANT)


def pair_stats(tag, a_name, b_name, a_label, b_label, a_frames, b_frames):
    common = sorted(set(a_frames) & set(b_frames))
    d = {f: a_frames[f]["max_depth_m"] - b_frames[f]["max_depth_m"] for f in common}
    absd = {f: abs(d[f]) for f in common}
    nz = [f for f in common if quant(absd[f]) > 0]
    worst = max(common, key=lambda f: absd[f])
    deeper_b = sum(1 for f in common if d[f] > 0)      # b 更负 = b 更深
    deeper_a = sum(1 for f in common if d[f] < 0)
    identical_maxdepth = len(common) - len(nz)
    row_identical = sum(1 for f in common
                        if (a_frames[f]["max_depth_m"] == b_frames[f]["max_depth_m"]
                            and a_frames[f]["overlapping_pairs"] == b_frames[f]["overlapping_pairs"]
                            and a_frames[f]["raw_depth_m"] == b_frames[f]["raw_depth_m"]))
    nz_vals = [absd[f] for f in nz]
    all_vals = [absd[f] for f in common]

    def q(vals, p):
        if not vals:
            return None
        s = sorted(vals)
        k = (len(s) - 1) * p
        lo, hi = int(k), min(int(k) + 1, len(s) - 1)
        return quant(s[lo] + (s[hi] - s[lo]) * (k - lo))

    return {
        "tag": tag,
        "a": a_label,
        "b": b_label,
        "frames": len(common),
        "frame_range": [common[0], common[-1]] if common else None,
        # 同一帧 max_depth_m 六位量化后相等（旧 compare 脚本的 identical_frames 口径）
        "max_depth_equal_frames": identical_maxdepth,
        # 三元组（max_depth / overlapping_pairs / raw_depth）全等（judge 的 identical 口径）
        "row_identical_frames": row_identical,
        "a_deeper_frames": deeper_a,
        "b_deeper_frames": deeper_b,
        "abs_delta_m": {
            "over_all_frames": {
                "count": len(all_vals),
                "median": q(all_vals, 0.5),
                "mean": quant(statistics.mean(all_vals)) if all_vals else None,
                "p10": q(all_vals, 0.10),
                "p25": q(all_vals, 0.25),
                "p75": q(all_vals, 0.75),
                "p90": q(all_vals, 0.90),
                "max": quant(max(all_vals)) if all_vals else None,
                "max_frame": worst if all_vals else None,
            },
            "over_nonzero_frames": {
                "count": len(nz_vals),
                "median": q(nz_vals, 0.5),
                "mean": quant(statistics.mean(nz_vals)) if nz_vals else None,
                "max": quant(max(nz_vals)) if nz_vals else None,
            },
            "max_raw_float": absd[worst] if common else None,
            "max_raw_delta_signed": d[worst] if common else None,
            "quantized_to": "1e-%d" % QUANT,
        },
        "overlapping_pairs_sum": {
            a_label: sum(a_frames[f]["overlapping_pairs"] for f in common),
            b_label: sum(b_frames[f]["overlapping_pairs"] for f in common),
        },
        "raw_depth_min": {
            a_label: quant(min(a_frames[f]["raw_depth_m"] for f in common)) if common else None,
            b_label: quant(min(b_frames[f]["raw_depth_m"] for f in common)) if common else None,
        },
    }


def check(label, got, want, rows):
    ok = got == want
    rows.append({"check": label, "got": got, "want": want, "ok": ok})
    print("  [%s] %-52s got=%r want=%r" % ("PASS" if ok else "FAIL", label, got, want))
    return ok


def selftest():
    """统计函数的自检：喂已知答案的构造序列。"""
    print("[selftest] 分位/中位/量化")
    ok = True
    rows = []
    # 偶数个、中间两个不同 ⇒ 中位取两者均值；先量化 6 位
    vals = [0.001, 0.002, 0.004, 0.009]
    ok &= check("median(4 个)= (0.002+0.004)/2", quant(statistics.median(vals)), 0.003, rows)
    ok &= check("median(奇数个)", quant(statistics.median([0.001, 0.003, 0.02])), 0.003, rows)
    # 量化边界：分辨率是 1e-6（6 位小数），不是 1e-3。
    # 第一版把「0.0004 → 0」写进断言，被自己的自检抓住——0.0004 s = 400 µs，本来就该留着。
    ok &= check("量化 4e-7→0", quant(0.0000004), 0.0, rows)
    ok &= check("量化 6e-7→1e-6", quant(0.0000006), 0.000001, rows)
    ok &= check("量化 0.0004 保留", quant(0.0004), 0.0004, rows)
    # 两端各留一个已知极值：p0/p100 式检查（max 必须等于真最大）
    ok &= check("max 取真最大", quant(max([0.001, 0.015544, 0.002])), 0.015544, rows)
    return ok, rows


def cross_check(table_rows, judges):
    """与既有产物逐项对账：中位/最大/相同帧数/重叠对数。"""
    print("[cross-check] 与既有判词文件对账")
    rows = []
    ok = True
    by_tag = {r["tag"]: r for r in table_rows}

    for tag, want in judges.items():
        jd = (want.get("detail") or {})
        t = by_tag[tag]
        ok &= check("%s max_abs_delta_m ≡ judge" % tag,
                    t["abs_delta_m"]["over_all_frames"]["max"], jd.get("max_abs_delta_m"), rows)
        ok &= check("%s worst_frame ≡ judge" % tag,
                    t["abs_delta_m"]["over_all_frames"]["max_frame"], jd.get("worst_frame"), rows)
        ok &= check("%s overlapping_pairs ≡ judge" % tag,
                    sorted(t["overlapping_pairs_sum"].values()),
                    sorted((jd.get("overlapping_pairs_sum") or {}).values()), rows)

    # 旧 compare 脚本的 identical_frames 口径（只比 max_depth）
    with io.open(os.path.join(PEN, "a0_free_perframe_compare.json"), encoding="utf-8") as fh:
        old = json.load(fh)
    old_by_tag = {r["tag"]: r for r in old["rows"]}
    for tag in ("灵敏度", "可重现", "确定性"):
        old_tag = {"灵敏度": "sens", "可重现": "repro", "确定性": "determ"}[tag]
        ok &= check("旧 compare 相同帧(%s) ≡ 本表" % tag,
                    old_by_tag[tag]["identical_frames"], by_tag[old_tag]["max_depth_equal_frames"], rows)
        ok &= check("旧 compare max_abs_delta(%s) ≡ 本表" % tag,
                    round(old_by_tag[tag]["max_abs_delta_m"], QUANT),
                    by_tag[old_tag]["abs_delta_m"]["over_all_frames"]["max"], rows)
    return ok, rows


def main():
    print("spec=%s" % SPEC)
    ok_self, self_rows = selftest()

    metas, frames, hashes = {}, {}, {}
    for _tag, a, b, _la, _lb, _judge in PAIRS:
        for name in (a, b):
            if name in frames:
                continue
            try:
                meta, fr, path = load(name)
            except FileNotFoundError as exc:
                print("[算不出] 缺产物：%s" % exc)
                return 2
            if len(fr) != 240:
                print("[算不出] %s 只有 %d 帧（要 240）" % (name, len(fr)))
                return 2
            metas[name] = meta
            frames[name] = fr
            hashes[name] = {"path": path.replace("/", "\\"),
                            "sha256_lf_normalized": sha_set(path)["sha256_lf_normalized"],
                            "bytes": os.path.getsize(path)}

    print("\n[arms] 读数前提")
    for name in sorted(metas):
        cs = metas[name].get("cache_state") or {}
        print("  %-8s is_baked=%-5r eval_policy=%-24r frames_measured=%s"
              % (name, cs.get("is_baked"), metas[name].get("eval_policy"),
                 metas[name].get("frames_measured")))

    rows = []
    for tag, a, b, a_label, b_label, _judge in PAIRS:
        rows.append(pair_stats(tag, a, b, a_label, b_label, frames[a], frames[b]))

    print("\n[table] 三对臂")
    for r in rows:
        d = r["abs_delta_m"]["over_all_frames"]
        print("  %-6s %-28s vs %-28s frames=%d 全等=%d 量化等=%d A深=%d B深=%d"
              % (r["tag"], r["a"], r["b"], r["frames"], r["row_identical_frames"],
                 r["max_depth_equal_frames"], r["a_deeper_frames"], r["b_deeper_frames"]))
        print("         |Δ| 中位=%s m 均值=%s p90=%s 最大=%s m @f%s  (raw float %r)"
              % (d["median"], d["mean"], d["p90"], d["max"], d["max_frame"], r["abs_delta_m"]["max_raw_float"]))

    judges = {}
    for _tag, _a, _b, _la, _lb, judge_file in PAIRS:
        p = os.path.join(PEN, judge_file)
        if os.path.exists(p):
            with io.open(p, encoding="utf-8") as fh:
                judges[{"a0_free_sensitivity.json": "sens",
                        "a0_free_reproducibility.json": "repro",
                        "a0_free_determinism.json": "determ"}[judge_file]] = json.load(fh)
    ok_cross, cross_rows = cross_check(rows, judges)

    out = {
        "spec": SPEC,
        "what": "A0 正控 v2 三对臂的逐帧分布（由 *_meta.json 只读重算；不开 Blender）",
        "why": "旧 compare 只存 max，中位数只在 stdout；本表把分布与读数前提一起落盘",
        "quantized_to": "1e-%d（探针输出精度，D-143 先量化再比）" % QUANT,
        "arms": hashes,
        "arm_state": {name: {"is_baked": (metas[name].get("cache_state") or {}).get("is_baked"),
                             "is_outdated": (metas[name].get("cache_state") or {}).get("is_outdated"),
                             "eval_policy": metas[name].get("eval_policy"),
                             "frames_measured": metas[name].get("frames_measured"),
                             "blend": metas[name].get("blend")}
                      for name in metas},
        "pairs": rows,
        "judge_words_as_recorded": {k: {"tier": v.get("tier"), "word": v.get("word"),
                                        "verdict": (v.get("detail") or {}).get("verdict")}
                                    for k, v in judges.items()},
        "selftest": {"ok": bool(ok_self), "rows": self_rows},
        "cross_check": {"ok": bool(ok_cross), "rows": cross_rows},
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with io.open(OUT_JSON, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print("\nwritten %s" % OUT_JSON)

    if not ok_self:
        print("[FAIL] 自检不过 ⇒ 表里的数一律不许发")
        return 1
    if not ok_cross:
        print("[FAIL] 与既有产物对不上 ⇒ 先查哪边错，不许解释")
        return 1
    print("[OK] 自检 + 对账全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
