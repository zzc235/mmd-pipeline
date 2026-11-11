"""产物布局：中间产物与成片分开。

为什么要这一层：一次运行会掉出 20 多类文件（帧序列、scene.blend、修过的
PMX、拼接 VMD、成片、联络表、相机参数、state）。全混在同一个目录里，
以后要判断「这张 mp4 是跑通的那次，还是渲到一半失败的那次」只能翻 state。

规则写死成数据，不散落在 runner 里：

    isolated   中间产物 → <out>/work/<run_id>/      （可整目录删）
               成片     → <out>/final/<run_id>/     （只在全流程 ok 后落地）
    legacy     全部写在 <out> 根目录                （v1.2.0 及以前的行为，留给旧脚本）

`run_id` 用 `started_at` 生成，保证同一 `--out` 下多次运行互不覆盖。

纯路径与文件搬运，不 import bpy，可单测。
"""
from __future__ import annotations

import os
import re
import shutil

LAYOUTS = ("isolated", "legacy")
DEFAULT_LAYOUT = "isolated"

# 成片包里放什么：能直接交付/复现的最小集合。
# 帧序列与中间 PMX/VMD 留在 work/，它们随时可以重跑出来。
DELIVERABLES = (
    "result.mp4",
    "contact_sheet.png",
    "camera.json",
    "scene.blend",
    "pipeline_state.json",
)


def run_id(started_at: str) -> str:
    """`2026-11-11 21:07:30` → `20261111_210730`。

    取不到合法字符时退回 `run`，绝不因为时间串脏了就崩——这层不该有权失败。
    """
    digits = re.sub(r"\D", "", started_at or "")
    if len(digits) >= 14:
        return "%s_%s" % (digits[:8], digits[8:14])
    return "run"


def plan(root: str, layout: str = DEFAULT_LAYOUT, started_at: str = "") -> dict:
    """算出这次运行各产物该落在哪。"""
    if layout not in LAYOUTS:
        raise ValueError("未知布局 %r，可选 %s" % (layout, ", ".join(LAYOUTS)))
    root = os.path.abspath(root)
    rid = run_id(started_at)
    if layout == "isolated":
        work = os.path.join(root, "work", rid)
        final = os.path.join(root, "final", rid)
    else:
        work = root
        final = ""                      # legacy：没有隔离，也就没有落地一说
    return {
        "layout": layout,
        "run_id": rid,
        "root": root,
        "work": work,
        "final": final,
    }


def promote(work_dir: str, final_dir: str, names=DELIVERABLES) -> list:
    """把成片从 work 复制到 final。返回实际落地的文件名（缺失的不算错）。

    用复制不用移动：work 里留着同一份，事后要复现（改参数重渲、比对帧）
    不用再跑一遍；删 work 也不影响 final。
    """
    if not final_dir:
        return []
    landed = []
    for name in names:
        src = os.path.join(work_dir, name)
        if not os.path.isfile(src):
            continue
        os.makedirs(final_dir, exist_ok=True)
        shutil.copy2(src, os.path.join(final_dir, name))
        landed.append(name)
    return landed


def describe(paths: dict) -> str:
    """一行人类可读的落点说明，用于日志和 state。"""
    if paths["layout"] == "legacy":
        return "布局 legacy（全部在 %s）" % paths["root"]
    return "布局 isolated（中间产物 %s，成片 %s）" % (paths["work"], paths["final"] or "不落地")
