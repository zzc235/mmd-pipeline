#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""M04 四组比对器（纯 Python，不开 Blender，不重算任何深度）。

用途：读 `m04_capsule_probe.py` 产出的 meta JSON（每帧一个最坏对 + 计数），
按预注册 `m04_remeasure_prereg_v2.md` §七 给判词。

**本脚本存在的首要理由是"符号"**：探针的 `max_depth_m = -max(0, depth - baseline)`，
负值 = 新增重叠。判据式 `max(0, depth-baseline) > epsilon` 与判词 `max_depth_m < -epsilon`
看起来反号，其实是同一个式子。把它当成"正 = 更深"去数，输出正是
`frames_over_epsilon = 0`——今天最让人放心的那个数。所以 `--selftest` 是门，不是建议。

退出码：0 = 全部可比且无结论级变化 / 1 = 至少一处结论级变化 / 2 = 用法错
       3 = 有组不可判（UNKNOWN）/ 4 = 自检失败（此时任何引用都作废）
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys

sys.stdout.reconfigure(encoding="utf-8")

EPSILON_M = 0.020   # 判据，不随档位改（thresholds.md, profile pg/0.1-exploratory）


# ---------------------------------------------------------------- 计数与判词

def frames_over_epsilon(per_frame, epsilon=EPSILON_M):
    """越判据帧数。max_depth_m 是**带符号增量**（负值=新增重叠），故用 `< -epsilon`。

    严格小于：恰好等于 -epsilon 不算越（边界控制见 selftest）。
    """
    return sum(1 for r in per_frame if float(r["max_depth_m"]) < -abs(epsilon))


def wrong_sign_count(per_frame, epsilon=EPSILON_M):
    """**故意写错的约定**（正 = 更深）。只在 selftest 里用，用来证明计数方向不是随便写的。"""
    return sum(1 for r in per_frame if float(r["max_depth_m"]) > +abs(epsilon))


def summarize(name, meta, epsilon=EPSILON_M):
    per_frame = meta.get("per_frame") or []
    rows = {
        "group": name,
        "frames_in_meta": meta.get("frames_measured"),
        "frames_read": len(per_frame),
        "frames_over_epsilon": frames_over_epsilon(per_frame, epsilon),
        "epsilon_m": abs(epsilon),
        "pairs_without_baseline": sum(int(r.get("pairs_without_baseline") or 0) for r in per_frame),
        "overlapping_pairs_median": (statistics.median([int(r.get("overlapping_pairs") or 0)
                                                        for r in per_frame]) if per_frame else None),
        "overlapping_pairs_all_zero": all(int(r.get("overlapping_pairs") or 0) == 0 for r in per_frame),
        "baseline_sha256": meta.get("baseline_sha256"),
        "baseline_source": meta.get("baseline_source"),
        "mask_state": (meta.get("mask_state") if "mask_state" in meta
                       else (meta.get("provenance") or {}).get("mask_state")),
        "vmd_sha256": (meta.get("vmd_sha256") if "vmd_sha256" in meta
                       else (meta.get("provenance") or {}).get("vmd_sha256")),
        "blend": meta.get("blend"),
        "window": meta.get("frames"),
        "eval_policy": meta.get("eval_policy"),
    }
    deepest = min(per_frame, key=lambda r: float(r["max_depth_m"])) if per_frame else None
    rows["deepest_frame"] = deepest.get("frame") if deepest else None
    rows["deepest_max_depth_m"] = deepest.get("max_depth_m") if deepest else None
    rows["deepest_bone"] = deepest.get("bone") if deepest else None
    rows["deepest_bone_other"] = deepest.get("bone_other") if deepest else None
    rows["raw_depth_m_at_deepest"] = deepest.get("raw_depth_m") if deepest else None

    # 可判性：两条正控之一不过，本组一律 UNKNOWN（预注册 §七）
    reasons = []
    if not per_frame:
        reasons.append("per_frame 为空（没有取到任何一帧）")
    if rows["frames_in_meta"] is not None and rows["frames_in_meta"] != rows["frames_read"]:
        reasons.append("frames_measured=%s 与 per_frame 行数=%d 不一致"
                       % (rows["frames_in_meta"], rows["frames_read"]))
    if rows["pairs_without_baseline"] > 0:
        reasons.append("pairs_without_baseline=%d（缺基线的对不许默认 0）" % rows["pairs_without_baseline"])
    if rows["overlapping_pairs_all_zero"]:
        reasons.append("overlapping_pairs 每帧都是 0（没算到任何重叠，那个「没变化」是空集给的）")
    rows["unknown_reasons"] = reasons
    rows["judgeable"] = not reasons
    _hit("judgeable" if not reasons else "unjudgeable")
    return rows


BRANCH_HITS = {}


def _hit(name):
    """分支计数。用途：证明「那段代码真的被走到过」——
    一个分支一次没走，六条行为断言照样可以全绿（1号 2026-11-16 的教训）。
    计数本身不参与任何判断，所以它只能靠「静音它」的变异体来证明自己有牙。"""
    BRANCH_HITS[name] = BRANCH_HITS.get(name, 0) + 1


def verdict(a, b, same_action=False):
    """两组的判词。0/非0 变化 = 结论级变化；否则数值变化结论不变。"""
    if not (a["judgeable"] and b["judgeable"]):
        _hit("verdict_unknown")
        return ("UNKNOWN", "有一组不可判：%s / %s"
                % (";".join(a["unknown_reasons"]) or "ok", ";".join(b["unknown_reasons"]) or "ok"))
    za, zb = a["frames_over_epsilon"] == 0, b["frames_over_epsilon"] == 0
    if za != zb:
        _hit("verdict_flip")
        return ("结论级变化", "%s 的 frames_over_epsilon=%d，%s 的=%d（一边 0 一边非 0）"
                % (a["group"], a["frames_over_epsilon"], b["group"], b["frames_over_epsilon"]))
    _hit("verdict_same")
    note = "两组都是 %s" % ("0（未越判据）" if za else "非 0（越判据）")
    if same_action:
        _hit("verdict_same_action_numeric")
        da, db = a["deepest_max_depth_m"], b["deepest_max_depth_m"]
        note += "；同一动作故可比数值：deepest %.6f vs %.6f（Δ=%.6f m）" % (da, db, abs(da - db))
    else:
        _hit("verdict_same_action_false")
        note += "；**增量不同源（各自相对自己窗口首帧的基线），不比数值差**"
    return ("数值变化、结论不变", note)


# ---------------------------------------------------------------- 自检（门）

def _mk(frames):
    return [{"frame": f, "max_depth_m": d, "overlapping_pairs": 1, "pairs_without_baseline": 0,
             "bone": "下擺_0_0", "bone_other": "下半身", "raw_depth_m": d} for f, d in frames]


def selftest():
    ok = True
    BRANCH_HITS.clear()          # 分支计数按次清零，避免上一次的残值把覆盖度灌满

    def chk(title, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print("  [%s] %-42s got=%r want=%r" % ("PASS" if good else "FAIL", title, got, want))

    print("[selftest] 计数规则三条控制（预注册 §七）")
    two = _mk([(1, -0.031), (2, -0.001)])
    chk("正控：一帧越判据、一帧不越 → 1", frames_over_epsilon(two), 1)
    chk("负控·符号写反（正=更深）→ 0，证明方向不是随便写的", wrong_sign_count(two), 0)
    chk("负控·边界：恰好等于 -epsilon 不算越", frames_over_epsilon(_mk([(1, -0.020)])), 0)
    chk("负控·再深一点就计上（-0.0201）", frames_over_epsilon(_mk([(1, -0.0201)])), 1)

    print("[selftest] 可判性正控（空集与缺基线必须不可判）")
    chk("空 per_frame 不可判", summarize("empty", {"per_frame": []})["judgeable"], False)
    no_base = _mk([(1, -0.031)])
    no_base[0]["pairs_without_baseline"] = 3
    chk("缺基线 >0 不可判", summarize("nobase", {"per_frame": no_base})["judgeable"], False)
    zero = _mk([(1, 0.0)])
    zero[0]["overlapping_pairs"] = 0
    chk("overlapping_pairs 全 0 不可判", summarize("zeroovl", {"per_frame": zero})["judgeable"], False)
    meta_bad = {"frames_measured": 240, "per_frame": _mk([(1, -0.031)])}
    chk("frames_measured 与行数不符不可判", summarize("short", meta_bad)["judgeable"], False)

    print("[selftest] 判词正控")
    a = summarize("A", {"frames_measured": 2, "per_frame": _mk([(1, -0.001), (2, -0.002)])})
    b = summarize("B", {"frames_measured": 2, "per_frame": _mk([(1, -0.031), (2, -0.002)])})
    chk("0 → 非0 判结论级变化", verdict(a, b)[0], "结论级变化")
    chk("两组都 0 判结论不变", verdict(a, summarize("C", {"frames_measured": 1,
                                                        "per_frame": _mk([(1, -0.003)])}))[0],
        "数值变化、结论不变")
    # 这条原来**从来没有被跑过**——1号 的分支计数提醒查出来的
    bad = summarize("BAD", {"frames_measured": 1, "per_frame": []})
    chk("有一组不可判 → 判 UNKNOWN（原来没测过这条分支）", verdict(a, bad)[0], "UNKNOWN")
    chk("同动作才比数值差", "Δ=" in verdict(a, summarize("D", {"frames_measured": 1,
                                                              "per_frame": _mk([(1, -0.002)])}),
                                          same_action=True)[1], True)
    chk("跨动作不比数值差", "不比数值差" in verdict(a, summarize("E", {"frames_measured": 1,
                                                                    "per_frame": _mk([(1, -0.002)])}))[1], True)

    print("[selftest] 分支覆盖（每个分支至少走到一次，否则断言全绿也说明不了它被走过）")
    need = ["judgeable", "unjudgeable", "verdict_unknown", "verdict_flip", "verdict_same",
            "verdict_same_action_numeric", "verdict_same_action_false"]
    missing = [k for k in need if BRANCH_HITS.get(k, 0) < 1]
    chk("七个分支都被走到过（缺：%s）" % (missing or "无"), missing, [])
    print("  branch_hits=%s" % dict(sorted(BRANCH_HITS.items())))

    print("\n[selftest] %s" % ("全部通过" if ok else "有失败——四组的 frames_over_epsilon 一律不许引用"))
    return 0 if ok else 4



MUTANTS = [
    # (名字, 追加到文件末尾之前的代码, 期望退出码)
    ("符号写反（正=更深）",
     'def frames_over_epsilon(per_frame, epsilon=EPSILON_M):\n'
     '    return sum(1 for r in per_frame if float(r["max_depth_m"]) > +abs(epsilon))\n', 4),
    ("边界 <= 而非 <",
     'def frames_over_epsilon(per_frame, epsilon=EPSILON_M):\n'
     '    return sum(1 for r in per_frame if float(r["max_depth_m"]) <= -abs(epsilon))\n', 4),
    ("等价替换（反探测，应仍绿）",
     '_orig_foe = frames_over_epsilon\n'
     'def frames_over_epsilon(per_frame, epsilon=EPSILON_M):\n'
     '    return _orig_foe(per_frame, epsilon)\n', 0),
    # 行为完全不变，只把分支计数静音 ⇒ 六条行为断言照样全绿，只有分支覆盖抓得住（1号 2026-11-16）
    ("分支计数被静音（行为不变）",
     '_hit = lambda *a, **k: None\n', 4),
]


def _run_mutant(head, tail, marker, code, want, src_sha, expect_ok=True):
    """跑一个变异体：写临时副本 → 子进程跑 → 比退出码。返回 (判定, 详情)。"""
    import hashlib
    import os
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "mutant.py")
        text = head + code + "\n\n" + marker + tail
        open(p, "w", encoding="utf-8", newline="\n").write(text)
        mut_sha = hashlib.sha256(open(p, "rb").read()).hexdigest()
        differs = mut_sha != src_sha
        r = subprocess.run([sys.executable, p, "--selftest"], capture_output=True,
                           encoding="utf-8", errors="replace", timeout=180)
        fails = (r.stdout or "").count("[FAIL]")
        got_red = (r.returncode != want)      # 检测器是否判它不合期望
        ok = (got_red == (not expect_ok)) and differs
        detail = {"rc": r.returncode, "want": want, "differs": differs, "fails": fails,
                  "tail": (r.stdout or "").strip().splitlines()[-3:]}
        return ok, detail


def mutation_test(source_path):
    """变异测试：把实现改坏写进**磁盘上的临时副本**，用**子进程**跑它，看退出码。

    为什么不在一进程里 monkeypatch（2026-11-16 的教训，1号 实测）：
    本脚本前一版用「`sha256(__file__) == sha256(传进来的文件)`」当身份检查，
    但**两边的值都由本脚本自己决定**——若上层桩忽略参数、把同一个路径既当参数又当加载目标，
    两边当然相等，检查照样通过。**单进程内的路径检查是循环论证。**

    所以改成：变异体写到磁盘 → `subprocess` 起新解释器跑那个文件 →
    **谁被加载由操作系统按我们给的路径决定，不由我们的变量决定**。

    四条对照（总控 `D-20261116-128`：全部留在 artifact 里，不只留在消息里）：
      ① 未变异体作对照（必须绿，否则后面的红分不清来源）
      ② 变异体必须红（符号写反、边界 `<=`）
      ③ 等价替换必须仍绿（证明**不敏感于无关改动**——只证明「敏感」是不够的）
      ④ **负控：变异体为空却期望红**（证明检测器真的会判负，而不是所有变异体恰好都过）
    """
    import hashlib
    import os
    import subprocess
    import tempfile

    def sha(b):
        return hashlib.sha256(b).hexdigest()

    src = open(source_path, encoding="utf-8").read()
    src_sha = sha(src.encode("utf-8"))
    # 标记用拼接构造：否则本行自身就会在源码里制造第二处出现
    marker = "if __name__" + ' == "__main__":'
    if marker not in src:
        print("[mutation] FAIL 找不到 __main__ 标记，无法安全插入变异体")
        return 4
    head, _, tail = src.rpartition(marker)   # 取最后一处

    print("[mutation] source: %s" % source_path)
    print("[mutation] source_sha256=%s" % src_sha[:16])

    checks = []
    # 先跑未变异体作对照：它必须绿，否则后面的红分不清是变异造成的还是本来就红
    with tempfile.TemporaryDirectory() as d:
        ctrl = os.path.join(d, "control.py")
        open(ctrl, "w", encoding="utf-8", newline="\n").write(src)
        r = subprocess.run([sys.executable, ctrl, "--selftest"], capture_output=True,
                           encoding="utf-8", errors="replace", timeout=180)
        ok = r.returncode == 0
        checks.append(ok)
        print("[mutation] %-24s rc=%d(期望0) 副本sha=%s → %s"
              % ("对照·未变异", r.returncode, sha(open(ctrl, "rb").read())[:16],
                 "PASS" if ok else "FAIL"))

    for name, code, want in MUTANTS:
        ok, d = _run_mutant(head, tail, marker, code, want, src_sha)
        checks.append(ok)
        print("[mutation] %-24s rc=%d(期望%d) 副本与原文件不同=%s FAIL行=%d → %s"
              % (name, d["rc"], want, d["differs"], d["fails"], "PASS" if ok else "FAIL"))
        if not ok:
            for line in d["tail"]:
                print("             | %s" % line)

    # ④ 负控（总控 `D-20261116-128` 要求的形状，必须留在 artifact 里）：
    #    变异体为空 = 「改了但没生效」，期望 rc=4 —— 检测器**必须判它 FAIL**。
    #    只留「改坏会红」的话，红起来也不知道该信谁：
    #    这一条证明检测器真的会判负，而不是所有变异体恰好都过。
    ok, d = _run_mutant(head, tail, marker, "", 4, src_sha, expect_ok=False)
    checks.append(ok)
    print("[mutation] %-24s rc=%d(期望4) 副本与原文件不同=%s → 检测器判负=%s ⇒ %s"
          % ("④ 负控·变异体为空", d["rc"], d["differs"], d["rc"] != 4,
             "PASS（真的会判负）" if ok else "FAIL（对无效变异体放行了）"))

    ok = all(checks)
    print("\n[mutation] %s（%d/%d）" % ("全部通过" if ok else "有失败，本次自检不算验过",
                                       sum(1 for c in checks if c), len(checks)))
    return 0 if ok else 4


# ---------------------------------------------------------------- 主流程

def _load(spec):
    """spec = NAME=path"""
    name, _, path = spec.partition("=")
    if not path:
        raise SystemExit("[compare] --meta 需要 NAME=path 形式：%r" % spec)
    with open(path, "r", encoding="utf-8") as fh:
        meta = json.load(fh)
    return name, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", action="append", default=[], help="NAME=path（探针的 --meta 产物）")
    ap.add_argument("--pairs", action="append", default=[],
                    help="NAME1:NAME2[:same-action]（:same-action 才比数值差）")
    ap.add_argument("--eps", type=float, default=EPSILON_M)
    ap.add_argument("--json", default="", help="把汇总写到这个 JSON")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--mutation-test", action="store_true",
                    help="变异测试：把实现改坏，证明自检会红（含身份检查与调用计数）")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if a.mutation_test:
        return mutation_test(__file__)
    if not a.meta:
        ap.print_help()
        return 2

    groups = {}
    for spec in a.meta:
        name, meta = _load(spec)
        groups[name] = summarize(name, meta, a.eps)
        g = groups[name]
        print("[%s] frames=%d over_eps=%d deepest=f%s %.6f (%s↔%s) ovl_median=%s base=%s policy=%s"
              % (name, g["frames_read"], g["frames_over_epsilon"], g["deepest_frame"],
                 g["deepest_max_depth_m"] or 0.0, g["deepest_bone"], g["deepest_bone_other"],
                 g["overlapping_pairs_median"], (g["baseline_sha256"] or "-")[:16], g["eval_policy"]))
        print("      raw@deepest=%s  pairs_without_baseline=%d  judgeable=%s %s"
              % (g["raw_depth_m_at_deepest"], g["pairs_without_baseline"], g["judgeable"],
                 ("reasons=" + ";".join(g["unknown_reasons"])) if g["unknown_reasons"] else ""))

    rc = 0
    for spec in a.pairs:
        parts = spec.split(":")
        if len(parts) < 2:
            raise SystemExit("[compare] --pairs 需要 NAME1:NAME2：%r" % spec)
        same_action = len(parts) > 2 and parts[2] == "same-action"
        x, y = parts[0], parts[1]
        if x not in groups or y not in groups:
            raise SystemExit("[compare] 组名未提供：%s / %s" % (x, y))
        v, why = verdict(groups[x], groups[y], same_action)
        print("\n%s vs %s → %s\n   %s" % (x, y, v, why))
        if v == "结论级变化":
            rc = 1
        elif v == "UNKNOWN":
            rc = max(rc, 3)

    bad = [g for g in groups.values() if not g["judgeable"]]
    if bad and rc == 0:
        rc = 3

    if a.json:
        with open(a.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"epsilon_m": abs(a.eps), "groups": groups,
                       "note": "max_depth_m = -max(0, depth-baseline)，负值=新增重叠；"
                               "判词只用 frames_over_epsilon，raw_depth_m 只作量级描述。"},
                      fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        print("\n[compare] written %s" % a.json)
    return rc


if __name__ == "__main__":
    sys.exit(main())
