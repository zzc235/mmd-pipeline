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

`coordination/comparability.py`（`总控` 19:34 说正在落）落地后，本脚本的「取最深值」应当
改成调它的 `extremum_report()`；现在那一条模块在工作树里还不存在，所以这里仍是本地实现，
不要假装接上了。

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
        --ratio 0.10 --ratio 0.50 --sensitivity 0.05,0.10,0.15,0.20
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from statistics import median

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
    return {
        "window": [a, b],
        "frames": n,
        "over_eps": sum(1 for v in vals if v < -eps),
        "median_mm": round(median(vals) * 1000.0, 3),
        "mean_mm": round(mean * 1000.0, 3),
        "sd_mm": round(var ** 0.5 * 1000.0, 3),
        "deepest_mm": round(float(deep["max_depth_m"]) * 1000.0, 3),
        "deepest_frame": int(deep["frame"]),
    }


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


def build_rows(rows, hold_from, ratio, eps=EPS_DEFAULT, anim_from=None):
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
        "rule": {"rule_kind": "segment_ratio", "hold_from": hold_from,
                 "ratio": float(ratio), "hold_frames": hold_frames,
                 "transition_frames": k},
        "anim": anim, "hold": hold, "transition": head, "steady": tail,
    }


def sensitivity(rows, hold_from, ratios, eps=EPS_DEFAULT):
    """换比例，看切分结论稳不稳 —— 这条才是「边框可复现」的检验。"""
    out = []
    for ratio in ratios:
        block = build_rows(rows, hold_from, ratio, eps)
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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--meta", required=True, help="meta json（含 per_frame）")
    ap.add_argument("--hold-from", type=int, required=True, help="保持段起始帧")
    ap.add_argument("--anim-from", type=int, default=None, help="动画段起始帧（默认取第一帧）")
    ap.add_argument("--ratio", type=float, action="append", default=None,
                    help="比例规则，可重复（例如 0.10 与 0.50）")
    ap.add_argument("--sensitivity", default=None,
                    help="逗号分隔的一组比例，用来验「换切点结论还成不成立」")
    ap.add_argument("--eps", type=float, default=EPS_DEFAULT, help="判据 ε（米）")
    ap.add_argument("--json", action="store_true", help="输出 json 而不是 markdown")
    args = ap.parse_args(argv)
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")

    ratios = args.ratio or [0.10]
    try:
        rows = load_frames(args.meta)
        blocks = [build_rows(rows, args.hold_from, r, args.eps, args.anim_from)
                  for r in ratios]
        sens = (sensitivity(rows, args.hold_from,
                            [float(x) for x in args.sensitivity.split(",") if x.strip()],
                            args.eps)
                if args.sensitivity else [])
    except ValueError as exc:
        sys.stderr.write("REFUSED: %s\n" % exc)
        return 2

    if args.json:
        print(json.dumps({"meta": args.meta, "eps": args.eps,
                          "blocks": blocks, "sensitivity": sens},
                         ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    for block in blocks:
        rule = block["rule"]
        print("窗口规则：%s（先于数据可判）—— 保持段 %d..%d 共 %d 帧，取前 %.0f%% = %d 帧作交接瞬态"
              % (rule["rule_kind"], rule["hold_from"],
                 rule["hold_from"] + rule["hold_frames"] - 1,
                 rule["hold_frames"], rule["ratio"] * 100.0,
                 rule["transition_frames"]))
        print(render(block))
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
