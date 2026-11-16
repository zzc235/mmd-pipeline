#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""核对 `s2_prereg_v4.md` 里的每个数是否真来自 `s2_axis_peaks.json`（不手打、不猜）。

两步：
1. **数值点检**：从 md 里抽出全部数字串（含「1 744」这种千位分组），逐个与 JSON 里的期望值比，
   容差按量级分档（rad/count 用 1e-6，deg 用 1e-3 —— md 里角度按 3 位小数写）。
2. **同句点检**：每根骨的峰值必须出现在**含该骨名的那一行**里，防止「数对了但配错了骨」。

`scanned==0` 也算失败：检查条数为 0 时不给 PASS。
"""

from __future__ import annotations

import io
import json
import os
import re
import sys

import hashlib


def sha256_of(path):
    h = hashlib.sha256()
    with io.open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

HERE = os.path.dirname(os.path.abspath(__file__))
MD = os.path.normpath(os.path.join(HERE, "..", "s2_prereg_v4.md"))
JSON = os.path.normpath(os.path.join(HERE, "..", "s2_axis_peaks.json"))
IDENT = os.path.normpath(os.path.join(HERE, "..", "s2_dump_identity.json"))


def numbers_in(text):
    """md 里的数字集合：先合并千位分组（1 744 → 1744），再抽 token。"""
    flat = re.sub(r"(?<=\d) (?=\d{3}(?!\d))", "", text)
    out = set()
    for tok in re.findall(r"-?\d+(?:\.\d+)?", flat):
        try:
            out.add(float(tok))
        except ValueError:
            continue
    return out


def norm(line):
    """把一行表格压成指纹：去掉空白、星号、竖线、反引号。"""
    return re.sub(r"[\s*|`]+", "", line)


def main():
    md = io.open(MD, encoding="utf-8").read()
    js = json.load(io.open(JSON, encoding="utf-8"))
    primary = [d for d in js["dumps"] if d["dump"] == js["primary"]][0]
    axes = primary["axes"]
    nums = numbers_in(md)
    checks = []                       # (label, value, tol, where)
    lines = [ln for ln in md.splitlines() if ln.strip()]

    def want(label, value, tol):
        checks.append((label, float(value), tol))

    want("主 dump 字节", primary["dump_bytes"], 1e-6)
    text_checks = ["主 dump sha256: " + primary["dump_sha256"]]
    for d in js["dumps"]:
        text_checks.append("dump sha256(%s): %s"
                           % (os.path.basename(os.path.dirname(d["dump"])), d["dump_sha256"]))
    text_checks.append("s2_axis_peaks.json 自身 sha256: " + sha256_of(JSON))
    want("s2_axis_peaks.json 自身字节", os.path.getsize(JSON), 1e-6)
    for axis in ("x", "y", "z"):
        a = axes[axis]
        want("轴 %s 峰值 rad" % axis, a["peak_rad"], 1e-6)
        want("轴 %s 峰值 deg" % axis, a["peak_deg"], 1e-3)
        want("轴 %s 骨数越 0.7" % axis, a["bones_over"]["peak_ge_0_7rad"], 1e-6)
        for s in a["sensitivity"]:
            want("轴 %s / %s 越限点" % (axis, s["limit_label"]), s["samples_over"], 1e-6)
        for s in a["sensitivity_own"]:
            want("轴 %s / %s 本轴限值" % (axis, s["limit_label"]), s["limit_rad"], 1e-4)
            want("轴 %s / %s 本轴越限点" % (axis, s["limit_label"]), s["samples_over"], 1e-6)

    bad = 0
    for label, value, tol in checks:
        if not any(abs(n - value) <= tol for n in nums):
            bad += 1
            print("MISSING  %-40s 期望 %r（容差 %g）在 md 里找不到" % (label, value, tol))
    for text in text_checks:
        if text.split(": ")[-1] not in md:
            bad += 1
            print("MISSING  %s" % text)

    # 同句：每骨峰值必须出现在含该骨名的那一行
    pb = sorted(axes[primary["chosen_axis"]]["per_bone_deg"].items(), key=lambda kv: -kv[1])[:6]
    for bone, deg in pb:
        cand = [ln for ln in lines if bone in ln]
        if not cand:
            bad += 1
            print("MISSING  骨 %s 在 md 里没有出现" % bone)
            continue
        if not any(any(abs(n - deg) <= 1e-3 for n in numbers_in(ln)) for ln in cand):
            bad += 1
            print("MISSING  骨 %s 名下的任何一行都没有 %.4f" % (bone, deg))

    # 整行指纹：载荷最重的两张表必须**逐行**对上（防止「数对但配错行/配错数」）
    fingerprints = []
    for axis in ("x", "y", "z"):
        a = axes[axis]
        fingerprints.append(("§1.2 轴 %s 行" % axis.upper(),
                             [axis.upper(), "%.6f" % a["peak_rad"], "%.4f" % a["peak_deg"],
                              a["bone"], "%d" % a["frame"],
                              "%d" % a["bones_over"]["peak_ge_0_7rad"]]))
    shared = {"x": {}, "y": {}, "z": {}}
    for axis in ("x", "y", "z"):
        for s in axes[axis]["sensitivity"]:
            shared[axis][s["limit_label"]] = s["samples_over"]
    for axis in ("x", "y", "z"):
        row = [axis.upper()]
        for label in ("0.5×峰值", "原 ±0.7 rad", "1.2×峰值", "现交付 ±1.5708 rad"):
            row.append("%d" % shared[axis][label])
        fingerprints.append(("§2.1 轴 %s 行" % axis.upper(), row))

    md_norm = {norm(ln) for ln in lines}
    for label, cells in fingerprints:
        if norm("| " + " | ".join(cells) + " |") not in md_norm:
            bad += 1
            print("MISSING  整行对不上：%s → | %s |" % (label, " | ".join(cells)))

    # §1.4 逐臂身份表：每行必须写出它自己的字节数与 sha16，s8 组按 sha 分组核
    ident = json.load(io.open(IDENT, encoding="utf-8"))
    row_checks = 0
    for r in ident["rows"]:
        if r["kind"] != "dyn":
            continue
        prefix = "| dyn | `%s` |" % r["arm"]
        hit = [ln for ln in lines if ln.strip().startswith(prefix)]
        row_checks += 1
        if not hit:
            bad += 1
            print("MISSING  §1.4 没有 %s 这一行" % r["arm"])
            continue
        line = norm(hit[0])
        if "%d" % r["bytes"] not in line or r["sha256"][:16] not in line:
            bad += 1
            print("MISSING  §1.4 %s 行里字节/sha 对不上（期望 %d / %s）"
                  % (r["arm"], r["bytes"], r["sha256"][:16]))
    for sha, arms in ident["identical_groups"].items():
        if not any(a.startswith("A1") for a in arms):
            continue
        row_checks += 1
        s8_line = [ln for ln in lines if ln.strip().startswith("| s8 |")
                   and sha[:16] in norm(ln)]
        if not s8_line:
            bad += 1
            print("MISSING  §1.4 s8 组没有写出 sha16=%s 的那一行" % sha[:16])

    total = len(checks) + len(pb) + len(fingerprints) + row_checks
    if total == 0:
        print("检查条数为 0：不给 PASS")
        return 2
    print("检查 %d 条（数值 %d + 同句 %d + 整行 %d + 身份行 %d），失败 %d 条"
          % (total, len(checks), len(pb), len(fingerprints), row_checks, bad))
    return 0 if bad == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
