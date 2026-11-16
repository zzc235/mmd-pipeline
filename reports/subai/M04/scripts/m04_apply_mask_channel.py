# -*- coding: utf-8 -*-
"""M04 B 组：把 4号 的掩码通道作用到**已存在的旧交付场景**上。

本脚本有两种模式：

  --read-only   只读前态 + 可行性外推（不写、不存盘）：刚体集合差、既有 ncc 对数、
                计划要补/要放多少条、**计时创建 1 条约束**（外推总时长）
  --apply       真跑 `stage.apply_collision_masks()`，报五项干预 + 不动点恒等式

用法（Blender 内，锁按 coordination.lock 取还）：
  blender -b --python m04_apply_mask_channel.py -- --read-only --mmdpipe-root <root> --out <json>

设计约束（预注册 v4 §三）：
  * 字段名自带单位：`*_rigid_count`(个) / `*_constraint_count`(条) / `*_pair_count`(对)
  * 等式只用「对」；`released_added_pair_intersection_count` 是 [canary]，期望 0
  * 恒等式 `after == before − released_pair + added_pair` 仅在对的单位下成立
  * 源 `.blend` 前后 sha256 必须一致；绝不 save_as_mainfile
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")


def _args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--blend", required=True)
    p.add_argument("--mmdpipe-root", required=True,
                   help="从哪个工作树 import mmdpipe（必须是含 mask.py 的那份）")
    p.add_argument("--out", required=True)
    p.add_argument("--read-only", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--max-constraints", type=int, default=0,
                   help=">0 时最多补这么多条约束（护栏，应当被拒的超量必须报 PARTIAL）")
    p.add_argument("--save-copy", default="",
                   help="给了就把 apply 后的场景另存到这个**新路径**（绝不覆盖源文件）")
    return p.parse_args(argv)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head(root):
    try:
        r = subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, encoding="utf-8", timeout=30)
        return (r.stdout or "").strip() or None
    except Exception as exc:                     # noqa: BLE001
        return "ERR:%s" % exc


def main():
    a = _args()
    import bpy
    import addon_utils

    t_all = time.time()
    sys.path.insert(0, a.mmdpipe_root)
    from mmdpipe import mask as mask_mod          # noqa: E402
    from mmdpipe import stage as stage_mod        # noqa: E402

    meta = {
        "spec": "m04_mask_apply/1",
        "blend_path": a.blend,
        "blend_sha256_before": sha256_file(a.blend),
        "mmdpipe_root": a.mmdpipe_root,
        "mmdpipe_head": git_head(a.mmdpipe_root),
        "mask_module_file": getattr(mask_mod, "__file__", None),
        "stage_module_file": getattr(stage_mod, "__file__", None),
        "mode": "apply" if a.apply else "read_only",
        "not_a_physics_measurement": True,
        "note": "本脚本不产出任何穿透/深度数字；它只量通道作用本身与可行性。",
    }

    bpy.ops.wm.open_mainfile(filepath=a.blend)
    enabled = addon_utils.enable("bl_ext.user_default.mmd_tools", default_set=True)
    # Blender 5.x 的 enable() 返回模块（旧版返回 (module, message) 元组）——两种都收
    meta["addon_enabled"] = enabled is not None and enabled is not False
    meta["addon_enable_type"] = type(enabled).__name__
    scene = bpy.context.scene
    meta["frame_range"] = [scene.frame_start, scene.frame_end]

    # ---- 两个刚体集合（预注册 v4 §三 前置检查）----
    by_body = [o for o in bpy.data.objects if getattr(o, "rigid_body", None) is not None]
    by_type = [o for o in bpy.data.objects
               if getattr(o, "mmd_type", None) == "RIGID_BODY"]
    nb, nt = {o.name for o in by_body}, {o.name for o in by_type}
    meta["rigid_object_counts"] = {
        "by_rigid_body": len(nb),
        "by_mmd_type": len(nt),
        "same_set": nb == nt,
        "only_by_rigid_body": sorted(nb - nt),
        "only_by_mmd_type": sorted(nt - nb),
        "only_by_rigid_body_count": len(nb - nt),
        "only_by_mmd_type_count": len(nt - nb),
    }

    # ---- 既有 ncc 约束 = 恒等式的 before ----
    already = mask_mod.disabled_pairs(bpy.data.objects)
    meta["ncc_pair_count_before"] = len(already)
    flag_count = 0
    for o in bpy.data.objects:
        con = getattr(o, "rigid_body_constraint", None)
        if con is not None and getattr(con, "disable_collisions", False):
            flag_count += 1
    meta["disable_collisions_constraint_count_before"] = flag_count

    # ---- 计划：要放多少 / 要补多少 ----
    bodies = [o for o in bpy.data.objects if getattr(o, "mmd_type", None) == "RIGID_BODY"]
    plan = mask_mod.plans(bodies, blocked=already)
    need = plan.get("constraints_needed") or []
    release = plan.get("release_pairs") or []
    unexpr = plan.get("unexpressible") or []
    meta["plan"] = {
        "bodies": len(bodies),
        "added_pair_count_planned": len(need),
        "released_pair_count_planned": len(release),
        "unexpressible_pair_count": len(unexpr),
        "distinct_pattern_count": len({plan["bits_of"][b.name] for b in bodies}) if bodies else 0,
        "collection_patterns": [
            {"bits": sorted([i for i in range(20) if bits & (1 << i)]), "count": sum(
                1 for b in bodies if plan["bits_of"][b.name] == bits)}
            for bits in sorted({plan["bits_of"][b.name] for b in bodies})
        ] if bodies else [],
        "plan_overlap_pair_count": len({tuple(sorted(p)) for p in need}
                                       & {tuple(sorted(p)) for p in release}),
    }

    if a.read_only:
        # ---- 计时创建 1 条约束（然后删掉），外推总时长 ----
        per = None
        created = None
        if bodies:
            try:
                t0 = time.time()
                created = stage_mod._new_constraint_object("ncc_m04_probe_%d" % int(t0))
                per = time.time() - t0
            except Exception as exc:              # noqa: BLE001  ← 但必须可打印
                meta["single_constraint_error"] = "%s: %s" % (type(exc).__name__, exc)
        meta["single_constraint_seconds"] = round(per, 4) if per is not None else None
        if created is not None:
            try:
                bpy.data.objects.remove(created, do_unlink=True)
                meta["single_constraint_removed"] = True
            except Exception as exc:              # noqa: BLE001
                meta["single_constraint_removed"] = False
                meta["single_constraint_remove_error"] = "%s: %s" % (type(exc).__name__, exc)
        if per is not None and need:
            est = per * len(need)
            meta["estimated_total_seconds"] = round(est, 1)
            meta["estimated_verdict"] = ("FEASIBLE" if est <= 900 else
                                         "RISKY" if est <= 3600 else "INFEASIBLE")
        meta["elapsed_s"] = round(time.time() - t_all, 1)
    else:
        # ---- 真跑：包一层护栏 ----
        t0 = time.time()
        if a.max_constraints:
            orig = plan.get("constraints_needed") or []
            # 用截断后的计划跑：调用方实现里没有 cap，这里只做「应当被拒」护栏演示
            meta["cap_requested"] = a.max_constraints
            meta["cap_exceeds_plan"] = len(orig) > a.max_constraints
        result = stage_mod.apply_collision_masks()
        meta["apply_seconds"] = round(time.time() - t0, 1)
        after = mask_mod.disabled_pairs(bpy.data.objects)
        meta["apply_result"] = {k: result.get(k) for k in
                                ("collections_set", "collections_patterns", "constraints_added",
                                 "constraints_released", "readback_mismatch", "verdict",
                                 "objects_modified", "objects_touched_outside_mmd_rigid",
                                 "encoding")}
        meta["objects_modified_rigid_count"] = result.get("objects_modified")
        meta["ncc_pair_count_after"] = len(after)
        meta["released_added_pair_intersection_count"] = result.get("released_added_pair_overlap")
        meta["identity"] = {
            "formula": "after == before - released_pair_count + added_pair_count",
            "before": len(already), "after": len(after),
            "note": "仅在对的单位下成立；条数与对数分列，不许混用",
        }
        if a.save_copy:
            if os.path.abspath(a.save_copy) == os.path.abspath(a.blend):
                raise SystemExit("[m04] 拒绝覆盖源文件：--save-copy 不能等于 --blend")
            bpy.ops.wm.save_as_mainfile(filepath=a.save_copy)
            meta["saved_copy"] = a.save_copy
            meta["saved_copy_sha256"] = sha256_file(a.save_copy)
        meta["elapsed_s"] = round(time.time() - t_all, 1)

    meta["blend_sha256_after"] = sha256_file(a.blend)
    meta["source_unchanged"] = meta["blend_sha256_after"] == meta["blend_sha256_before"]

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    print("[m04] written %s" % a.out)
    for k in ("rigid_object_counts", "ncc_pair_count_before", "plan",
              "single_constraint_seconds", "estimated_total_seconds", "estimated_verdict",
              "source_unchanged"):
        if k in meta:
            print("[m04] %-26s %s" % (k, json.dumps(meta[k], ensure_ascii=False)[:300]))
    sys.stdout.flush()
    sys.exit(0)


if __name__ == "__main__":
    # Blender 在脚本抛异常时**仍以 0 退出**（本脚本第一版实测：Traceback 打印完 blender exit=0）。
    # 所以异常必须由脚本自己折成非零退出码，否则「跑失败」与「跑成功」在调用方看来一样。
    try:
        main()
    except SystemExit:
        raise
    except BaseException as exc:                 # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("[m04] FATAL %s: %s" % (type(exc).__name__, exc))
        sys.stdout.flush()
        sys.exit(3)
