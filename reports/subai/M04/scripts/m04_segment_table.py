# -*- coding: utf-8 -*-
"""C@W2 分段读数的**生成器**：窗口由规则定，不由「看着哪儿挤就切哪儿」定。

为什么要有这个脚本
------------------
19:30 那版报告里「交接瞬态 302..351」的边界是我事后看着极端值挤在那一带切出来的。
`4号` 用换切点的办法验了一句「结论稳、只有 15 这个数不稳」，然后给了个不依赖数据的
规则：按保持段长度取比例。规则本身对，但手抄表格时又出了一处「窗口与最深帧不配对」
（稳态窗口 355..832 那行写的最深是 f353，而 f353 不在 355..832 里）。

所以这里做两件事：
1. 窗口**只接受规则输入**（`hold_from` + 比例），边界由 `transition_length()` 算出；
2. 相邻窗口必须**恰好铺满**目标区间（不重叠、不留缝），否则拒算 —— 这是
   `assert_partition()`，它的存在不是为了抓代码 bug，是为了让「把某个数记到它不属于的
   窗口里」这件事在源头就不可能（数是从窗口内算出来的，不是人抄进去的）。

窗口规则分类（`总控` 19:34 的口径裁定：窗口规则必须「先于数据可判」）
------------------------------------------------------------------
本脚本只产出 `segment_ratio`（段长比例）一类窗口 —— 先于数据可判、换个人算同一条边界。
看着数据切的窗口（例如 19:30 那版 `302..351`）在本脚本里**造不出来**，要引用只能标
`POST_HOC_WINDOW`，而 `post_hoc` 只许作解释、不许作判据。`rule_kind` 跟着每一行一起输出。

极值的权威口径是 `coordination.comparability.extremum_report()`（D-224）：三件套
（值 + 帧号 + 邻域计数）与 TRANSIENT / PLATEAU 判词都由它给，本脚本不另立一套。
`window_stats()` 经它取最深值并把结果放进每行的 `extremum` 字段；老字段
`deepest_mm` / `deepest_frame` 保留兼容。若 comparability 不在树里，`extremum=None`
明确表示「没接上」，不静默当作已接。

窗口定义（全部由 `hold_from` 与比例导出）
-----------------------------------------
- 动画段：`anim_from .. hold_from-1`
- 保持段：`hold_from .. 最后一帧`
- 比例 r 的两切分：`hold_from .. hold_from+k-1` 与 `hold_from+k .. 最后一帧`，
  其中 `k = round(保持段帧数 * r)`

拒绝（`ValueError`，CLI exit 2）
-------------------------------
- 比例 ≤ 0 或 ≥ 1（切不出两段）；
- 窗口选不到帧，或读数没有铺满请求的窗口（读的是 1..832，问 302..900 是「没量」不是「全 0」）；
- 相邻窗口之间有缝或有重叠。

用法
----
    python reports/subai/M04/scripts/m04_segment_table.py \
        --meta reports/subai/M04/cd_round2/C_W2.meta.json --hold-from 302 \
        --ratio 0.10 --ratio 0.50 --sensitivity 0.05,0.10,0.15,0.20 \
        --boundary-frames 304,344,346,347,353

`--boundary-frames` 回答另一个问题：**边界其实由哪几帧决定**。比例只是让它可复现的
约定；`round(hold_frames*r) >= k` 等价于 `r >= (k-0.5)/hold_frames`，那个 `k-0.5` 阈值
就是「比例调到多少才会翻」。`C@W2` 上是两级台阶：`f347` 要 46 帧（阈值 8.57%）、
`f353` 要 52 帧（9.70%），所以 8% / 9% / 10% 给出三组不同的稳态极值。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from statistics import median

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m04_paths as _paths  # noqa: E402

EPS_DEFAULT = 0.020


def load_frames(path):
    """读一份 meta 的 `per_frame`，返回按帧号升序的记录列表。"""
    with io.open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    rows = doc.get("per_frame")
    if not rows:
        raise ValueError("per_frame 为空：没有读数可分段 (%s)" % path)
    frames = [int(r["frame"]) for r in rows]
    if frames != list(range(frames[0], frames[0] + len(frames))):
        raise ValueError("per_frame 帧号不是从 %d 起的连续整数" % frames[0])
    for r in rows:
        val = r.get("max_depth_m")
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise ValueError("帧 %r 没有数值型 max_depth_m" % (r.get("frame"),))
    return rows


def transition_length(hold_frames, ratio):
    """比例规则：`round(保持段帧数 * ratio)`，两端必须都非空。"""
    ratio = float(ratio)
    if not 0.0 < ratio < 1.0:
        raise ValueError("比例必须在 (0,1) 内，收到 %r" % (ratio,))
    k = int(round(hold_frames * ratio))
    if k < 1:
        raise ValueError("比例 %r 在 %d 帧的保持段上切出来的瞬态窗口是 0 帧"
                         % (ratio, hold_frames))
    if k >= hold_frames:
        raise ValueError("比例 %r 在 %d 帧的保持段上切完没有稳态帧"
                         % (ratio, hold_frames))
    return k


def window_stats(rows, a, b, eps=EPS_DEFAULT):
    """一个窗口内的读数。窗口必须被读数完整覆盖，否则拒算。"""
    a, b = int(a), int(b)
    if b < a:
        raise ValueError("窗口 %d..%d 起止颠倒" % (a, b))
    sel = [r for r in rows if a <= r["frame"] <= b]
    if not sel:
        raise ValueError("窗口 %d..%d 选不到任何帧" % (a, b))
    if sel[0]["frame"] != a or sel[-1]["frame"] != b:
        raise ValueError("窗口 %d..%d 没有被读数铺满（读数在 %d..%d）"
                         % (a, b, sel[0]["frame"], sel[-1]["frame"]))
    vals = [float(r["max_depth_m"]) for r in sel]
    n = len(vals)
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / n
    deep = min(sel, key=lambda r: float(r["max_depth_m"]))
    deep_frame = int(deep["frame"])
    # D-224：极值只能经 coordination.comparability.extremum_report() 取 —— 同笔给出
    # 三件套（值 + 帧号 + 邻域计数）与 TRANSIENT / PLATEAU 判词，不许本脚本另立一套。
    # 老字段 deepest_mm/deepest_frame 保留兼容；extremum 是新增的权威口径。
    # comparability 不在树里时降级为本地三件套缺失（与 _window_rules 的降级风格一致），
    # 但绝不假装接上：extremum=None 是可读的「没接上」事实。
    try:
        _ensure_repo_root_on_path()
        from coordination.comparability import extremum_report
        ext = extremum_report(sel, deep_frame, window_rule="segment_ratio")
    except Exception:
        ext = None
    out = {
        "window": [a, b],
        "frames": n,
        "over_eps": sum(1 for v in vals if v < -eps),
        "median_mm": round(median(vals) * 1000.0, 3),
        "mean_mm": round(mean * 1000.0, 3),
        "sd_mm": round(var ** 0.5 * 1000.0, 3),
        "deepest_mm": round(float(deep["max_depth_m"]) * 1000.0, 3),
        "deepest_frame": deep_frame,
        "extremum": ext,
    }
    return out


def assert_partition(parts, start, end):
    """相邻窗口必须首尾相接、恰好铺满 `start..end`；有缝或重叠一律拒。

    负控（`tests/test_m04_segment_table.py`）：漏一帧、重一帧都必须抛。
    """
    cursor = int(start)
    for part in parts:
        a, b = part["window"]
        if a != cursor:
            raise ValueError("窗口 %d..%d 应当从 %d 起（中间有缝或重叠）"
                             % (a, b, cursor))
        if b < a:
            raise ValueError("窗口 %d..%d 起止颠倒" % (a, b))
        cursor = b + 1
    if cursor != int(end) + 1:
        raise ValueError("窗口只铺到 %d，要求铺到 %d" % (cursor - 1, end))
    return True


def build_rows(rows, hold_from, ratio, eps=EPS_DEFAULT, anim_from=None,
               rule_kind="post_hoc"):
    """按一条比例规则切保持段，返回 (动画段行, 保持段行, 切分两行)。"""
    frame_min = min(int(r["frame"]) for r in rows)
    frame_max = max(int(r["frame"]) for r in rows)
    hold_from = int(hold_from)
    if anim_from is None:
        anim_from = frame_min
    anim_from = int(anim_from)
    if not frame_min <= anim_from < hold_from <= frame_max:
        raise ValueError("hold_from=%d 不在 %d..%d 内（或动画段为空）"
                         % (hold_from, frame_min, frame_max))
    hold_frames = frame_max - hold_from + 1
    k = transition_length(hold_frames, ratio)
    cut = hold_from + k - 1

    anim = window_stats(rows, anim_from, hold_from - 1, eps)
    hold = window_stats(rows, hold_from, frame_max, eps)
    head = window_stats(rows, hold_from, cut, eps)
    tail = window_stats(rows, cut + 1, frame_max, eps)
    assert_partition([anim, hold], anim_from, frame_max)
    assert_partition([head, tail], hold_from, frame_max)
    return {
        "rule": {"rule_kind": rule_kind, "hold_from": hold_from,
                 "ratio": float(ratio), "hold_frames": hold_frames,
                 "transition_frames": k},
        "anim": anim, "hold": hold, "transition": head, "steady": tail,
    }


def boundary_frames(rows, hold_from, frames, eps=EPS_DEFAULT, ratio=None):
    """「边界由哪几帧决定」—— 比例只是代理，真正的分界是这几帧进不进瞬态窗口。

    对每个候选帧给出：它的深度、把它纳入瞬态窗口所需的帧数 `k = frame-hold_from+1`、
    物理口径的占段比 `k/hold_frames`、以及**可操作阈值**：`round(hold_frames*r) >= k`
    等价于 `r >= (k-0.5)/hold_frames`，这是「比例调到多少才会翻」的那个数。
    """
    frame_max = max(int(r["frame"]) for r in rows)
    hold_frames = frame_max - int(hold_from) + 1
    k_at_ratio = None if ratio is None else int(round(hold_frames * float(ratio)))
    out = []
    for f in frames:
        f = int(f)
        rec = [r for r in rows if int(r["frame"]) == f]
        if not rec:
            raise ValueError("帧 %d 不在读数里" % f)
        k = f - int(hold_from) + 1
        if not 1 <= k <= hold_frames:
            raise ValueError("帧 %d 不在保持段 %d..%d 内" % (f, hold_from, frame_max))
        out.append({
            "frame": f,
            "depth_mm": round(float(rec[0]["max_depth_m"]) * 1000.0, 3),
            "over_eps": float(rec[0]["max_depth_m"]) < -eps,
            "frames_needed": k,
            "hold_fraction": k / float(hold_frames),
            "round_threshold": (k - 0.5) / float(hold_frames),
            "covered_at_ratio": None if k_at_ratio is None else bool(k_at_ratio >= k),
        })
    return out


def smallest_covering_ratio(boundaries, hold_frames):
    """能让所有候选帧都落进瞬态窗口的最小比例（可操作口径）与其物理口径。"""
    if not boundaries:
        return None
    need = max(b["frames_needed"] for b in boundaries)
    return {"frames_needed": need,
            "hold_fraction": need / float(hold_frames),
            "round_threshold": (need - 0.5) / float(hold_frames)}


def sensitivity(rows, hold_from, ratios, eps=EPS_DEFAULT, boundary=None):
    """换比例，看切分结论稳不稳 —— 这条才是「边框可复现」的检验。"""
    boundary = [int(f) for f in (boundary or [])]
    out = []
    for ratio in ratios:
        block = build_rows(rows, hold_from, ratio, eps)
        a, b = block["transition"]["window"]
        out.append({
            "ratio": float(ratio),
            "transition_window": block["transition"]["window"],
            "transition_over": block["transition"]["over_eps"],
            "transition_deepest_mm": block["transition"]["deepest_mm"],
            "transition_deepest_frame": block["transition"]["deepest_frame"],
            "steady_window": block["steady"]["window"],
            "steady_over": block["steady"]["over_eps"],
            "steady_deepest_mm": block["steady"]["deepest_mm"],
            "steady_deepest_frame": block["steady"]["deepest_frame"],
            "covers": {str(f): bool(a <= f <= b) for f in boundary},
        })
    return out


def render(block):
    ratio = block["rule"]["ratio"]
    k = block["rule"]["transition_frames"]
    labels = [
        ("动画段 %d..%d" % tuple(block["anim"]["window"]), block["anim"], ""),
        ("保持段 %d..%d" % tuple(block["hold"]["window"]), block["hold"], ""),
        ("交接瞬态 %d..%d（保持段前 %d 帧 = %.0f%%）"
         % (block["transition"]["window"][0], block["transition"]["window"][1],
            k, ratio * 100.0), block["transition"], "|- "),
        ("稳态保持 %d..%d"
         % (block["steady"]["window"][0], block["steady"]["window"][1]),
         block["steady"], "`- "),
    ]
    lines = ["| 窗口 | 帧数 | 越判据帧 | 中位 | 均值 | 逐帧标准差 | 最深 |",
             "|---|---|---|---|---|---|---|"]
    for label, w, mark in labels:
        lines.append("| %s%s | %d | %s | %.3f mm | %.3f mm | %.3f mm | %.3f mm @f%d |"
                     % (mark, label, w["frames"], w["over_eps"],
                        w["median_mm"], w["mean_mm"], w["sd_mm"],
                        w["deepest_mm"], w["deepest_frame"]))
    return "\n".join(lines)


def _find_repo_root(start):
    """自定位：往上走到同时有 `coordination/` 与 `mmdpipe/` 的那一层（实现在 `m04_paths`）。"""
    return _paths.find_repo_root(start)


def _check_root(root):
    """验根：两个目录都得在，否则**打印那个根**再退出（不是抛 `ImportError`）。"""
    return _paths.check_root(root)


def _ensure_repo_root_on_path():
    """`python path/to/script.py` 时 `sys.path[0]` 是**脚本目录**、不是仓库根 —— 直接
    `import coordination` 会失败，而失败在这里表现为「沉默地没接上」（今晚的老形状）。
    所以先自定位、再验根、再插进 `sys.path`（`m04_paths` 里一份实现，不各写一遍）。"""
    import os
    root = _paths.ensure_on_path(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    return root


def _window_rules():
    """窗口规则闭集由 `coordination.comparability` 定义，不在这里另立一套。"""
    try:
        _ensure_repo_root_on_path()
        from coordination.comparability import WINDOW_RULES
        return tuple(WINDOW_RULES)
    except Exception:
        return ("preregistered", "segment_ratio", "post_hoc")


def _delegated_stability(rows, rule, sens, eps=EPS_DEFAULT):
    """「对切点稳健」这句话交给 `comparability.cut_sensitivity()` 算，不由本脚本嘴说。

    本脚本的 `--sensitivity` 只描述「换比例各给什么数」；判词（`STABLE` /
    `CONCLUSION_STABLE_NUMBER_UNSTABLE` / `UNSTABLE`）与「哪几帧在动」由 `总控` 的
    闭包给。它落地后，这里就是薄包装 —— 同一件事在两处各写一遍正是今天反复付代价的形状。
    """
    try:
        _ensure_repo_root_on_path()
        from coordination.comparability import cut_sensitivity, ratio_cuts
    except Exception:
        return None
    start = rule["hold_from"]
    end = start + rule["hold_frames"] - 1
    ratios = [s["ratio"] for s in sens]
    cuts = ratio_cuts(start, end, ratios)
    out = cut_sensitivity(rows, cuts, start, end, eps=eps)
    out["ratios"] = ratios
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--meta", required=True, help="meta json（含 per_frame）")
    ap.add_argument("--hold-from", type=int, required=True, help="保持段起始帧")
    ap.add_argument("--anim-from", type=int, default=None, help="动画段起始帧（默认取第一帧）")
    ap.add_argument("--ratio", type=float, action="append", default=None,
                    help="比例规则，可重复（例如 0.10 与 0.50）")
    ap.add_argument("--sensitivity", default=None,
                    help="逗号分隔的一组比例，用来验「换切点结论还成不成立」")
    ap.add_argument("--boundary-frames", default=None,
                    help="逗号分隔的帧号：这些帧进不进瞬态窗口，决定了比例下限在哪")
    ap.add_argument("--eps", type=float, default=EPS_DEFAULT, help="判据 ε（米）")
    ap.add_argument("--rule-kind", default="post_hoc",
                    help="窗口规则分类：preregistered / segment_ratio / post_hoc"
                         "（默认 post_hoc —— 危险的默认值往保守那边放，`D-224`）")
    ap.add_argument("--json", action="store_true", help="输出 json 而不是 markdown")
    args = ap.parse_args(argv)
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")

    ratios = args.ratio or [0.10]
    bframes = ([int(x) for x in args.boundary_frames.split(",") if x.strip()]
               if args.boundary_frames else [])
    try:
        rules_ok = _window_rules()
        if args.rule_kind not in rules_ok:
            raise ValueError("rule_kind %r 不在闭集 %r 内" % (args.rule_kind, list(rules_ok)))
        rows = load_frames(args.meta)
        blocks = [build_rows(rows, args.hold_from, r, args.eps, args.anim_from,
                             rule_kind=args.rule_kind)
                  for r in ratios]
        bounds = boundary_frames(rows, args.hold_from, bframes, args.eps)
        need = smallest_covering_ratio(bounds,
                                       blocks[0]["rule"]["hold_frames"])
        sens = (sensitivity(rows, args.hold_from,
                            [float(x) for x in args.sensitivity.split(",") if x.strip()],
                            args.eps, bframes)
                if args.sensitivity else [])
        delegated = _delegated_stability(
            rows, blocks[0]["rule"], sens, args.eps) if sens else None
    except ValueError as exc:
        sys.stderr.write("REFUSED: %s\n" % exc)
        return 2

    if args.json:
        print(json.dumps({"meta": args.meta, "eps": args.eps,
                          "blocks": blocks, "boundary": bounds,
                          "smallest_covering_ratio": need, "sensitivity": sens,
                          "comparability": delegated},
                         ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    for block in blocks:
        rule = block["rule"]
        tag = ("（`post_hoc`：事后窗口，只能作解释、不许作判据 —— `D-224`）"
               if rule["rule_kind"] == "post_hoc" else
               "（`%s`）" % rule["rule_kind"])
        print("窗口规则：%s%s —— 保持段 %d..%d 共 %d 帧，取前 %.0f%% = %d 帧作交接瞬态"
              % (rule["rule_kind"], tag, rule["hold_from"],
                 rule["hold_from"] + rule["hold_frames"] - 1,
                 rule["hold_frames"], rule["ratio"] * 100.0,
                 rule["transition_frames"]))
        print(render(block))
        print("")
    if bounds:
        print("边界由哪几帧决定（比例只是代理，这几帧进不进瞬态窗口才是分界）：")
        print("| 帧 | 深度 | 需覆盖帧数 k | 占段长 k/N | round() 阈值 (k−0.5)/N | 落在哪个窗口（本期比例） |")
        print("|---|---|---|---|---|---|")
        a, b = blocks[0]["transition"]["window"]
        for bd in bounds:
            print("| f%d | %.3f mm | %d | %.2f%% | %.2f%% | %s |"
                  % (bd["frame"], bd["depth_mm"], bd["frames_needed"],
                     bd["hold_fraction"] * 100.0, bd["round_threshold"] * 100.0,
                     "交接瞬态" if a <= bd["frame"] <= b else "稳态保持"))
        if need:
            print("⇒ 让这几帧全部落进瞬态窗口的最小比例：物理口径 %.2f%%（%d 帧），"
                  "可操作口径（本次 round() 落点）%.2f%%"
                  % (need["hold_fraction"] * 100.0, need["frames_needed"],
                     need["round_threshold"] * 100.0))
        print("")
    if sens:
        print("换比例（同一条规则，只改比例）：")
        print("| 比例 | 瞬态窗口 | 瞬态越判据 | 瞬态最深 | 稳态窗口 | 稳态越判据 | 稳态最深 |")
        print("|---|---|---|---|---|---|---|")
        for s in sens:
            print("| %.0f%% | %d..%d | %d | %.3f mm @f%d | %d..%d | %d | %.3f mm @f%d |"
                  % (s["ratio"] * 100.0, s["transition_window"][0], s["transition_window"][1],
                     s["transition_over"], s["transition_deepest_mm"], s["transition_deepest_frame"],
                     s["steady_window"][0], s["steady_window"][1], s["steady_over"],
                     s["steady_deepest_mm"], s["steady_deepest_frame"]))
        if delegated:
            print("")
            print("切点敏感性判词（`coordination.comparability.cut_sensitivity()` 算的，不是本脚本说的）："
                  "`%s`" % delegated["verdict"])
            print("  两段的极值帧：%s；`over_eps` 范围 %s；`worst_frame_stable=%s`"
                  % (", ".join("f%d" % f for f in delegated["worst_frames"]),
                     delegated["over_eps_range"], delegated["worst_frame_stable"]))
            print("  §注意：上述一切仍属 `%s` —— 判词只说明这些数在切点间稳不稳，"
                  "不把它们抬成判据。" % blocks[0]["rule"]["rule_kind"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
