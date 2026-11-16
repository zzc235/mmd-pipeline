# -*- coding: utf-8 -*-
"""造 M04 对照场景：改**碰撞位**、并按需要**清掉刚体点缓存**（位改要真的进解算）。

用途（预注册 v4 §二）：A0 是**仪器灵敏度正控**，不进任何判词。它回答的问题是：
「如果碰撞状态真的变了，这台探针看得见吗？」——若 A0 与 A 读数相同，说明探针看不见碰撞状态，
四组全部作废判 `UNMEASURED`。

2026-11-16 实测（`m04_a0_why_blind.py`，两支场景各一份）：
  只清位、不碰缓存 ⇒ A 与 A0 **240/240 帧逐位相同**。机制已查明：
  `rigidbody_world.point_cache.is_baked = true`（frame 1..326，240 帧在内存里），
  探针 `frame_set` 顺序走帧时**读的是已烘焙的旧解算结果**，位清零根本没进解算；
  并且 ROI 那 18 根骨**一个关键帧都没有**（`total_keys = 0`），全靠 `_arm_rig` 上
  511 条 pose 约束跟着刚体对象走 ⇒ 「骨骼被键钉死」与「没有解算」两个假设都被排除。
  ⇒ 清位必须**同时清缓存**，位才进解算。

为什么只清位、不删约束：
  Blender 侧语义是「共享某一位即碰」（4号 用 40 帧下落实验实测：D(bit1) 被 G(bit1) 挡住、
  穿过 G(bit2)）。**所有位清空 ⇒ 没有任何两刚体共享位 ⇒ 一对都不碰**，
  既有 `disable_collisions` 约束因此变成冗余，无需改动它们——
  这也避开了 `constraint_add()` 每次触发全场景 depsgraph 求值的代价（B 组就死在那上面）。

安全约定：源 `.blend` 只读；产物写到**新路径**；绝不 save 回源；前后 sha256 必须一致。

用法（Blender --background）：
  # A0：清位 + 清缓存（灵敏度正控的实验臂）
  blender -b --python m04_make_a0_scene.py -- --blend SRC --out-blend A0_free.blend \
      --out-json a0_free.json --clear-bits --free-cache
  # R ：不改位 + 清缓存（对照臂：证明"重解一遍"本身不会凭空改变读数）
  blender -b --python m04_make_a0_scene.py -- --blend SRC --out-blend R_free.blend \
      --out-json r_free.json --keep-bits --free-cache

退出码：0 = 产物与记录一致 / 3 = 异常、或回读不符（位没清干净 / 缓存没清掉 / 源被改）
"""
import argparse
import hashlib
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

CACHE_ATTRS = ("is_baked", "info", "use_disk_cache", "frame_start", "frame_end",
               "frame_step", "use_external")


def _args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--blend", required=True)
    p.add_argument("--out-blend", required=True, help="对照场景写到这个**新**路径")
    p.add_argument("--out-json", required=True)
    bits = p.add_mutually_exclusive_group()
    bits.add_argument("--clear-bits", dest="clear_bits", action="store_true", default=True,
                      help="清空所有刚体的 collision_collections 位（默认）")
    bits.add_argument("--keep-bits", dest="clear_bits", action="store_false",
                      help="不动位（用于造「只清缓存」的对照臂）")
    p.add_argument("--free-cache", action="store_true",
                   help="清掉刚体世界的点缓存，让顺序走帧时**重新解算**（不清就会读到旧烘焙结果）")
    p.add_argument("--control-tag", default="", help="写进 scene 的控制组标签；留空则按开关自动取")
    return p.parse_args(argv)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cache_state(scene):
    """点缓存状态快照。`is_baked=true` 就是「探针会读到旧解算结果」的那个开关。"""
    rbw = getattr(scene, "rigidbody_world", None)
    if rbw is None:
        return {"present": False}
    pc = getattr(rbw, "point_cache", None)
    if pc is None:
        return {"present": True, "point_cache": None}
    out = {"present": True}
    for a in CACHE_ATTRS:
        if hasattr(pc, a):
            v = getattr(pc, a)
            out[a] = v if isinstance(v, (int, float, bool, str)) else str(v)
    out["rbw_enabled"] = bool(getattr(rbw, "enabled", False))
    return out


def free_cache(scene):
    """清点缓存，返回 (方法名, 是否成功)。方法名进记录——不同 Blender 版本路径不同。"""
    import bpy
    rbw = getattr(scene, "rigidbody_world", None)
    pc = getattr(rbw, "point_cache", None) if rbw is not None else None
    if pc is None:
        return "no_point_cache", False
    attempts = []
    for name in ("free_bake_all",):
        op = getattr(bpy.ops.ptcache, name, None)
        if op is None:
            continue
        try:
            op()
            attempts.append((name, "ok"))
        except Exception as exc:                       # noqa: BLE001
            attempts.append((name, "raised:%s" % (exc,)))
    ok = not bool(getattr(pc, "is_baked", False))
    return "; ".join("%s=%s" % t for t in attempts) or "no_operator", ok


def main():
    a = _args()
    if os.path.abspath(a.out_blend) == os.path.abspath(a.blend):
        raise SystemExit("[a0] 拒绝把对照场景写回源文件")

    import bpy

    before = sha256_file(a.blend)
    bpy.ops.wm.open_mainfile(filepath=a.blend)
    scene = bpy.context.scene
    cache_before = cache_state(scene)

    rigids = [o for o in bpy.data.objects if getattr(o, "rigid_body", None) is not None]
    modified = 0
    width = None
    for o in rigids:
        body = o.rigid_body
        flags = body.collision_collections
        width = len(flags)
        before_true = sum(1 for f in flags if f)
        if not a.clear_bits:
            continue
        for i in range(width):
            flags[i] = False
        modified += 1 if before_true else 0

    # 回读确认
    still_set = 0
    for o in rigids:
        still_set += sum(1 for f in o.rigid_body.collision_collections if f)
    bits_readback_ok = (still_set == 0) if a.clear_bits else (still_set > 0)

    cache_method, cache_ok = "not_requested", True
    if a.free_cache:
        cache_method, cache_ok = free_cache(scene)
    cache_after = cache_state(scene)

    # 标记写进**场景自身**（不只文件名）：清位副本与「通道没接上」在位型上逐位相同，
    # 谁拿它过 wired 闸门都会读成 EMPTY —— 那不是通道失败，是控制组本身。
    # 打上 ID 属性后，标记跟着文件走，改名也不会丢。
    tag = a.control_tag
    if not tag:
        if a.clear_bits and a.free_cache:
            tag = "a0_collision_off_resim"
        elif a.clear_bits:
            tag = "a0_collision_off_cache_replay"
        elif a.free_cache:
            tag = "a_free_resim"
        else:
            tag = "a_copy_untouched"
    scene["m04_control"] = tag
    scene["m04_gate_eligible"] = False
    scene["m04_note"] = ("M04 control scene (%s). bits_cleared=%s free_cache=%s. "
                         "Bit pattern after clearing is identical to 'channel not wired'; "
                         "must NOT be fed to any wired/not-wired gate."
                         % (tag, a.clear_bits, a.free_cache))

    bpy.ops.wm.save_as_mainfile(filepath=a.out_blend)
    out_sha = sha256_file(a.out_blend)
    after_src = sha256_file(a.blend)

    pose_source = ("fresh_solve（缓存已清，顺序走帧会重新解算）" if (a.free_cache and cache_ok)
                   else "cache_replay（点缓存仍是烘焙态，读数来自旧解算结果——位改不会生效）")

    doc = {
        "spec": "m04_a0_scene/2",
        "purpose": ("instrument sensitivity control (clear bits + free cache)" if (a.clear_bits and a.free_cache)
                    else "control arm: free cache without touching bits" if a.free_cache
                    else "control scene built without freeing the cache"),
        "control": tag,
        "gate_eligible": False,
        "must_not_enter_gates": [
            "m02_mask_channel_probe.py --expect wired",
            "mmdpipe.stage.stage_mask(root)",
        ],
        "predicted_stage_mask_verdict": "EMPTY" if a.clear_bits else "（不清位时无预测，本臂不过闸门）",
        "prediction_note": ("清位副本与「通道没接上」在位型上逐位相同（无任何两刚体共享位）。"
                            "所以 wired 闸门对它读 EMPTY 是**正确行为**，不是通道失败；"
                            "它的用途只有一条：证明探针在这个场景上看得见碰撞状态的变化。"),
        "not_a_physics_measurement": True,
        "bits_cleared": bool(a.clear_bits),
        "free_cache_requested": bool(a.free_cache),
        "cache_free_method": cache_method,
        "cache_free_ok": bool(cache_ok),
        "cache_state_before": cache_before,
        "cache_state_after": cache_after,
        "pose_source_if_probed": pose_source,
        "source_blend": a.blend,
        "source_sha256_before": before,
        "source_sha256_after": after_src,
        "source_unchanged": before == after_src,
        "out_blend": a.out_blend,
        "out_sha256": out_sha,
        "collision_collections_width": width,
        "rigid_object_count": len(rigids),
        "changed_rigid_count": modified,
        "bits_still_set_after": still_set,
        "bits_readback_ok": bits_readback_ok,
        "frame_range": [scene.frame_start, scene.frame_end],
        "note": ("清位 ⇒ 无共享位 ⇒ 一对都不碰；既有 disable_collisions 约束变冗余，未改动。"
                 "清缓存 ⇒ 走帧重新解算；不清缓存时位改不进解算（2026-11-16 实测 240/240 帧逐位相同）。"),
    }
    d = os.path.dirname(a.out_json)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(a.out_json, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    print("[a0] tag=%s clear_bits=%s free_cache=%s rigids=%d changed=%d width=%s"
          % (tag, a.clear_bits, a.free_cache, len(rigids), modified, width))
    print("[a0] bits_still_set=%d cache_before.is_baked=%s cache_after.is_baked=%s method=%s"
          % (still_set, cache_before.get("is_baked"), cache_after.get("is_baked"), cache_method))
    print("[a0] pose_source=%s" % pose_source)
    print("[a0] out_sha256=%s  source_unchanged=%s" % (out_sha[:16], doc["source_unchanged"]))
    print("[a0] written %s" % a.out_blend)
    ok = doc["source_unchanged"] and bits_readback_ok and (cache_ok if a.free_cache else True)
    sys.stdout.flush()
    sys.exit(0 if ok else 3)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException as exc:                 # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("[a0] FATAL %s: %s" % (type(exc).__name__, exc))
        sys.stdout.flush()
        sys.exit(3)
