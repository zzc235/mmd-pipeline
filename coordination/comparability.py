"""可比性闸门：让「这组数能不能比」成为一等检查，而不是靠读的人记得。

## 为什么有这个东西

2026-11-16 一晚，同一形状错了四次，四次都是「把一段/一域的读数当成另一段/另一域的属性」：

1. `2号` 拿 `C@W2` 全域（832 帧）的最坏值减 `C@W1` 域内（240 帧）的最坏值，得 `0.049031 m`；
   同域是 `0.046198 m`。
2. `2号` 说「保持段整体不更深」：中位 `-1.556` 比 `-1.324` **更负即更深**，方向读反。
3. `2号` 把保持段里 50 帧交接瞬态的极值当成 531 帧整段的属性。
4. `4号` 在更正里把 `352..832` 的最坏帧 `f353` 写进 `355..832` 的句子里（窗外的帧号当窗内的）。

四次都不是算错 —— 逐帧值、sha、分段计数每次都对。**错的是「这个数属于哪一段」**。
手写循环取极值，换个人、换个切点、隔一条消息就会再错一次。所以做成闸门。

## 三件事

1. `check_sides(a, b)`：两边逐条给出**可比性六条**，缺一条或两边不等即拒（`EVIDENCE_SCOPE_MISMATCH`）。
2. `domain_extrema(a_frames, b_frames, lo, hi)`：同域差**由它自己算**，接口只吃逐帧数组 +
   帧域，**拒收两个标量** —— 「跨域相减」这种调用在类型上就写不出来。
3. `extremum_report(frames, frame, ...)`：极值只能经它取，同笔给出
   `值 + 帧号 + 邻域计数 + 窗口规则`；帧号不在给的帧域里直接拒（第 4 条错的形状）。

## 窗口规则必须「先于数据可判」

`preregistered`（冻结预注册写死）与 `segment_ratio`（按段长比例切，比例先于数据）
可以当判据；`post_hoc`（看着极端值挤在哪儿切）**只许作解释**，标 `POST_HOC_WINDOW`，
当判据用即被拒。理由不是洁癖：事后窗口把结论写进前提，是 `D-196` 那族的错法。

退出码（CLI）：0 通过 / 3 不可比 / 2 用法错。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

#: 可比性六条。两边逐条相等才谈得上「同一个问题的两个答案」。
COMPARABILITY_FIELDS = (
    "frame_domain",      # 逐帧数据覆盖哪一段（闭区间 [lo, hi]）
    "baseline",          # 零点在哪：静态件？每臂自己的窗口首帧？(带 sha)
    "pair_universe",     # 候选对宇宙：哪些对参与了比较（带规模）
    "scale",             # 刚体/骨骼尺度（312 / 323 / 324 不许跨）
    "segment_label",     # 这段叫动画段 / 保持段 / 稳态保持 …… 边界怎么来的
    "window_rule",       # 窗口按什么规则定的（见下）
)

#: `window_rule` 的闭集。只有前两种能当判据。
WINDOW_RULES = ("preregistered", "segment_ratio", "post_hoc")
CRITERION_WINDOW_RULES = ("preregistered", "segment_ratio")

#: 极值邻域判词。
TRANSIENT = "TRANSIENT"      # 尖峰：邻域内几乎没有同量级的帧 -> 不许当整段属性引用
PLATEAU = "PLATEAU"          # 平台：邻域内有若干同量级的帧 -> 可当该段属性引用


class ComparabilityError(ValueError):
    """不可比 / 调用方式本身错。宁可红，也不许给一个看起来能用的数。"""


def _norm_domain(dom):
    """把帧域规范成 `(lo, hi)` 两个整数；接受 `[1, 240]` / `(1, 240)` / `{"lo":1,"hi":240}`。"""
    if isinstance(dom, dict):
        dom = (dom.get("lo"), dom.get("hi"))
    if not isinstance(dom, (list, tuple)) or len(dom) != 2:
        raise ComparabilityError("帧域必须写成 [lo, hi]，收到 %r" % (dom,))
    lo, hi = dom
    if not isinstance(lo, int) or not isinstance(hi, int) or lo > hi:
        raise ComparabilityError("帧域必须两个整数且 lo <= hi，收到 %r" % (dom,))
    return lo, hi


def _nonempty(value):
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) > 0
    return True


def check_sides(a: dict, b: dict) -> dict:
    """检查两组读数是否可比。`a` / `b` 各自带可比性六条。

    返回 `{"state": "OK"|"INCOMPARABLE", "problems": [...], "shared": {...}}`。
    `problems` 里每条都带 `field`，不合并成一句「不可比」—— 读的人要知道改哪一条。
    """
    problems = []
    shared = {}
    for field in COMPARABILITY_FIELDS:
        va = (a or {}).get(field)
        vb = (b or {}).get(field)
        if not _nonempty(va):
            problems.append({"field": field, "side": "a", "why": "missing"})
        if not _nonempty(vb):
            problems.append({"field": field, "side": "b", "why": "missing"})
        if not _nonempty(va) or not _nonempty(vb):
            continue
        # `scale` 允许不等，但两边都必须显式声明「知道尺度不同」；否则跨尺度相减是偷偷做的。
        if field == "scale":
            if va != vb:
                if not (a.get("scale_annotated") is True and b.get("scale_annotated") is True):
                    problems.append({"field": field, "why": "scale_differs_not_annotated",
                                     "a": va, "b": vb})
                else:
                    shared[field] = "differs(annotated)"
            else:
                shared[field] = va
            continue
        if va != vb:
            problems.append({"field": field, "why": "sides_differ", "a": va, "b": vb})
        else:
            shared[field] = va
    # 窗口规则：必须在闭集里，且 post_hoc 不许当判据
    for side, rec in (("a", a or {}), ("b", b or {})):
        rule = rec.get("window_rule")
        if rule is None:
            continue
        if rule not in WINDOW_RULES:
            problems.append({"field": "window_rule", "side": side, "why": "not_in_closed_set",
                             "got": rule, "allowed": list(WINDOW_RULES)})
        elif rule == "post_hoc" and rec.get("as_criterion") is True:
            problems.append({"field": "window_rule", "side": side,
                             "why": "post_hoc_window_not_criterion",
                             "hint": "事后窗口只许作解释，改用 preregistered / segment_ratio"})
    return {"state": "INCOMPARABLE" if problems else "OK",
            "problems": problems, "shared": shared}


def _frames_map(frames, key):
    """把逐帧数组变成 `{帧号: 值}`；**拒收标量**（那正是跨域相减的入口）。"""
    if isinstance(frames, (int, float)) or frames is None:
        raise ComparabilityError(
            "要逐帧数组，收到一个标量（%r）。两个标量相减就是跨域相减的入口，本闸门不提供这条路。"
            % (frames,))
    if not isinstance(frames, (list, tuple)):
        raise ComparabilityError("要逐帧数组（list of dict），收到 %s" % type(frames).__name__)
    out = {}
    for row in frames:
        if not isinstance(row, dict) or "frame" not in row or key not in row:
            raise ComparabilityError("逐帧记录必须含 `frame` 与 %r，收到 %r" % (key, row))
        out[int(row["frame"])] = row[key]
    return out


def domain_extrema(a_frames, b_frames, lo, hi=None, key: str = "max_depth_m",
                   deeper_is_lower: bool = True) -> dict:
    """在**同一个帧域** `[lo, hi]` 上取两边极值并给出差。

    两边各自的覆盖必须**包含** `[lo, hi]` 的每一帧 —— 少一帧就说明「这段数据不覆盖这个域」，
    指标算不出来却会被算成 0。**拒。**

    数据延伸到 `[lo, hi]` 之外不拒（只记一笔）：本函数只用 `[lo, hi]` 里的帧算极值，
    而「跨域相减」在这个签名下**结构上写不出来** —— 帧域只有一份，两边共用。
    """
    lo, hi = _norm_domain((lo, hi) if hi is not None else lo)
    a = _frames_map(a_frames, key)
    b = _frames_map(b_frames, key)
    problems = []
    extends = {}
    for side, m in (("a", a), ("b", b)):
        missing = [f for f in range(lo, hi + 1) if f not in m]
        extra = sorted(f for f in m if not (lo <= f <= hi))
        if missing:
            problems.append({"side": side, "why": "missing_frames", "count": len(missing),
                             "first": missing[:5]})
        if extra:
            extends[side] = len(extra)
    if problems:
        return {"state": "INCOMPARABLE", "problems": problems}

    pick = min if deeper_is_lower else max
    wa = pick(range(lo, hi + 1), key=lambda f: a[f])
    wb = pick(range(lo, hi + 1), key=lambda f: b[f])
    delta = abs(a[wa] - b[wb])
    return {
        "state": "OK",
        "frame_domain": [lo, hi],
        "a": {"worst_frame": wa, key: a[wa]},
        "b": {"worst_frame": wb, key: b[wb]},
        "delta": delta,
        "deeper_is_lower": deeper_is_lower,
        "data_extends_beyond_domain": extends,
        "note": "同域差由本函数算，勿在报告里手工相减",
    }


def extremum_report(frames, frame: int, key: str = "max_depth_m",
                    halfwidth: int = 12, half_magnitude_ratio: float = 0.5,
                    window_rule: str = "segment_ratio") -> dict:
    """极值引用三件套 + 窗口规则：`值 + 帧号 + 邻域计数`，并给 `TRANSIENT` / `PLATEAU` 判词。

    `frame` 必须落在 `frames` 的帧域里 —— 窗外的帧号直接拒（2026-11-16 第四次错的形状：
    切点从 `352` 挪到 `355`，最坏帧 `f353` 没跟着挪）。
    """
    if window_rule not in WINDOW_RULES:
        raise ComparabilityError("window_rule %r 不在闭集 %r" % (window_rule, WINDOW_RULES))
    m = _frames_map(frames, key)
    frame = int(frame)
    if frame not in m:
        raise ComparabilityError(
            "帧号 f%d 不在给的帧域 [%d, %d] 里 —— 窗外的帧号不许当窗内极值引用"
            % (frame, min(m), max(m)))
    value = m[frame]
    half = abs(value) * half_magnitude_ratio
    lo, hi = frame - halfwidth, frame + halfwidth
    neighbours = [f for f in m if lo <= f <= hi and abs(m[f]) >= half]
    # 邻域里除自己以外还有几帧达到半量级
    peers = [f for f in neighbours if f != frame]
    label = TRANSIENT if len(peers) <= 1 else PLATEAU
    return {
        "frame": frame,
        key: value,
        "halfwidth": halfwidth,
        "half_magnitude": half,
        "neighbourhood_size": sum(1 for f in m if lo <= f <= hi),
        "peers_at_half_magnitude": len(peers),
        "label": label,
        "window_rule": window_rule,
        "usable_as_segment_property": label == PLATEAU,
        "note": ("尖峰：邻域内没有同量级的帧，不许当整段属性引用，只能写成「f%d 这一帧」"
                 % frame) if label == TRANSIENT else "平台：邻域内有同量级帧，可作为该段属性引用",
    }


def ratio_cuts(segment_start: int, segment_end: int, ratios) -> list:
    """把一组比例映射成一组候选切点（窗口末帧），供 `cut_sensitivity()` 用。

    比例与切点是一一对应的：`cut = start + round(len * ratio) - 1`。
    `2号` 2026-11-16 晚量到这条对应关系的**下限**：`C@W2` 保持段上

        5%  -> 瞬态 302..328，稳态里还有 24 帧越判据、最深 -81.290 @f347（结论翻转）
        10% -> 瞬态 302..354，稳态 11 帧越判据、最深 -65.647 @f646
        15% / 20% -> 与 10% 同

    所以「比例规则先于数据可判」还不够 —— **比例本身也得带上敏感度**。
    """
    length = int(segment_end) - int(segment_start) + 1
    if length <= 0:
        raise ComparabilityError("段 [%d, %d] 不成立" % (segment_start, segment_end))
    out = []
    for r in ratios:
        r = float(r)
        if not 0.0 < r < 1.0:
            raise ComparabilityError("ratio 必须在 (0, 1)，收到 %r" % (r,))
        out.append(int(segment_start) + max(1, int(round(length * r))) - 1)
    return out


def window_cut(segment_start: int, segment_end: int, rule: str,
               ratio: float = 0.10, cut: int | None = None, note: str = "",
               stability: dict | None = None) -> dict:
    """按规则切一个窗口。

    `segment_ratio` 用段长比例（先于数据可判），但**必须同时给 `stability`**
    ——`cut_sensitivity()` 在若干比例上的结果。理由：比例规则救得了「换个人换个数」，
    救不了「比例本身把结论切翻」（5% 时极端值落进稳态窗口）。
    `worst_frame_stable` 为假即拒：那时的比例把结论切翻了，不许当判据。
    """
    if rule not in WINDOW_RULES:
        raise ComparabilityError("window_rule %r 不在闭集 %r" % (rule, WINDOW_RULES))
    start, end = int(segment_start), int(segment_end)
    if end < start:
        raise ComparabilityError("段 [%d, %d] 不成立" % (start, end))
    length = end - start + 1
    if rule == "segment_ratio":
        if not 0.0 < ratio < 1.0:
            raise ComparabilityError("ratio 必须在 (0, 1)，收到 %r" % (ratio,))
        width = max(1, int(round(length * ratio)))
        got = {"rule": rule, "ratio": ratio, "segment": [start, end],
               "window": [start, start + width - 1],
               "rest": [start + width, end] if start + width <= end else [],
               "usable_as_criterion": False,
               "note": ""}
        if stability is None:
            got["note"] = ("比例规则必须先跑 `cut_sensitivity()`（用 `ratio_cuts()` 把比例映射成切点）"
                           "并在报告里带上比例；未带敏感度时不许当判据")
            return got
        if not stability.get("worst_frame_stable"):
            got["note"] = ("该比例把结论切翻了（极值帧随比例变化：%r）"
                           % (stability.get("worst_frames"),))
            return got
        got["usable_as_criterion"] = True
        got["ratio_floor_checked"] = True
        got["over_eps_range"] = stability.get("over_eps_range")
        got["note"] = ("比例先于数据可判，且极值帧对该组比例不变 => 结论可引；"
                       "over_eps 随比例浮动 => 引用时必须带比例")
        return got
    if cut is None:
        raise ComparabilityError("rule=%s 必须给显式 cut 帧" % rule)
    cut = int(cut)
    if not start <= cut < end:
        raise ComparabilityError("cut f%d 必须落在 [%d, %d) 内" % (cut, start, end))
    return {"rule": rule, "segment": [start, end], "window": [start, cut],
            "rest": [cut + 1, end],
            "usable_as_criterion": rule in CRITERION_WINDOW_RULES,
            "note": note or ("预注册写死的切点" if rule == "preregistered"
                             else "事后窗口：只许作解释，不许作判据")}


def _window_stats(m, lo, hi, key, eps):
    sel = [f for f in m if lo <= f <= hi]
    if not sel:
        return None
    over = [f for f in sel if m[f] <= -eps]
    worst = min(sel, key=lambda f: m[f])
    return {"window": [lo, hi], "frames": len(sel), "over_eps": len(over),
            "worst_frame": worst, key: m[worst]}


def cut_sensitivity(frames, cuts, segment_start: int, segment_end: int | None = None,
                    key: str = "max_depth_m", eps: float = 0.020) -> dict:
    """同一个「窗口从哪儿切」换成若干个候选切点，看结论稳不稳、数浮不浮。

    **「对切点稳健」这句话必须由它自己算出来，不能由作者嘴说。**

    两段都算（给定 `segment_end` 时）：`prefix = [start, cut]`、`rest = [cut+1, end]`。
    只看 `prefix` 会漏掉真正会翻的那种情况 —— `2号` / `4号` 量的下限：

        5%  -> prefix 302..328，rest 里还有 24 帧越判据、最深 -81.290 @f347
        10% -> prefix 302..354，rest 11 帧越判据、最深 -65.647 @f646

    `prefix` 的极值帧两次都是 `f304`（看起来稳），**翻的是 `rest` 的极值帧**。
    所以判词按两段的极值帧**联合**判：任一段的极值帧随切点动，结论就不稳。
    """
    m = _frames_map(frames, key)
    start = int(segment_start)
    end = None if segment_end is None else int(segment_end)
    rows = []
    for cut in sorted(int(c) for c in cuts):
        if cut < start:
            raise ComparabilityError("切点 f%d 在段起点 f%d 之前" % (cut, start))
        pre = _window_stats(m, start, cut, key, eps)
        if pre is None:
            raise ComparabilityError("窗口 [%d, %d] 里没有数据" % (start, cut))
        row = {"cut": cut, "prefix": pre}
        if end is not None:
            if cut >= end:
                raise ComparabilityError("切点 f%d 不早于段末 f%d" % (cut, end))
            row["rest"] = _window_stats(m, cut + 1, end, key, eps)
        rows.append(row)

    def _collect(side, field):
        vals = []
        for r in rows:
            blk = r.get(side)
            if blk is None:
                continue
            vals.append(blk["worst_frame"] if field == "worst_frame" else blk[field])
        return vals

    sides = ["prefix"] + (["rest"] if end is not None else [])
    frame_sets = {s: _collect(s, "worst_frame") for s in sides}
    count_sets = {s: _collect(s, "over_eps") for s in sides}
    worst_frames = sorted({f for vs in frame_sets.values() for f in vs})
    counts = [c for vs in count_sets.values() for c in vs]
    values = [r[s][key] for r in rows for s in sides if r.get(s)]
    stable_frame = all(len(set(vs)) == 1 for vs in frame_sets.values())
    stable_count = all(len(set(vs)) == 1 for vs in count_sets.values())
    if stable_frame and stable_count:
        verdict = "STABLE"
    elif stable_frame:
        verdict = "CONCLUSION_STABLE_NUMBER_UNSTABLE"
    else:
        verdict = "UNSTABLE"
    return {
        "segment": [start, end] if end is not None else [start, max(r["cut"] for r in rows)],
        "sides": sides,
        "eps": eps,
        "rows": rows,
        "worst_frames": worst_frames,
        "worst_frames_by_side": frame_sets,
        "over_eps_range": [min(counts), max(counts)],
        "worst_value_range": [min(values), max(values)],
        "worst_frame_stable": stable_frame,
        "over_eps_stable": stable_count,
        "verdict": verdict,
        "note": ("极值帧对所有切点不变 => 这一句可以当结论引用；over_eps 随切点浮动 => "
                 "引用时必须带切点或比例"
                 if verdict == "CONCLUSION_STABLE_NUMBER_UNSTABLE" else
                 "切点/比例影响结论本身 => 不许用事后切点，比例也必须带敏感度表"),
    }


def check_record(record: dict) -> dict:
    """检查一份「引用声明」。`record = {"a": {...}, "b": {...}}`，两边各带可比性六条。"""
    if not isinstance(record, dict):
        raise ComparabilityError("记录必须是 dict，收到 %s" % type(record).__name__)
    for side in ("a", "b"):
        if not isinstance(record.get(side), dict):
            raise ComparabilityError("记录缺 %r 一侧（两边都要给可比性六条）" % side)
    return check_sides(record["a"], record["b"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="comparability", description=__doc__.splitlines()[0])
    ap.add_argument("--check", metavar="JSON", help="检查一份引用声明（可比性六条）")
    args = ap.parse_args(argv)
    if not args.check:
        ap.print_usage(sys.stderr)
        return 2
    try:
        with open(args.check, encoding="utf-8") as fh:
            record = json.load(fh)
        got = check_record(record)
    except (OSError, ValueError) as exc:
        sys.stdout.write("USAGE_ERROR: %s\n" % exc)
        return 2
    sys.stdout.write(json.dumps(got, ensure_ascii=False, sort_keys=True) + "\n")
    return 0 if got["state"] == "OK" else 3


if __name__ == "__main__":
    raise SystemExit(main())
