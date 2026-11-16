#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""`content_digest_v1`：把「交付件的内容」压成一个可复核、可跨次比较的摘要（纯 Python）。

为什么要有这个东西（总控 18:08 §一）：`.blend` **不是逐字节可复现的**——同一输入连跑三次，
字节 5 929 823 / 5 928 599 / 5 923 244 各不同，而回读内容一致。于是「交付件能由代码重建」
这句话只能定义在**内容**上；但「内容相同」若不说清剥掉了什么，任何两份文件都会「相同」，
判据就变成恒绿。本脚本与 `content_digest_v1.md` 一起负责把这句话说死。

## 规格（v1.1，改版本要写为什么）

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

**摘要算法**：`sha256(<版本前缀 ASCII> + b"\\n" + canonical_json)`，其中 `canonical_json` 是
`json.dumps(subset, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`。
版本前缀进哈希，换版本时摘要必然全变——这是有意的，避免「换了规格但看起来仍相同」。

## v1.1 修的洞（总控 18:09 §一 复现的那条）

v1 里 `strict=False` 会**悄悄**跳过缺失字段并照样给出摘要：两份物理上不同的 facts 得到同一个
摘要，而摘要本身**看不出** `bodies` 被跳过。这等于「缺料不拒、还给出一个看起来合格的答案」。
v1.1 三条一起改：

1. **模式分版本前缀**：强摘要 `content_digest_v1`，弱摘要 `content_digest_v1_partial`。
   两者哈希输入的第一行不同 ⇒ **数学上不可能相等**，不会被误当同一件事。
2. **覆盖面写进摘要**：每份摘要的 canonical json 里都有
   `"__coverage__": {"mode": ..., "version": ..., "missing": [...]}`
   （`rigids` 与 `len(bodies)` 不一致时还会带 `body_count_mismatch`）。弱摘要**自证它少了什么**。
3. **模式随结果落盘**：`compute()` 的返回记录里有 `digest_mode: "strict" | "partial"`，
   CLI 的 `--record-out` 直接写这个字段——不靠调用方记得。

另外 **fail-closed 成了默认**：CLI 不带 `--allow-partial` 时，缺字段一律**拒绝出摘要**
（exit 2），要弱摘要必须显式写 `--allow-partial`，且输出会标 partial。

## 比较纪律（比之前先读这一条）

**摘要只在同一 mode、同一版本前缀内比较。** 同一份完整 facts 用 strict 与 `--allow-partial`
打出来的摘要**必然不同**（前缀不同），所以跨 mode 比出来的「不同」只是模式差异，不代表内容被改过；
把它当成「被改过」就是误判。partial 之间相等也只能说「在 `missing` 没列到的那几项上一致」。
看见摘要不同，先问：是不是换了模式 / 换了版本前缀。

**性质（必须成立，见 `--selftest`）**：
- 改任一 included 字段 ⇒ 摘要变；
- 只改 excluded 字段 ⇒ 摘要不变；
- 两次相同输入 ⇒ 摘要相同；
- 缺必填字段 + strict ⇒ **拒绝**（SystemExit），不出摘要；
- 同一份 facts，partial 摘要 ≠ strict 摘要；
- partial 摘要的 `__coverage__.missing` 必须列出缺的项。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys

# GBK 控制台下 `⇒`/中文混排会让脚本崩在打印上（总控 18:18）：入口统一 UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                        # noqa: BLE001
        pass

VERSION = "content_digest_v1"
VERSION_PARTIAL = VERSION + "_partial"

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


def _extract(facts):
    """按规格抽参与摘要的字段。返回 (subset, missing 排序列表, 计数不符的说明或 None)。

    这里只做抽取与「缺了什么」的记账，**是否放行由调用方按模式决定**——
    判据的覆盖面必须能写进摘要本身，不能靠调用方自律。
    """
    out = {}
    missing = []
    for key in INCLUDED_TOP:
        if key not in facts or facts[key] is None:
            missing.append(key)
            continue
        out[key] = facts[key]

    bodies = facts.get("bodies")
    if isinstance(bodies, list) and bodies:
        out["bodies"] = sorted((_body(b) for b in bodies), key=lambda r: r["name"])
    else:
        # 缺、None、空列表（回读失败时最常见的形状）都算缺 —— 空列表不许当成「0 个刚体」
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

    # 总数与逐刚体条数不一致 ⇒ 逐刚体回读不完整，必须记下来（strict 直接拒）
    mismatch = None
    rigids = facts.get("rigids")
    if isinstance(rigids, int) and isinstance(bodies, list) and len(bodies) != rigids:
        mismatch = {"rigids": rigids, "bodies": len(bodies)}

    return out, sorted(missing), mismatch


def subset(facts, strict=True):
    """向后兼容的入口：只返回参与摘要的字段。strict 且缺字段时抛 SystemExit。"""
    out, missing, mismatch = _extract(facts)
    if strict and (missing or mismatch):
        raise SystemExit(_refusal(missing, mismatch))
    return out


def _refusal(missing, mismatch):
    bits = []
    if missing:
        bits.append("facts 缺字段 %r" % (missing,))
    if mismatch:
        bits.append("逐刚体回读不完整：rigids=%d 但 bodies 只有 %d 条"
                    % (mismatch["rigids"], mismatch["bodies"]))
    return "%s：不编默认值，先补齐再算（%s；要弱摘要请显式 --allow-partial）" % (
        "；".join(bits), VERSION)


def compute(facts, strict=True):
    """算摘要并返回**带模式标记**的记录（这是唯一的正规入口）。

    返回键：`digest` / `digest_mode` / `version` / `missing` / `body_count_mismatch` /
    `canonical_json` / `canonical_sha256` / `canonical_bytes`。
    """
    mode = "strict" if strict else "partial"
    out, missing, mismatch = _extract(facts)
    if mode == "strict" and (missing or mismatch):
        raise SystemExit(_refusal(missing, mismatch))

    prefix = VERSION if mode == "strict" else VERSION_PARTIAL
    coverage = {"mode": mode, "version": prefix, "missing": missing}
    if mismatch:
        coverage["body_count_mismatch"] = mismatch
    out["__coverage__"] = coverage

    body = json.dumps(out, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    raw = body.encode("utf-8")
    h = hashlib.sha256()
    h.update(prefix.encode("ascii") + b"\n")
    h.update(raw)
    return {
        "digest": h.hexdigest(),
        "digest_mode": mode,
        "version": prefix,
        "missing": missing,
        "body_count_mismatch": mismatch,
        "canonical_json": body,
        "canonical_sha256": hashlib.sha256(raw).hexdigest(),
        "canonical_bytes": len(raw),
    }


def digest(facts, strict=True):
    """向后兼容的入口：返回 (摘要, canonical_json)。"""
    rec = compute(facts, strict=strict)
    return rec["digest"], rec["canonical_json"]


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


def _no_bodies(facts):
    """去掉逐刚体属性，模拟「只有 rebuild_report.json 的聚合量」那一层。"""
    f = json.loads(json.dumps(facts))
    f.pop("bodies", None)
    return f


def _strict_refuses(facts):
    """strict 模式必须拒绝：返回 True 才算对。"""
    try:
        compute(facts, strict=True)
    except SystemExit:
        return True
    return False


def selftest():
    """九条性质的自检（v1.1：新增 fail-closed 三条 + 模式区分两条）。"""
    base = _mini_facts()
    d0 = compute(base, strict=True)["digest"]
    cases = []

    f = json.loads(json.dumps(base))
    f["bodies"][1]["kinematic"] = False                    # 物理字段翻转
    cases.append(("bodies[1].kinematic 翻转", compute(f)["digest"], True))

    f = json.loads(json.dumps(base))
    f["bodies"][0]["mass"] = 1.5
    cases.append(("bodies[0].mass 改", compute(f)["digest"], True))

    f = json.loads(json.dumps(base))
    f["scene"]["frame_end"] = 832
    cases.append(("scene.frame_end 改", compute(f)["digest"], True))

    f = json.loads(json.dumps(base))
    f["constraints_by_type"]["LIMIT_ROTATION"] = 3
    cases.append(("constraints 条数改", compute(f)["digest"], True))

    f = json.loads(json.dumps(base))
    f["mask"]["constraints_added"] = 6685
    cases.append(("mask.constraints_added 改", compute(f)["digest"], True))

    f = json.loads(json.dumps(base))
    f["blend"] = r"D:\other\delivery_v1.blend"
    f["blend_sha256"] = "b" * 64
    f["started_at"] = "2030-01-01T00:00:00+0800"
    f["elapsed_s"] = 99.0
    f["blender"] = "9.9.9"
    cases.append(("只改 excluded（路径/时间戳/版本）", compute(f)["digest"], False))

    bad = 0
    print("一、included/excluded 方向（%d 条）" % len(cases))
    for label, got, should_change in cases:
        changed = got != d0
        ok = changed == should_change
        print("  [%s] %-40s 期望%s，实际%s" % ("ok" if ok else "NO", label,
                                              "变" if should_change else "不变",
                                              "变" if changed else "不变"))
        bad += 0 if ok else 1
    print("  摘要基准值 = %s" % d0)

    # ---- v1.1：fail-closed（缺料必须拒）----
    print("二、fail-closed：缺 bodies + strict 必须拒绝（3 条）")
    weak = _no_bodies(base)
    empty = json.loads(json.dumps(base))
    empty["bodies"] = []
    short = json.loads(json.dumps(base))
    short["bodies"] = short["bodies"][:2]                  # rigids=3 ≠ 2
    for label, facts in (("缺 bodies 键", weak), ("bodies = []", empty),
                         ("rigids 3 但 bodies 2 条", short)):
        refused = _strict_refuses(facts)
        print("  [%s] %-40s 期望拒绝，实际%s" % ("ok" if refused else "NO", label,
                                                "拒绝" if refused else "**出了摘要**"))
        bad += 0 if refused else 1

    # ---- v1.1：弱摘要不得冒充强摘要 ----
    print("三、模式区分（3 条）")
    rec_s = compute(base, strict=True)
    rec_p = compute(base, strict=False)
    same_facts_differ = rec_s["digest"] != rec_p["digest"]
    print("  [%s] %-40s 期望不同，实际%s" % ("ok" if same_facts_differ else "NO",
                                            "同一 facts 的 strict vs partial",
                                            "不同" if same_facts_differ else "**相同**"))
    bad += 0 if same_facts_differ else 1

    weak_rec = compute(weak, strict=False)
    declared = (weak_rec["digest_mode"] == "partial"
                and weak_rec["missing"] == ["bodies"]
                and '"missing":["bodies"]' in weak_rec["canonical_json"]
                and weak_rec["version"] == VERSION_PARTIAL)
    print("  [%s] %-40s 期望 partial + missing=[bodies] 进摘要，实际%s"
          % ("ok" if declared else "NO", "弱摘要自证缺了什么",
             "对" if declared else "缺声明"))
    bad += 0 if declared else 1

    # 总控 18:09 复现的那个洞：两份物理上不同的 facts（都只剩聚合量，其中一份多带旁证字段
    # mass_total_g）。v1 里二者摘要相等且看不出缺 bodies ⇒ 洞。v1.1：strict 必须都拒；
    # partial 相等仍允许，但必须自证 partial + missing=[bodies]。
    hole_a = _no_bodies(base)
    hole_b = json.loads(json.dumps(hole_a))
    hole_b["mass_total_g"] = 12.5                          # 旁证字段：不进摘要，正是洞的来源
    strict_both_refused = _strict_refuses(hole_a) and _strict_refuses(hole_b)
    pa, pb = compute(hole_a, strict=False), compute(hole_b, strict=False)
    declared = (pa["digest_mode"] == pb["digest_mode"] == "partial"
                and pa["version"] == pb["version"] == VERSION_PARTIAL
                and pa["missing"] == ["bodies"]
                and '"missing":["bodies"]' in pa["canonical_json"])
    hole_closed = strict_both_refused and declared
    print("  [%s] %-40s 期望strict双拒+partial自证，实际%s"
          % ("ok" if hole_closed else "NO", "18:09 那个洞（两份不同 facts）",
             "闭合（partial 摘要%s，但已自证 partial）" % ("仍相等" if pa["digest"] == pb["digest"]
                                                     else "不同")
             if hole_closed else "**仍开**"))
    bad += 0 if hole_closed else 1

    total = len(cases) + 6
    print("自检 %d 条，失败 %d 条" % (total, bad))
    return 0 if bad == 0 else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="content_digest_v1（回读内容的规范化摘要）")
    ap.add_argument("--facts", help="facts JSON（含 rigids/bodies/constraints_by_type/...）")
    ap.add_argument("--json", action="store_true",
                    help="只打印摘要记录（含 digest_mode / version / missing）")
    ap.add_argument("--digest-only", action="store_true", help="只打印摘要十六进制串")
    ap.add_argument("--record-out", help="把摘要记录写到这个文件（含 digest_mode）")
    ap.add_argument("--allow-partial", action="store_true",
                    help="缺字段时允许出弱摘要（默认拒绝；弱摘要不会与强摘要相等）")
    ap.add_argument("--selftest", action="store_true", help="跑九条性质的自检")
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

    try:
        rec = compute(facts, strict=not args.allow_partial)
    except SystemExit as exc:
        print("拒绝：%s" % exc)
        print("（fail-closed 是默认行为；要弱摘要必须显式 --allow-partial，"
              "得到的摘要前缀是 %s，与强摘要永不可能相等）" % VERSION_PARTIAL)
        return 2

    out = {k: rec[k] for k in ("digest", "digest_mode", "version", "missing",
                               "body_count_mismatch", "canonical_sha256", "canonical_bytes")}
    out["facts_path"] = args.facts
    if args.record_out:
        with io.open(args.record_out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    if args.digest_only:
        print(rec["digest"])
        return 0
    if args.json:
        print(json.dumps(out, ensure_ascii=False, sort_keys=True))
        return 0

    print("%s = %s" % (rec["version"], rec["digest"]))
    print("digest_mode = %s" % rec["digest_mode"])
    if rec["missing"]:
        print("缺项（已进摘要的 __coverage__）= %r" % (rec["missing"],))
        print("  ⇒ 这份摘要**不覆盖**上述字段，不得用于声称「内容确定 / 可复现」")
    if rec["body_count_mismatch"]:
        print("逐刚体不完整 = %r" % (rec["body_count_mismatch"],))
    print("参与摘要的字段（%d 字节 canonical json）：" % rec["canonical_bytes"])
    for key in INCLUDED_TOP:
        if key in facts and facts.get(key) is not None:
            print("  + %s" % key)
    if facts.get("bodies"):
        print("  + bodies（%d 条，按 name 排序）" % len(facts["bodies"]))
    else:
        print("  - bodies（**缺**：只覆盖聚合量）")
    print("剔除：路径 / 时间戳 / blend_sha256 / blender·python 版本 / 耗时（理由见模块 docstring）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
