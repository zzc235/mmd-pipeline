"""M01 阶段 A：只读基线。

不开 Blender，不写任何模型文件：
  * 两个源 PMX 的 SHA256
  * 飞霄 24-29 号刚体的 index/name/bone/mode/group/mask + 相连关节的 6DOF 限位与弹簧（原始字节）
  * 卡芙卡袖筒物理单元的真实结构（刚体数/关节数/cycle_rank/焊占比/mode 分布）

    python m01_baseline.py            # 写 out/subai/M01/baseline.json + baseline.md
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import sys

sys.path.insert(0, r"E:\dsh pr\woker2")

from mmdpipe import physics, pmx  # noqa: E402

FEIXIAO = (r"E:\blender模型\没有外套本家模型\星穹铁道—飞霄（无外套）.pmx")
KAFKA = (r"E:\blender模型\星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_"
         r"31cc0fe7cc29460474ff5e5cd7188309\星穹铁道—卡芙卡无外套\卡芙卡3.0.pmx")
OUT = r"E:\dsh pr\woker2\out\subai\M01"
TARGET_RIGIDS = list(range(24, 30))


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def joint_limits(model, jid: int) -> dict:
    """关节限位 / 弹簧原始值（实测字节布局，不是按规范猜）：

    pos(3f, +0) rot(3f, +12) 平移下限(3f, +24) 平移上限(3f, +36)
    旋转下限(3f, +48) 旋转上限(3f, +60) 平移弹簧(3f, +72) 旋转弹簧(3f, +78)
    """
    off = model.joint_pos_offsets[jid]
    lim = struct.unpack_from("<12f", model.raw, off + 24)
    spr = struct.unpack_from("<6f", model.raw, off + 72)
    return {
        "move_min": [round(v, 6) for v in lim[0:3]],
        "move_max": [round(v, 6) for v in lim[3:6]],
        "rot_min": [round(v, 6) for v in lim[6:9]],
        "rot_max": [round(v, 6) for v in lim[9:12]],
        "spring_move": [round(v, 6) for v in spr[0:3]],
        "spring_rot": [round(v, 6) for v in spr[3:6]],
    }


def feixiao_baseline() -> dict:
    m = pmx.load(FEIXIAO)
    assert m.tail_error is None, "飞霄 PMX 尾部没对齐：%s" % m.tail_error
    modes = {}
    for r in m.rigids:
        modes[r.mode] = modes.get(r.mode, 0) + 1
    targets = []
    for idx in TARGET_RIGIDS:
        if not (0 <= idx < len(m.rigids)):
            raise SystemExit("刚体索引 %d 越界（共 %d）" % (idx, len(m.rigids)))
        r = m.rigids[idx]
        targets.append({
            "index": r.index, "name": r.name,
            "bone_index": r.bone, "bone": m.bones[r.bone].name if 0 <= r.bone < len(m.bones) else "",
            "group": r.group, "mask": r.mask, "shape": r.shape, "mode": r.mode,
            "position": [round(v, 4) for v in r.position],
            "size": [round(v, 4) for v in r.size],
        })
    target_set = set(TARGET_RIGIDS)
    joints = []
    for j in m.joints:
        if j.rigid_a in target_set or j.rigid_b in target_set:
            raw = joint_limits(m, j.index)
            joints.append({
                "index": j.index, "name": j.name, "kind": j.kind,
                "rigid_a": j.rigid_a, "rigid_b": j.rigid_b,
                "welded": j.welded, "limit_span": round(j.limit_span, 6),
                "spring_max": round(j.spring_max, 6),
                "move_min": raw["move_min"], "move_max": raw["move_max"],
                "rot_min": raw["rot_min"], "rot_max": raw["rot_max"],
                "spring_move": raw["spring_move"], "spring_rot": raw["spring_rot"],
            })
    rep = physics.classify(m)
    return {
        "path": FEIXIAO, "sha256": sha256(FEIXIAO), "bytes": m.bytes_total,
        "model_name": m.name, "rigids": len(m.rigids), "joints": len(m.joints),
        "bones": len(m.bones), "mode_distribution": dict(sorted(modes.items())),
        "targets": targets, "target_joints": joints,
        "target_modes": sorted({t["mode"] for t in targets}),
        "target_modes_all_2": all(t["mode"] == 2 for t in targets),
        "counts": rep.counts, "mute_bones": rep.mute_bones,
        "suspect_units": rep.suspect_units,
    }


def kafka_baseline() -> dict:
    m = pmx.load(KAFKA)
    assert m.tail_error is None, "卡芙卡 PMX 尾部没对齐：%s" % m.tail_error
    modes = {}
    for r in m.rigids:
        modes[r.mode] = modes.get(r.mode, 0) + 1
    rep = physics.classify(m)
    sleeves = []
    for u in rep.units:
        if len(u.bodies) >= 20 and u.cycle_rank >= 20 and 2 not in (u.modes or {}):
            bodies = []
            for bi in u.bodies:
                r = m.rigids[bi]
                bodies.append({"index": bi, "name": r.name, "mode": r.mode,
                               "bone": m.bones[r.bone].name if 0 <= r.bone < len(m.bones) else "",
                               "group": r.group})
            sleeves.append({
                "uid": u.uid, "bodies": len(u.bodies), "joints": len(u.joint_ids),
                "cycle_rank": u.cycle_rank, "welded_ratio": round(u.welded_ratio, 3),
                "welded_joints": u.welded_joints, "flex_joints": u.flex_joints,
                "anchor_bone": u.anchor_bone, "modes": u.modes,
                "spring_max": round(u.spring_max, 6),
                "rigid_index_range": [min(u.bodies), max(u.bodies)],
                "body_detail": bodies,
            })
    xk = physics.bones_by_pattern(m, ["xk_"])
    return {
        "path": KAFKA, "sha256": sha256(KAFKA), "bytes": m.bytes_total,
        "model_name": m.name, "rigids": len(m.rigids), "joints": len(m.joints),
        "bones": len(m.bones), "mode_distribution": dict(sorted(modes.items())),
        "has_mode2_anywhere": modes.get(2, 0) > 0,
        "sleeve_units": sleeves,
        "counts": rep.counts,
        "suspect_units": rep.suspect_units,
        "suspect_bones": rep.suspect_bones,
        "strict_policy_bones": physics.bones_for_policy(rep, "strict"),
        "xk_bones": xk,
    }


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    fx = feixiao_baseline()
    kf = kafka_baseline()
    data = {"feixiao": fx, "kafka": kf}

    with open(os.path.join(OUT, "baseline.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)

    md = []
    md.append("# M01 阶段 A 基线（只读）\n")
    md.append("## 飞霄（S3）\n")
    md.append("- 文件：`%s`" % fx["path"])
    md.append("- SHA256：`%s`" % fx["sha256"])
    md.append("- 刚体 %d / 关节 %d / 骨 %d，mode 分布 %s"
              % (fx["rigids"], fx["joints"], fx["bones"], fx["mode_distribution"]))
    md.append("- 目标 24–29 全部 mode2：**%s**" % fx["target_modes_all_2"])
    md.append("\n| idx | name | bone | group | mask | mode |")
    md.append("|---:|---|---|---:|---:|---:|")
    for t in fx["targets"]:
        md.append("| %d | %s | %s | %d | %d | %d |"
                  % (t["index"], t["name"], t["bone"], t["group"], t["mask"], t["mode"]))
    md.append("\n| joint | a→b | welded | 转限位 rot_min → rot_max (rad) | 弹簧 max |")
    md.append("|---:|---|---|---|---:|")
    for j in fx["target_joints"]:
        md.append("| %d | %d→%d | %s | %s → %s | %.4g |"
                  % (j["index"], j["rigid_a"], j["rigid_b"], j["welded"],
                     j["rot_min"], j["rot_max"], j["spring_max"]))
    md.append("\n- 判定器：%s；待静音骨 %d 根" % (fx["counts"], len(fx["mute_bones"])))

    md.append("\n## 卡芙卡（S5）\n")
    md.append("- 文件：`%s`" % kf["path"])
    md.append("- SHA256：`%s`" % kf["sha256"])
    md.append("- 刚体 %d / 关节 %d / 骨 %d，mode 分布 %s，全模型有 mode2：**%s**"
              % (kf["rigids"], kf["joints"], kf["bones"],
                 kf["mode_distribution"], kf["has_mode2_anywhere"]))
    md.append("\n| 袖筒单元 | 刚体 | 关节 | 环 | 焊占比 | welded/flex | modes | 索引范围 |")
    md.append("|---|---:|---:|---:|---:|---|---|---|")
    for s in kf["sleeve_units"]:
        md.append("| %s | %d | %d | %d | %.0f%% | %d/%d | %s | %d–%d |"
                  % (s["anchor_bone"], s["bodies"], s["joints"], s["cycle_rank"],
                     s["welded_ratio"] * 100, s["welded_joints"], s["flex_joints"],
                     s["modes"], s["rigid_index_range"][0], s["rigid_index_range"][1]))
    md.append("\n- 结构僵死嫌疑单元 %d；strict 策略骨 %d 根；xk_ 匹配骨 %d 根"
              % (len(kf["suspect_units"]), len(kf["strict_policy_bones"]), len(kf["xk_bones"])))
    with open(os.path.join(OUT, "baseline.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")

    print("BASELINE ok")
    print("feixiao rigids=%d joints=%d modes=%s targets_ok=%s"
          % (fx["rigids"], fx["joints"], fx["mode_distribution"], fx["target_modes_all_2"]))
    print("feixiao target joints=%d all_welded=%s"
          % (len(fx["target_joints"]), all(j["welded"] for j in fx["target_joints"])))
    print("kafka rigids=%d joints=%d modes=%s" % (kf["rigids"], kf["joints"], kf["mode_distribution"]))
    print("kafka sleeve units=%d" % len(kf["sleeve_units"]))
    for s in kf["sleeve_units"]:
        print("  unit uid=%d bodies=%d joints=%d cycle=%d welded=%.2f modes=%s range=%s"
              % (s["uid"], s["bodies"], s["joints"], s["cycle_rank"],
                 s["welded_ratio"], s["modes"], s["rigid_index_range"]))
    print("kafka strict bones=%d xk bones=%d" % (len(kf["strict_policy_bones"]), len(kf["xk_bones"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
