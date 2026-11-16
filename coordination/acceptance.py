# -*- coding: utf-8 -*-
"""M08 总验收的**一键判据**（纯 Python，不 import bpy）。

分工：`tests_integration/m08_accept_probe.py` 在 Blender 里**只采集事实**（刚体数、
骨数、顶点数、占位符、`stage_mask()` 输出、`cache_state` 记录、三处 sha），本模块**只判**。
两步分开的理由：判据要能在没有 Blender 的机器上复算、也要能被单测直接喂一份"应当被拒"的
事实（`tests/test_acceptance.py` 里 J_baked 那份就是）。

口径按 AGENTS.md 第一条：判「通道接没接上」不自己再算一遍，直接吃 `stage.stage_mask()`
（它内部走 `mmdpipe.mask.mask_report()`），**同一件事只有一处实现**。

退出码（也写在 `--help` 里，脚本自己 `sys.exit`，见 `D-135`）：
    0  全部 PASS
    3  有 FAIL（至少一行判据为假）
    4  CANNOT（事实缺失/读不到 —— "测不出来"不许当"通过"）
"""
from __future__ import annotations

import argparse
import json
import os
import sys

PASS = "PASS"
FAIL = "FAIL"
CANNOT = "CANNOT"

EXIT_OK = 0
EXIT_FAIL = 3
EXIT_CANNOT = 4

#: 交付场景的期望值（D0 15:10 给的清单）。**这是数据，不是逻辑**：
#: 换验收对象就换一份 expectations，不要把数字写进判断分支里。
DEFAULT_EXPECTATIONS = {
    "spec": "m08_acceptance/1",
    "scene": "delivery_v1",
    "rigids_u323": 312,
    "placeholders": 0,
    "bones": 482,
    "vertices": 25506,
    "skirt_bones_0": 18,
    "skirt_bones_11": 0,
    "mask_verdict": "WIRED",
    "constraints_capped": False,
    "skipped_count": 0,
    "blocked_and_should_collide": 0,
    "nocollide_pairs_still_colliding": 0,
    "unexpressible_pairs": 0,
    "cache_verdict_in": ["OK_UNBAKED", "OK_BAKED_CONSISTENT", "OK_BAKED_VERIFIED",
                         "OK_NO_PHYSICS"],
}

SKIRT_PREFIX = "下擺_"
PLACEHOLDER = "$"


def _row(check_id, expected, actual, status, detail=""):
    return {"id": check_id, "expected": expected, "actual": actual,
            "status": status, "detail": detail}


def _cmp(check_id, expected, actual):
    """单个数值/字符串的比较。`actual is None` ⇒ CANNOT（没测到 ≠ 不等于）。"""
    if actual is None:
        return _row(check_id, expected, None, CANNOT, "没测到")
    if actual != expected:
        return _row(check_id, expected, actual, FAIL,
                    "实际 %r != 期望 %r" % (actual, expected))
    return _row(check_id, expected, actual, PASS)


def _cmp_in(check_id, allowed, actual):
    if actual is None:
        return _row(check_id, allowed, None, CANNOT, "没测到")
    if actual not in allowed:
        return _row(check_id, allowed, actual, FAIL, "不在允许集合内")
    return _row(check_id, allowed, actual, PASS)


def judge(facts, expectations=None) -> dict:
    """把一份事实判成若干行 + 总判定 + 退出码。"""
    exp = dict(DEFAULT_EXPECTATIONS)
    if expectations:
        exp.update(expectations)
    rows = []
    if not isinstance(facts, dict):
        return {"spec": exp["spec"], "scene": exp.get("scene"),
                "rows": [_row("facts", "dict", type(facts).__name__, CANNOT, "事实不是 dict")],
                "verdict": CANNOT, "exit_code": EXIT_CANNOT}

    # 1) 文件身份：三处 sha 必须一致且非空（"读的时候没人在写"）
    reads = facts.get("sha256_reads")
    if not reads:
        rows.append(_row("blend_sha256_three_reads", 3, 0, CANNOT, "没有三次读数"))
    elif len(set(reads)) != 1 or not reads[0]:
        rows.append(_row("blend_sha256_three_reads", "三次相同", reads, FAIL,
                         "三次读数不一致 —— 验收期间有人在写这个文件"))
    else:
        rows.append(_row("blend_sha256_three_reads", "三次相同", reads[0], PASS))

    # 2) 场景构成
    rows.append(_cmp("rigids_u323", exp["rigids_u323"], facts.get("rigids_u323")))
    rows.append(_cmp("rigids_u324_equals_u323",
                     facts.get("rigids_u323"), facts.get("rigids_u324")))
    rows.append(_cmp("placeholders", exp["placeholders"], facts.get("placeholders")))
    rows.append(_cmp("bones", exp["bones"], facts.get("bones")))
    rows.append(_cmp("vertices", exp["vertices"], facts.get("vertices")))
    rows.append(_cmp("skirt_bones_0", exp["skirt_bones_0"], facts.get("skirt_bones_0")))
    rows.append(_cmp("skirt_bones_11", exp["skirt_bones_11"], facts.get("skirt_bones_11")))

    # 3) 缓存状态（判定词来自 `mmdpipe.cache_state.evaluate()`，不在这里重写）
    rows.append(_cmp_in("cache_verdict", exp["cache_verdict_in"],
                        facts.get("cache_verdict")))

    # 4) 通道：判词 + 两个归零量（`D-20261116-142`：不看约束总数）
    mask = facts.get("mask") or {}
    rows.append(_cmp("mask_verdict", exp["mask_verdict"], mask.get("verdict")))
    rows.append(_cmp("constraints_capped", exp["constraints_capped"],
                     mask.get("constraints_capped")))
    rows.append(_cmp("skipped_count", exp["skipped_count"], mask.get("skipped_count")))
    rows.append(_cmp("blocked_and_should_collide", exp["blocked_and_should_collide"],
                     mask.get("blocked_and_should_collide")))
    rows.append(_cmp("nocollide_pairs_still_colliding",
                     exp["nocollide_pairs_still_colliding"],
                     mask.get("nocollide_pairs_still_colliding")))
    rows.append(_cmp("unexpressible_pairs", exp["unexpressible_pairs"],
                     mask.get("unexpressible_pairs")))

    # 5) 采集器自己的错误（读不到东西时它会写进来）
    errors = facts.get("errors") or []
    rows.append(_row("collector_errors", [], errors, FAIL if errors else PASS,
                     "采集器报了错误" if errors else ""))

    statuses = {row["status"] for row in rows}
    if FAIL in statuses:
        verdict, code = FAIL, EXIT_FAIL
    elif CANNOT in statuses:
        verdict, code = CANNOT, EXIT_CANNOT
    else:
        verdict, code = PASS, EXIT_OK
    return {"spec": exp["spec"], "scene": exp.get("scene"), "rows": rows,
            "verdict": verdict, "exit_code": code}


def render(report, facts=None) -> str:
    """人读的一张表（写进 `accept_<sha8>.txt`）。"""
    lines = ["M08 验收 · %s · %s" % (report.get("scene"), report["spec"]),
             "总判定：%s（exit %d）" % (report["verdict"], report["exit_code"]), ""]
    width = max([len(row["id"]) for row in report["rows"]] + [4])
    for row in report["rows"]:
        lines.append("%-*s  %-6s  期望 %-22r 实际 %r%s"
                     % (width, row["id"], row["status"], row["expected"],
                        row["actual"], ("  ← " + row["detail"]) if row["detail"] else ""))
    if facts:
        prov = facts.get("provenance") or {}
        lines.append("")
        lines.append("采集器：blender=%s" % (prov.get("blender"),))
        for name in ("mmdpipe.stage", "mmdpipe.mask"):
            item = prov.get(name) or {}
            lines.append("  %s  %s  sha256=%s" % (name, item.get("file"),
                                                  (item.get("sha256") or "")[:16]))
    return "\n".join(lines) + "\n"


def fatal(message):
    """致命错误 → 非零退出（`D-135`：不许被上层吞成 0）。"""
    sys.stderr.write("ACCEPT_ERROR %s\n" % message)
    return EXIT_CANNOT


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="python -m coordination.acceptance",
        description="M08 总验收：吃采集器的事实 JSON，逐行判 PASS/FAIL/CANNOT。",
        epilog="退出码：0 全部 PASS / 3 有 FAIL / 4 CANNOT（事实缺失或读不到）。",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--facts", required=True, help="采集器打印的 FACTS_JSON 文件")
    ap.add_argument("--expect", default=None, help="期望值 JSON（默认用内置交付期望）")
    ap.add_argument("--out-dir", default=None,
                    help="产物目录（默认 reports/subai/M08）")
    args = ap.parse_args(argv)

    try:
        with open(args.facts, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        return fatal("读不到 facts：%s" % exc)

    payload = text.strip()
    marker = "FACTS_JSON "
    if marker in payload:                     # 允许直接喂 Blender 的原始日志
        payload = payload[payload.index(marker) + len(marker):].strip()
        payload = payload.splitlines()[0]
    try:
        facts = json.loads(payload)
    except ValueError as exc:
        return fatal("facts 不是合法 JSON：%s" % exc)

    expectations = None
    if args.expect:
        try:
            with open(args.expect, "r", encoding="utf-8") as fh:
                expectations = json.load(fh)
        except (OSError, ValueError) as exc:
            return fatal("读不到 expectations：%s" % exc)

    report = judge(facts, expectations)
    reads = facts.get("sha256_reads") or [""]
    digest = (reads[0] or "nosh")[:8]
    out_dir = args.out_dir or os.path.join("reports", "subai", "M08")
    body = render(report, facts)
    sys.stdout.write(body)
    try:
        os.makedirs(out_dir, exist_ok=True)
        base = os.path.join(out_dir, "accept_%s" % digest)
        with open(base + ".txt", "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
        with open(base + ".json", "w", encoding="utf-8", newline="\n") as fh:
            json.dump(dict(report, blend_sha256=reads[0],
                           facts_summary={k: facts.get(k) for k in
                                          ("rigids_u323", "rigids_u324", "bones",
                                           "vertices", "placeholders")}),
                      fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        sys.stdout.write("\n产物：%s.txt / %s.json\n" % (base, base))
    except OSError as exc:
        return fatal("写不出产物：%s" % exc)
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
