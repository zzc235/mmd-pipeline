# -*- coding: utf-8 -*-
"""A0 仪器灵敏度正控的判定器（纯 Python，不开 Blender）。

预注册 v4 §二 三档（**分层不许改**）：

| A0 vs A | 判词 |
|---|---|
| 逐帧逐位相同（`max_depth_m` 与 `overlapping_pairs` 全等） | **仪器看不见碰撞状态** ⇒ 四组全部作废，判 `UNMEASURED` |
| 有差别，但 `max|Δ(max_depth_m)| < 1 mm` | **仪器分辨率不足** ⇒ 只许出「结论级变化」判词，**不许**出「结论不变 / 通道无影响」 |
| `max|Δ| >= 1 mm` | 仪器有效 ⇒ 两种判词都可用 |

另报方向：关掉碰撞后刚体应互相穿透 ⇒ `overlapping_pairs` 与 `raw_depth_m` 应**变大**；
方向反了单列，不许并进「仪器有效」。

退出码：0 = 三档判出且无异常 / 3 = 不可判（缺帧、空数据、格式不符）/ 4 = 自检失败 / 2 = 用法
"""
import argparse
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

TIER_RESOLUTION_M = 0.001      # 1 mm，与 1号 S2 预注册同一判据；也是 20 mm 判据的 1/20


def load_frames(path):
    with open(path, "r", encoding="utf-8") as fh:
        meta = json.load(fh)
    rows = meta.get("per_frame") or []
    out = {}
    for r in rows:
        out[int(r["frame"])] = {
            "max_depth_m": float(r["max_depth_m"]),
            "overlapping_pairs": int(r.get("overlapping_pairs") or 0),
            "raw_depth_m": float(r.get("raw_depth_m") or 0.0),
        }
    return meta, out


def judge(a_frames, a0_frames):
    """返回 (档位, 判词, 详情)。档位 1/2/3 对应预注册表；`None` 表示不可判。"""
    if not a_frames or not a0_frames:
        return None, "UNMEASURED", {"reason": "空 per_frame（没有取到任何一帧）"}
    common = sorted(set(a_frames) & set(a0_frames))
    if len(common) != len(a_frames) or len(common) != len(a0_frames):
        return None, "UNMEASURED", {
            "reason": "帧集合不一致：A=%d A0=%d 交集=%d"
                      % (len(a_frames), len(a0_frames), len(common))}
    identical = all(a_frames[f] == a0_frames[f] for f in common)
    deltas_raw = {f: abs(a0_frames[f]["max_depth_m"] - a_frames[f]["max_depth_m"]) for f in common}
    worst_f = max(deltas_raw, key=lambda f: deltas_raw[f])
    # 探针输出本身是 6 位小数（`depth = -round(worst, 6)`），但浮点减法会在边界上出噪声：
    # 实测 `0.018 - 0.017 = 0.0009999999999999998 < 0.001`，于是「恰好 1 mm」被判进第 2 档。
    # 所以在**仪器分辨率（6 位）上先取整，再判边界**；原始浮点值一并报出来。
    max_abs_delta = round(deltas_raw[worst_f], 6)
    # 方向：关掉碰撞后应当更"穿透"（max_depth_m 更负、overlapping_pairs 更多）
    ovl_a = sum(a_frames[f]["overlapping_pairs"] for f in common)
    ovl_a0 = sum(a0_frames[f]["overlapping_pairs"] for f in common)
    raw_a = min(a_frames[f]["raw_depth_m"] for f in common)
    raw_a0 = min(a0_frames[f]["raw_depth_m"] for f in common)
    direction_ok = (a0_frames[worst_f]["max_depth_m"] <= a_frames[worst_f]["max_depth_m"]
                    and ovl_a0 >= ovl_a and raw_a0 <= raw_a)
    detail = {
        "frames_compared": len(common),
        "identical": identical,
        "max_abs_delta_m": max_abs_delta,
        "max_abs_delta_m_raw_float": deltas_raw[worst_f],
        "quantized_to": "1e-06（探针输出精度）",
        "worst_frame": worst_f,
        "A_max_depth_m": a_frames[worst_f]["max_depth_m"],
        "A0_max_depth_m": a0_frames[worst_f]["max_depth_m"],
        "overlapping_pairs_sum": {"A": ovl_a, "A0": ovl_a0},
        "raw_depth_min": {"A": round(raw_a, 9), "A0": round(raw_a0, 9)},
        "direction_expected": "A0 更穿透（max_depth_m 更负 / overlapping_pairs 更多 / raw 更负）",
        "direction_ok": direction_ok,
    }
    if identical:
        return 1, "UNMEASURED", dict(detail, verdict="仪器看不见碰撞状态 ⇒ 四组全部作废")
    if max_abs_delta < TIER_RESOLUTION_M:
        return 2, "分辨率不足", dict(detail, verdict="只许出「结论级变化」，不许出「结论不变」")
    return 3, "仪器有效", dict(detail, verdict="两种判词都可用")


def selftest():
    ok = True

    def chk(title, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print("  [%s] %-46s got=%r want=%r" % ("PASS" if good else "FAIL", title, got, want))

    print("[selftest] 三档判定（预注册 §二，分层不许挪）")

    def mk(frames):
        return {f: {"max_depth_m": d, "overlapping_pairs": n, "raw_depth_m": d}
                for f, d, n in frames}

    a = mk([(1, -0.017, 10), (2, -0.015, 11)])
    chk("逐位相同 ⇒ 档 1（仪器瞎）", judge(a, dict(a))[0], 1)
    chk("Δ=0.4 mm ⇒ 档 2（分辨率不足）", judge(a, mk([(1, -0.0174, 10), (2, -0.015, 11)]))[0], 2)
    chk("Δ=3 mm ⇒ 档 3（有效）", judge(a, mk([(1, -0.020, 12), (2, -0.015, 11)]))[0], 3)
    chk("边界 Δ 恰好 1 mm ⇒ 档 3（>=1mm 即有效）",
        judge(a, mk([(1, -0.018, 12), (2, -0.015, 11)]))[0], 3)
    chk("空数据 ⇒ 不可判", judge({}, a)[0], None)
    chk("帧集合不一致 ⇒ 不可判", judge(a, mk([(1, -0.020, 12)]))[0], None)

    print("[selftest] 方向控制（关碰撞后应更穿透）")
    eff = judge(a, mk([(1, -0.020, 12), (2, -0.015, 11)]))[2]
    chk("A0 更穿透 ⇒ direction_ok", eff["direction_ok"], True)
    rev = judge(a, mk([(1, -0.010, 5), (2, -0.015, 11)]))[2]
    chk("方向反了 ⇒ direction_ok=False（要单列）", rev["direction_ok"], False)

    print("\n[selftest] %s" % ("全部通过" if ok else "有失败——A0 判定不许引用"))
    return 0 if ok else 4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", help="A 组 meta（原场景）")
    ap.add_argument("--a0", help="A0 组 meta（碰撞全关）")
    ap.add_argument("--json", default="")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not (a.a and a.a0):
        ap.print_help()
        return 2

    meta_a, fa = load_frames(a.a)
    meta_a0, fa0 = load_frames(a.a0)
    tier, word, detail = judge(fa, fa0)
    print("[A0] tier=%s  判词=%s" % (tier, word))
    for k in ("frames_compared", "max_abs_delta_m", "worst_frame", "A_max_depth_m",
              "A0_max_depth_m", "overlapping_pairs_sum", "raw_depth_min", "direction_ok"):
        if k in detail:
            print("      %-24s %s" % (k, json.dumps(detail[k], ensure_ascii=False)))
    if detail.get("reason"):
        print("      reason: %s" % detail["reason"])
    print("      结论：%s" % detail.get("verdict", ""))
    # 记录两次跑的 blend sha 与口径，便于事后核对
    prov = {k: {"A": meta_a.get(k), "A0": meta_a0.get(k)}
            for k in ("blend", "frames", "frames_measured", "eval_policy", "baseline_sha256")}
    print("[A0] provenance %s" % json.dumps(prov, ensure_ascii=False)[:400])
    if a.json:
        with open(a.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"spec": "m04_a0_control/1", "tier": tier, "word": word,
                       "detail": detail, "provenance": prov,
                       "criterion_m": TIER_RESOLUTION_M,
                       "not_a_verdict_for_groups": "A0 不进任何判词；它只决定四组能不能被引用"},
                      fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        print("[A0] written %s" % a.json)
    return 0 if tier else 3


if __name__ == "__main__":
    sys.exit(main())
