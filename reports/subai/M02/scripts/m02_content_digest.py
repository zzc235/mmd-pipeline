#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""`content_digest_v1`：把「交付件的内容」压成一个可复核、可跨次比较的摘要（纯 Python）。

为什么要有这个东西（总控 18:08 §一）：`.blend` **不是逐字节可复现的**——同一输入连跑三次，
字节 5 929 823 / 5 928 599 / 5 923 244 各不同，而回读内容一致。于是「交付件能由代码重建」
这句话只能定义在**内容**上；但「内容相同」若不说清剥掉了什么，任何两份文件都会「相同」，
判据就变成恒绿。本脚本与 `content_digest_v1.md` 一起负责把这句话说死。

## 规格（v1，改版本要写为什么）

**摘要的输入**是一份 facts JSON（`m02_m08_readback.py` / `rebuild_report.json` 派生），
本脚本只认下面这些字段，**其余一律不参与**。

参与（included）：

| 键 | 说明 |
|---|---|
| `rigids` | 刚体总数（含非 PMX 的地面/占位体） |
| `bodies[]` | 逐刚体：`name` / `parent_bone` / `mass` / `kinematic` / `collision_shape` / `collision_collections` / `friction`；按 `name` 排序后取 |
| `constraints_by_type` | 约束类型 → 条数（键排序） |
| `chain_ratio` | 骨链比例，round 到 6 位 |
| `mask` | `verdict` / `constraints_capped` / `skipped_count` / `constraints_needed` / `constraints_added` / `constraints_already_blocked` / `readback_mismatch` |
| `action` | `name` / `frame_range` |
| `scene` | `frame_start` / `frame_end` / `fps` |
| `cache` | `is_baked` / `is_outdated` |

剔除（excluded，逐条给理由）：

| 键 | 理由 |
|---|---|
| 绝对路径类（`blend` / `out` / `vmd` / `preset`） | 换目录不该改变内容；它们由 identity 记录负责，不属于内容 |
| 时间戳类（`started_at` / `finished_at` / `file_mtime`） | 与内容无关 |
| `.blend` 的 sha256 | 那是**实例身份**（这一份文件的指纹），跨次本来就不同；见 §一 的两层定义 |
| `blender` / `python` 版本 | 它们是**环境上下文**：会影响数值，但不是「这份内容」的一部分。记在 facts 里随件保留，不进摘要 |
| `elapsed` / 耗时 | 与内容无关 |

**摘要算法**：`sha256(b"content_digest_v1\\n" + canonical_json)`，其中 `canonical_json` 是
`json.dumps(subset, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`。
版本前缀进哈希，换版本时摘要必然全变——这是有意的，避免「换了规格但看起来仍相同」。

**性质（必须成立，见 `--selftest`）**：
- 改任一 included 字段 ⇒ 摘要变；
- 只改 excluded 字段 ⇒ 摘要不变；
- 两次相同输入 ⇒ 摘要相同。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys

VERSION = "content_digest_v1"

INCLUDED_TOP = ("rigids", "constraints_by_type", "chain_ratio", "mask", "action", "scene", "cache")
BODY_FIELDS = ("name", "parent_bone", "mass", "kinematic", "collision_shape",
               "collision_collections", "friction")
MASK_FIELDS = ("verdict", "constraints_capped", "skipped_count", "constraints_needed",
               "constraints_added", "constraints_already_blocked", "readback_mismatch")


def _body(body):
    row = {}
    for f in BODY_FIELDS:
        v = body.get(f)
        if isinstance(v, float):
            v = round(v, 6)
        if isinstance(v, list):
            v = [int(x) for x in v]
        row[f] = v
    row["name"] = str(body.get("name"))
    return row


def subset(facts, strict=True):
    """按规格抽参与摘要的字段。缺字段时：strict 直接报错（不编默认值），否则跳过。"""
    out = {}
    missing = []
    for key in INCLUDED_TOP:
        if key not in facts or facts[key] is None:
            missing.append(key)
            continue
        out[key] = facts[key]

    if "bodies" in facts and facts["bodies"] is not None:
        out["bodies"] = sorted((_body(b) for b in facts["bodies"]), key=lambda r: r["name"])
    else:
        missing.append("bodies")

    if isinstance(out.get("mask"), dict):
        out["mask"] = {k: out["mask"].get(k) for k in MASK_FIELDS}
    if isinstance(out.get("action"), dict):
        out["action"] = {"name": out["action"].get("name"),
                         "frame_range": [int(x) for x in (out["action"].get("frame_range") or [])
                                         ] or None}
    if isinstance(out.get("scene"), dict):
        out["scene"] = {k: out["scene"].get(k) for k in ("frame_start", "frame_end", "fps")}
    if isinstance(out.get("cache"), dict):
        out["cache"] = {k: out["cache"].get(k) for k in ("is_baked", "is_outdated")}
    if isinstance(out.get("chain_ratio"), float):
        out["chain_ratio"] = round(out["chain_ratio"], 6)
    if isinstance(out.get("constraints_by_type"), dict):
        out["constraints_by_type"] = {str(k): int(v)
                                      for k, v in sorted(out["constraints_by_type"].items())}
    if missing and strict:
        raise SystemExit("facts 缺字段 %r：不编默认值，先补齐再算（%s）" % (missing, VERSION))
    return out


def digest(facts, strict=True):
    body = json.dumps(subset(facts, strict=strict), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    h = hashlib.sha256()
    h.update(VERSION.encode("ascii") + b"\n")
    h.update(body.encode("utf-8"))
    return h.hexdigest(), body


def _mini_facts():
    return {
        "blend": r"E:\x\delivery_v1.blend", "blend_sha256": "a" * 64,
        "started_at": "2026-11-16T18:00:00+0800", "elapsed_s": 12.5,
        "blender": "5.2.2", "python": "3.13.13",
        "rigids": 3,
        "bodies": [
            {"name": "000_a", "parent_bone": "下擺_0_0", "mass": 1.0, "kinematic": False,
             "collision_shape": "BOX", "collision_collections": [1, 0], "friction": 0.5},
            {"name": "001_b", "parent_bone": "下擺_0_1", "mass": 2.0, "kinematic": True,
             "collision_shape": "SPHERE", "collision_collections": [1, 0], "friction": 0.5},
            {"name": "002_ground", "parent_bone": None, "mass": 1.0, "kinematic": False,
             "collision_shape": "CONVEX_HULL", "collision_collections": [1, 0], "friction": 0.5},
        ],
        "constraints_by_type": {"COPY_ROTATION": 10, "LIMIT_ROTATION": 2},
        "chain_ratio": 0.946,
        "mask": {"verdict": "WIRED", "constraints_capped": False, "skipped_count": 0,
                 "constraints_needed": 8499, "constraints_added": 6686,
                 "constraints_already_blocked": 1813, "readback_mismatch": 0},
        "action": {"name": "B_aligned", "frame_range": [1, 300]},
        "scene": {"frame_start": 1, "frame_end": 240, "fps": 24.0},
        "cache": {"is_baked": False, "is_outdated": True},
    }


def selftest():
    """三条性质的自检：included 变 ⇒ 变；excluded 变 ⇒ 不变；同输入 ⇒ 同。"""
    base = _mini_facts()
    d0, _ = digest(base)
    cases = []

    f = json.loads(json.dumps(base))
    f["bodies"][1]["kinematic"] = False                    # 物理字段翻转
    cases.append(("bodies[1].kinematic 翻转", digest(f)[0], True))

    f = json.loads(json.dumps(base))
    f["bodies"][0]["mass"] = 1.5
    cases.append(("bodies[0].mass 改", digest(f)[0], True))

    f = json.loads(json.dumps(base))
    f["scene"]["frame_end"] = 832
    cases.append(("scene.frame_end 改", digest(f)[0], True))

    f = json.loads(json.dumps(base))
    f["constraints_by_type"]["LIMIT_ROTATION"] = 3
    cases.append(("constraints 条数改", digest(f)[0], True))

    f = json.loads(json.dumps(base))
    f["mask"]["constraints_added"] = 6685
    cases.append(("mask.constraints_added 改", digest(f)[0], True))

    f = json.loads(json.dumps(base))
    f["blend"] = r"D:\other\delivery_v1.blend"
    f["blend_sha256"] = "b" * 64
    f["started_at"] = "2030-01-01T00:00:00+0800"
    f["elapsed_s"] = 99.0
    f["blender"] = "9.9.9"
    cases.append(("只改 excluded（路径/时间戳/版本）", digest(f)[0], False))

    bad = 0
    for label, got, should_change in cases:
        changed = got != d0
        ok = changed == should_change
        print("  [%s] %-40s 期望%s，实际%s" % ("ok" if ok else "NO", label,
                                              "变" if should_change else "不变",
                                              "变" if changed else "不变"))
        bad += 0 if ok else 1
    print("  摘要基准值 = %s" % d0)
    print("自检 %d 条，失败 %d 条" % (len(cases), bad))
    return 0 if bad == 0 else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="content_digest_v1（回读内容的规范化摘要）")
    ap.add_argument("--facts", help="facts JSON（含 rigids/bodies/constraints_by_type/...）")
    ap.add_argument("--json", action="store_true", help="只打印摘要本身")
    ap.add_argument("--selftest", action="store_true", help="跑三条性质的自检")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.facts:
        ap.error("要么 --facts，要么 --selftest")

    with io.open(args.facts, encoding="utf-8-sig") as fh:
        facts = json.load(fh)
    # 允许直接把 rebuild_report.json 喂进来（它有 build.metrics.constraints / chain_ratio）
    if "build" in facts and isinstance(facts.get("build"), dict):
        metrics = facts["build"].get("metrics") or {}
        facts = dict(facts)
        facts.setdefault("constraints_by_type", metrics.get("constraints"))
        facts.setdefault("chain_ratio", metrics.get("chain_ratio"))
    d, body = digest(facts, strict=bool(facts.get("bodies")))
    if args.json:
        print(d)
        return 0
    print("%s = %s" % (VERSION, d))
    print("参与摘要的字段（%d 字节 canonical json）：" % len(body.encode("utf-8")))
    for key in INCLUDED_TOP:
        if key in facts and facts.get(key) is not None:
            print("  + %s" % key)
    if facts.get("bodies"):
        print("  + bodies（%d 条，按 name 排序）" % len(facts["bodies"]))
    else:
        print("  - bodies（**缺**：严格模式下本该报错；本次是重建报告，只有聚合量）")
    print("剔除：路径 / 时间戳 / blend_sha256 / blender·python 版本 / 耗时（理由见模块 docstring）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
