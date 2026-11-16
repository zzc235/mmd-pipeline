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
    """场景级：按 PMX 语义分桶，并数「Blender 里实际分开」多少。"""
    facts = [(o.name, mask_mod.group_of(o), mask_mod.mask_bits(o)) for o in bodies]
    bits = {name: mask_mod.collision_bits(o) for o, (name, _, _) in zip(bodies, facts)}
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
            if not (bits[name_a] & bits[name_b]):
                sep_bits += 1
            elif mask_mod.pair_key(name_a, name_b) in blocked:
                sep_constraint += 1
    patterns = {}
    for name, value in bits.items():
        patterns["%04x" % value] = patterns.get("%04x" % value, 0) + 1
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
    }


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--blend", required=True)
    ap.add_argument("--apply", action="store_true", help="真的打通道（默认只读前态）")
    args = ap.parse_args(argv)

    bpy.ops.wm.open_mainfile(filepath=args.blend)
    bodies = [o for o in bpy.data.objects if getattr(o, "mmd_type", None) == "RIGID_BODY"]
    out = {"blend": args.blend, "before": scene_state(bodies)}

    if args.apply:
        before_snapshot = snapshot(bodies)
        first = stage.apply_collision_masks()
        out["apply_first"] = {k: v for k, v in first.items()
                              if k not in ("blits_of", "constraints_needed")}
        out["after"] = scene_state(bodies)
        second = stage.apply_collision_masks()
        out["apply_second_constraints_added"] = second["constraints_added"]
        out["source_unchanged"] = snapshot(bodies) == before_snapshot
        out["idempotent"] = second["constraints_added"] == 0
        # 逐刚体回读：与源掩码一致
        bad = [name for name, (group, mask) in snapshot(bodies).items()
               if (mask | (1 << group)) != mask_mod.collision_bits(
                   bpy.data.objects[name])]
        out["readback_exact"] = len(bad) == 0
        out["readback_bad"] = bad[:5]

    print("PROBE_JSON " + json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
