# -*- coding: utf-8 -*-
"""掩码通道的**场景级**自验探针（spec §4 的 1/1c/2/3/4/5/6，跑在真 .blend 上）。

用法：
    blender -b --factory-startup -P tests_bpy/mask_channel_probe.py -- --blend <path> [--apply]

做的事（只读源数据，不写 .blend）：

1. **前态**：逐刚体读 `mmd_rigid`，按 PMX 语义算「总共多少对 / 该碰多少 / 不该碰多少」，
   再算 Blender 里现在实际分开多少（不共享位 + 有 DISABLE_COLLISIONS 约束）；
2. **打通道**：`stage.apply_collision_masks()`；
3. **后态**：位型数、约束数、读回一致、`constraints_added`；
4. **幂等**：再调一次，`constraints_added` 必须为 0；
5. **源数据未改**：跑前跑后逐刚体快照相同。
"""
import argparse
import itertools
import json
import sys

HERE = r"E:\code\mmdpipe-ai\A4"
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bpy                                    # noqa: E402
from mmdpipe import mask as mask_mod          # noqa: E402
from mmdpipe import stage                     # noqa: E402


def snapshot(bodies):
    return {o.name: (mask_mod.group_of(o), mask_mod.mask_bits(o)) for o in bodies}


def scene_state(bodies):
    """场景级：**读实际状态**（不是按掩码推算的"应该有"）。

    2026-11-16 自报：本函数第一版把 `bits` 算成 `mask|own`（**推算**），于是「位型 30 种、
    已分开 31797 对」——那不是场景里的状态，是我们打算写进去的状态。仪器必须读场景：
    `rigid_body.collision_collections` 与已存在的 `disable_collisions` 约束。
    """
    facts = [(o.name, mask_mod.group_of(o), mask_mod.mask_bits(o)) for o in bodies]
    actual = {o.name: mask_mod.collections_of(o) for o in bodies}      # 读场景
    blocked = mask_mod.disabled_pairs(bpy.data.objects)
    total = collide = 0
    sep_bits = sep_constraint = 0
    disallowed = 0
    for i in range(len(facts)):
        for j in range(i + 1, len(facts)):
            name_a, group_a, mask_a = facts[i]
            name_b, group_b, mask_b = facts[j]
            total += 1
            want = mask_mod.pmx_collides(group_a, mask_a, group_b, mask_b)
            collide += 1 if want else 0
            if want:
                continue
            disallowed += 1
            if not (actual[name_a] & actual[name_b]):
                sep_bits += 1
            elif mask_mod.pair_key(name_a, name_b) in blocked:
                sep_constraint += 1
    patterns = {}
    for name, value in actual.items():
        patterns["%04x" % value] = patterns.get("%04x" % value, 0) + 1
    # 已存在的约束是不是**方向对**：被挡的对里，有多少是 PMX 说"该碰"的？
    # mmd_tools 的 buildRigids() 用 `if not ignore: continue` 读属性，而属性 True 表示
    # "与该组碰"（见 mmdpipe/mask.py 的证据链）——若两者真的反了，这里会数出一批
    # "本该死碰却被挡掉"的对。这是可测的，不靠断言。
    by_name = {name: (group, mask) for name, group, mask in facts}
    blocked_total = blocked & set(itertools.combinations(sorted(by_name), 2))
    blocked_wrong = []
    blocked_right = 0
    for a, b in blocked_total:
        group_a, mask_a = by_name[a]
        group_b, mask_b = by_name[b]
        if mask_mod.pmx_collides(group_a, mask_a, group_b, mask_b):
            blocked_wrong.append((a, b))
        else:
            blocked_right += 1
    return {
        "rigid_objects": len(bodies),
        "pairs_total": total,
        "pmx_collide": collide,
        "pmx_nocollide": disallowed,
        "separated_by_bits": sep_bits,
        "separated_by_constraint": sep_constraint,
        "separated": sep_bits + sep_constraint,
        "collection_patterns": len(patterns),
        "collection_pattern_detail": patterns,
        "disable_collisions_constraints": len(blocked),
        "pairs_blocked_by_constraint": len(blocked_total),
        "blocked_and_should_collide": len(blocked_wrong),
        "blocked_wrong_examples": [list(p) for p in blocked_wrong[:5]],
        "blocked_and_should_not_collide": blocked_right,
    }


def object_census():
    """按 `mmd_type` 数对象 + 数带 `disable_collisions` 的约束（两者分开报）。"""
    by_type = {}
    flagged = {}
    for obj in bpy.data.objects:
        kind = getattr(obj, "mmd_type", None) or "<no mmd_type>"
        by_type[kind] = by_type.get(kind, 0) + 1
        con = getattr(obj, "rigid_body_constraint", None)
        if con is not None and getattr(con, "disable_collisions", False):
            flagged[kind] = flagged.get(kind, 0) + 1
    return {"objects_by_mmd_type": by_type, "disable_collisions_by_type": flagged}


def enable_mmd_tools():
    """`mmd_type` / `mmd_rigid` 这些属性是 mmd_tools 的 PropertyGroup 挂上去的。

    2026-11-16 实测：`--factory-startup` 下不启用插件，`getattr(o, "mmd_type", None)`
    永远拿不到 → "刚体 0 个"。这是个**假空场景**，不是"场景里没有刚体"——探针必须先
    启用插件再数，否则一次 0 会把整条验收读成"没有东西可接"。
    """
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


def rigid_objects():
    # 与 stage.collision_bodies() 同一取法（`mmd_type` 会漏掉 地面_物理 这类对象）
    return stage.collision_scope()[0]


def constraint_census():
    """把"挡掉碰撞"的两种载体分开数：ncc 空物体 / 带 disable_collisions 的关节。"""
    ncc = 0
    joints = 0
    for obj in bpy.data.objects:
        con = getattr(obj, "rigid_body_constraint", None)
        if con is None or not getattr(con, "disable_collisions", False):
            continue
        if getattr(obj, "mmd_type", None) == mask_mod.NCC_MMD_TYPE:
            ncc += 1
        else:
            joints += 1
    return {"ncc_objects": ncc, "joints_with_disable_collisions": joints}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--blend", required=True)
    ap.add_argument("--apply", action="store_true", help="真的打通道（默认只读前态）")
    args = ap.parse_args(argv)

    bpy.ops.wm.open_mainfile(filepath=args.blend)
    out = {"blend": args.blend, "addon": enable_mmd_tools()}
    bodies = rigid_objects()
    wide = [o for o in bpy.data.objects
            if getattr(o, "rigid_body", None) is not None
            and getattr(o, "mmd_rigid", None) is not None]
    out["census"] = object_census()
    # 两个宇宙都报，**都带标签**（D-20261116-133）：1c 的等式只在 U323 成立
    out["universe_u323"] = scene_state(bodies)
    out["universe_u323"].update(constraint_census())
    out["universe_u324"] = scene_state(wide)
    out["rigid_object_set_diff"] = {
        "only_by_rigid_body": [o.name for o in wide if o not in bodies],
        "only_by_mmd_type": [o.name for o in bodies if o not in wide],
    }
    out["exception_bodies"] = stage.exception_rows(bodies, [o for o in wide if o not in bodies])

    if args.apply:
        before_snapshot = snapshot(bodies)
        # **必须先关刚体世界再动手**：新建/改动约束会让 depsgraph 把整条 point cache
        # 重算一遍（实测：`J_baked` 上开跑几秒钟日志涨到 459 MB、CPU 1780 s 还没停）。
        # 这一步只是关掉求值，不改任何刚体数据。
        rbw = bpy.context.scene.rigidbody_world
        was_enabled = None if rbw is None else rbw.enabled
        was_range = None
        if rbw is not None:
            rbw.enabled = False
            # 还要把缓存帧窗压到 1 帧：只关 enabled 实测**拦不住** point cache 重算
            # （新建约束会让 depsgraph 把整条 cache 重新烘一遍，日志能涨到 459 MB）。
            was_range = (rbw.point_cache.frame_start, rbw.point_cache.frame_end)
            rbw.point_cache.frame_start = 1
            rbw.point_cache.frame_end = 1
        bpy.context.scene.frame_set(1)
        try:
            first = stage.apply_collision_masks()
        finally:
            if rbw is not None:
                if was_enabled is not None:
                    rbw.enabled = was_enabled
                if was_range is not None:
                    rbw.point_cache.frame_start, rbw.point_cache.frame_end = was_range
        out["rbw_disabled_during_apply"] = True
        out["apply_first"] = {k: v for k, v in first.items()
                              if k not in ("bits_of", "constraints_needed")}
        out["after"] = scene_state(bodies)
        out["after"].update(constraint_census())
        if rbw is not None:
            rbw.enabled = False
        second = stage.apply_collision_masks()
        if rbw is not None and was_enabled is not None:
            rbw.enabled = was_enabled
        out["apply_second_constraints_added"] = second["constraints_added"]
        out["source_unchanged"] = snapshot(bodies) == before_snapshot
        out["idempotent"] = second["constraints_added"] == 0
        bad = [name for name, (group, mask) in snapshot(bodies).items()
               if (mask | (1 << group)) != mask_mod.collision_bits(
                   bpy.data.objects[name])]
        out["readback_exact"] = len(bad) == 0
        out["readback_bad"] = bad[:5]

    print("PROBE_JSON " + json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
