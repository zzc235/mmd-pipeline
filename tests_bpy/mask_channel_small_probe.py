# -*- coding: utf-8 -*-
"""掩码通道的**全链路**自验（小场景 = 真实 PMX 的组号与掩码，60 个刚体）。

为什么不直接在 `J_baked.blend`（323 刚体）上 apply：实测逐对象
`bpy.ops.rigidbody.constraint_add()` 每次都触发整场景 depsgraph 求值，那个场景有 12 个
依赖环、300+ 刚体，1500 条约束 10 分钟跑不完（日志 459 MB）。**大场景必须走建场路径**
（`stage_build` 里刚体还没烘焙），事后 apply 只适合小场景/无缓存场景。

本探针验的是 applier 自己的账：位、逐刚体回读、放掉挡错的、补该挡的、幂等、源数据不变、
改动范围（只碰 mmd_rigid 存在的对象）。

用法：
    blender -b --factory-startup -P tests_bpy/mask_channel_small_probe.py -- \
        --pmx <模型.pmx> [--bodies 60]
"""
import argparse
import json
import sys

HERE = r"E:\code\mmdpipe-ai\A4"
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bpy                                    # noqa: E402
from mmdpipe import mask as mask_mod          # noqa: E402
from mmdpipe import pmx as pmx_mod            # noqa: E402
from mmdpipe import stage                     # noqa: E402


def enable_mmd_tools():
    import addon_utils
    for module in ("bl_ext.user_default.mmd_tools", "mmd_tools"):
        try:
            if addon_utils.check(module)[1]:
                return module
            addon_utils.enable(module, default_set=False, persistent=False)
            if addon_utils.check(module)[1]:
                return module
        except Exception:
            continue
    return None


def build_scene(rigids, limit):
    """按真实 PMX 的组号/掩码造 limit 个刚体对象（其它字节都无关紧要）。"""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.ops.rigidbody.world_add()
    rbw = bpy.context.scene.rigidbody_world
    rbw.enabled = False
    rbw.point_cache.frame_start = 1
    rbw.point_cache.frame_end = 1
    made = []
    for i, r in enumerate(rigids[:limit]):
        bpy.ops.mesh.primitive_cube_add(size=0.2, location=(i * 0.5, 0.0, 0.0))
        obj = bpy.context.active_object
        obj.name = "%03d_%s" % (i, r.name[:20])
        obj.mmd_type = "RIGID_BODY"
        obj.mmd_rigid.collision_group_number = r.group
        # PMX 原始位 = 非衝突フラグ（置位 = 不碰）⇒ Blender 属性 = 取反
        obj.mmd_rigid.collision_group_mask = [
            bool((r.mask >> n) & 1 == 0) for n in range(16)]
        bpy.ops.rigidbody.object_add()
        obj.rigid_body.type = "PASSIVE"
        obj.rigid_body.collision_collections = [False] * 20
        made.append(obj)
    return made


def snapshot(bodies):
    return {o.name: (mask_mod.group_of(o), mask_mod.mask_bits(o),
                     mask_mod.collections_of(o)) for o in bodies}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--pmx", required=True)
    ap.add_argument("--bodies", type=int, default=60)
    ap.add_argument("--max-constraints", type=int, default=None)
    args = ap.parse_args(argv)

    out = {"addon": enable_mmd_tools(), "blender": bpy.app.version_string}
    model = pmx_mod.load(args.pmx)
    bodies = build_scene(model.rigids, args.bodies)
    out["bodies"] = len(bodies)
    out["before_state"] = {
        "collections_patterns": len({mask_mod.collections_of(o) for o in bodies}),
        "constraints": len(mask_mod.disabled_pairs(bpy.data.objects)),
    }

    # 人为种一条**挡错的**约束：PMX 说该碰的一对，先挡上，看 applier 会不会放掉
    plan0 = mask_mod.plans(bodies)
    allowed = [(o.name, p) for o in bodies for p in ()]      # 占位，下面按对算
    wrong_pair = None
    for i in range(len(bodies)):
        for j in range(i + 1, len(bodies)):
            a, b = bodies[i], bodies[j]
            if mask_mod.pmx_collides(mask_mod.group_of(a), mask_mod.mask_bits(a),
                                     mask_mod.group_of(b), mask_mod.mask_bits(b)):
                wrong_pair = (a, b)
                break
        if wrong_pair:
            break
    if wrong_pair:
        ncc = bpy.data.objects.new("ncc_seeded_wrong", None)
        bpy.context.scene.collection.objects.link(ncc)
        ncc.mmd_type = mask_mod.NCC_MMD_TYPE
        bpy.context.view_layer.objects.active = ncc
        ncc.select_set(True)
        bpy.ops.rigidbody.constraint_add(type="GENERIC")
        ncc.rigid_body_constraint.object1, ncc.rigid_body_constraint.object2 = wrong_pair
        ncc.rigid_body_constraint.disable_collisions = True
        ncc.select_set(False)
    out["seeded_wrong_constraint"] = bool(wrong_pair)
    out["seeded_pair"] = [o.name for o in wrong_pair] if wrong_pair else None

    before = snapshot(bodies)
    kwargs = {}
    if args.max_constraints is not None:
        kwargs["max_constraints"] = args.max_constraints
    first = stage.apply_collision_masks(**kwargs)
    out["apply_first"] = {k: v for k, v in first.items()
                          if k in ("bodies", "collections_set", "collections_patterns",
                                   "readback_mismatch", "constraints_released",
                                   "constraints_added", "objects_modified",
                                   "objects_touched_outside_mmd_rigid",
                                   "unexpressible", "asymmetric_pairs", "verdict",
                                   "constraints_capped", "pmx_collide", "pmx_nocollide",
                                   "separated_by_bits", "blocked_before")}
    out["skipped_count"] = len(first.get("skipped") or [])
    out["skipped_examples"] = (first.get("skipped") or [])[:3]

    after = snapshot(bodies)
    # 源数据（组号/掩码）不许变；collections 必须变成 mask|own
    out["source_unchanged"] = all(before[n][:2] == after[n][:2] for n in before)
    out["bits_are_mask_or_own"] = all(
        after[n][2] == (after[n][1] | (1 << after[n][0])) for n in after)

    second = stage.apply_collision_masks(**kwargs)
    out["apply_second"] = {"constraints_added": second["constraints_added"],
                           "constraints_released": second["constraints_released"]}
    out["idempotent"] = second["constraints_added"] == 0

    # 场景级：挡错的对是否被放掉、该挡的对是否都挡住
    blocked = mask_mod.disabled_pairs(bpy.data.objects)
    facts = {o.name: (mask_mod.group_of(o), mask_mod.mask_bits(o)) for o in bodies}
    wrong_left = [p for p in blocked
                  if mask_mod.pmx_collides(facts[p[0]][0], facts[p[0]][1],
                                           facts[p[1]][0], facts[p[1]][1])]
    out["blocked_wrong_after"] = len(wrong_left)
    out["blocked_pairs_after"] = len(blocked)
    # 终态判据：**按 PMX 不该碰**的对里，还有多少在场景里"位重叠且没有约束挡"。
    # （原来那个 `needed_pairs_still_overlapping` 条件写反了，数的是"已经不重叠"的，恒为 0。）
    still_bad = 0
    for i in range(len(bodies)):
        for j in range(i + 1, len(bodies)):
            a, b = bodies[i], bodies[j]
            fa, fb = facts[a.name], facts[b.name]
            if mask_mod.pmx_collides(fa[0], fa[1], fb[0], fb[1]):
                continue
            if (mask_mod.collections_of(a) & mask_mod.collections_of(b)) \
                    and mask_mod.pair_key(a.name, b.name) not in blocked:
                still_bad += 1
    out["nocollide_pairs_still_colliding"] = still_bad
    out["sum_equals_nocollide"] = (
        first["separated_by_bits"] + first["constraints_added"] + still_bad
        == first["pmx_nocollide"])

    print("PROBE_JSON " + json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
