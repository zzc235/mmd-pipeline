"""M04 侧的掩码对账：我的胶囊重叠，有多少是「MMD 说不该互撞」的刚体对造成的。

输入（都在盘上，无需 Blender）：
  * `out/subai/M04/penetration/rigid_mask_dump.json`（本笔导出的 刚体→骨/组号/掩码）
  * `reports/subai/M04/baselines/B_from_blend1_roi18_capsule_v1.json`（5076 个重叠刚体对的基线）

MMD 语义（PMX 手册）：刚体 A 与 B 互撞 ⟺ A 的掩码含 B 的组 **且** B 的掩码含 A 的组。
不满足即「按 MMD 语义应当互不碰撞」——而本场景的 Blender 解算里这两条通道都没接，
所以这些对在解算中**照样互撞**。

输出只回答一个问题：**我的重叠数字里，有多大比例属于「本来就不该碰」的对。**
不是新测量、不出新深度数字。
"""
import json
import os

ROOT = r"E:\dsh pr\woker2"
DUMP = os.path.join(ROOT, r"out\subai\M04\penetration\rigid_mask_dump.json")
BASE = os.path.join(ROOT, r"reports\subai\M04\baselines\B_from_blend1_roi18_capsule_v1.json")
OUT = os.path.join(ROOT, r"out\subai\M04\penetration\mask_reconciliation.json")
SKIRT_ROI = "\u4e0b\u64fa_0_"  # 下擺_0_


def allows(group_a, mask_a, group_b, mask_b):
    """MMD：双方掩码都得含对方的组。组号 1..16 → bit 0..15。"""
    return bool(mask_a & (1 << (group_b - 1))) and bool(mask_b & (1 << (group_a - 1)))


def main():
    dump = json.load(open(DUMP, encoding="utf-8"))
    base = json.load(open(BASE, encoding="utf-8"))
    all_rows = dump["rows"]
    # 与探针的配对空间严格对齐：**ROI 侧**排除 kinematic（探针 --exclude-static），
    # **其它侧**不排除——探针的 `others` 是「除 ROI 刚体之外的全部刚体」，含 kinematic。
    # 不对齐的结果是 36/92 个基线键查不到对象，而那会伪装成「0 个属于不该互撞的对」。
    roi = [r for r in all_rows if SKIRT_ROI in r["bone"] and not r["kinematic"]]
    roi_names = {r["object"] for r in roi}
    others = [r for r in all_rows if r["object"] not in roi_names]
    rows = roi + others

    total_pairs = disallowed_all = 0
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = rows[i], rows[j]
            total_pairs += 1
            if not allows(a["group"], a["mask"], b["group"], b["mask"]):
                disallowed_all += 1

    roi_pairs = roi_disallowed = 0
    disallowed_bone_pairs = set()
    for a in roi:
        for b in others:
            roi_pairs += 1
            if not allows(a["group"], a["mask"], b["group"], b["mask"]):
                roi_disallowed += 1
                # **两侧都用同一套归一化**：基线的键是 `<ROI 骨>|<其它骨>`（有序，ROI 在前），
                # 直接拿它和 `sorted()` 出来的键比会一个都对不上——那会得出一个「0 个重叠属于
                # 不该互撞的对」的假结论。2026-11-16 14:0x 第一版就是这么错的。
                disallowed_bone_pairs.add(tuple(sorted((a["bone"], b["bone"]))))

    baseline_pairs = dict(base.get("baseline_m") or {})
    base_keys = {tuple(sorted(k.split("|"))) for k in baseline_pairs}
    overlapping = len(base_keys)
    overlapping_disallowed = len(base_keys & disallowed_bone_pairs)

    doc = {
        "spec": "mask_reconciliation/1",
        "blend": dump["blend"],
        "source": {"dump": os.path.basename(DUMP), "baseline": os.path.basename(BASE)},
        "rigid_rows": len(rows), "roi_rigids": len(roi), "other_rigids": len(others),
        "mask_read_failures": len(dump["read_failures"]),
        "all_pairs": total_pairs, "all_pairs_mmd_disallowed": disallowed_all,
        "all_pairs_disallowed_rate": round(disallowed_all / float(total_pairs), 4) if total_pairs else None,
        "roi_pairs": roi_pairs, "roi_pairs_mmd_disallowed": roi_disallowed,
        "roi_pairs_disallowed_rate": round(roi_disallowed / float(roi_pairs), 4) if roi_pairs else None,
        "baseline_overlapping_bone_pairs": overlapping,
        "baseline_pairs_mmd_disallowed": overlapping_disallowed,
        "baseline_disallowed_share": round(overlapping_disallowed / float(overlapping), 4) if overlapping else None,
        "reading": "MMD 语义下应当互不碰撞、但本场景解算里照样互撞的刚体对；"
                   "这些对的重叠量属于「解算口径造成」，不是设计缺陷。",
        "not_a_measurement": True,
    }
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in doc.items() if k != "reading"},
                     ensure_ascii=False, indent=1))


main()
