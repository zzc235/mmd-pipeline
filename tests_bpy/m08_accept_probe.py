# -*- coding: utf-8 -*-
"""M08 验收的**采集器**（在 Blender 里跑，只采事实，不判）。

判据在 `coordination/acceptance.py`（纯 Python）：本脚本打印一行
`FACTS_JSON {...}`，那边逐行判 PASS/FAIL/CANNOT 并写产物。

采集口径（按 AGENTS.md 第一条，能复用就复用）：

* 刚体数两个宇宙都报：`rigids_u323` = `stage.rigid_bodies()`（`mmd_type == RIGID_BODY`），
  `rigids_u324` = `rigid_body is not None`（含 `地面_物理` 这类手工对象）；
* 通道判词**直接吃** `stage.stage_mask()`，不在这里重算位/约束；
* 缓存判词**直接吃** `mmdpipe.cache_state.evaluate()`，不在这里重写三分法；
* 三次 sha 独立读三遍（"验收期间没人在写这个文件"）。

用法：
    blender -b --factory-startup -P tests_integration/m08_accept_probe.py -- \
        --blend <场景.blend> [--out facts.json]

退出码（`D-135`：Blender 会把脚本异常吞成 0，所以这里自己给非零码）：
    0  采集完成
    3  采集过程出错（`FACTS_JSON` 里带 `errors`，判据那边会因此 FAIL）
"""
import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bpy                                            # noqa: E402
from mmdpipe import cache_state as cache_mod          # noqa: E402
from mmdpipe import stage                             # noqa: E402

SKIRT_PREFIX = "下擺_"


def sha_reads(path, times=3):
    reads = []
    for _ in range(max(1, int(times))):
        with open(path, "rb") as fh:
            reads.append(hashlib.sha256(fh.read()).hexdigest())
    return reads


def provenance():
    out = {"blender": bpy.app.version_string}
    for name in ("mmdpipe.stage", "mmdpipe.mask", "mmdpipe.cache_state"):
        path = getattr(sys.modules.get(name), "__file__", None)
        digest = None
        if path and os.path.exists(path):
            with open(path, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
        out[name] = {"file": path, "sha256": digest}
    return out


def object_census():
    census = {}
    for obj in bpy.data.objects:
        key = getattr(obj, "mmd_type", None) or "NONE"
        census[key] = census.get(key, 0) + 1
    return census


def counts():
    u323 = len(stage.rigid_bodies())
    u324 = sum(1 for obj in bpy.data.objects if getattr(obj, "rigid_body", None) is not None)
    placeholders = sorted(obj.name for obj in bpy.data.objects if "$" in obj.name)
    bones = 0
    skirt_0 = 0
    skirt_11 = 0
    for arm in bpy.data.objects:
        if getattr(arm, "type", None) != "ARMATURE":
            continue
        for bone in arm.data.bones:
            bones += 1
            if bone.name.startswith(SKIRT_PREFIX + "0_"):
                skirt_0 += 1
            elif bone.name.startswith(SKIRT_PREFIX + "11_"):
                skirt_11 += 1
    vertices = sum(len(obj.data.vertices) for obj in bpy.data.objects
                   if getattr(obj, "type", None) == "MESH" and obj.data is not None)
    return {"rigids_u323": u323, "rigids_u324": u324,
            "placeholders": len(placeholders), "placeholder_names": placeholders[:12],
            "bones": bones, "vertices": vertices,
            "skirt_bones_0": skirt_0, "skirt_bones_11": skirt_11}


def cache_record():
    """缓存三项事实 → 交给 `cache_state.evaluate()` 判（不在本脚本里写三分法）。"""
    world = bpy.context.scene.rigidbody_world
    if world is None:
        return {"record": {"exists": True, "has_physics": False},
                "verdict": cache_mod.evaluate({"exists": True,
                                               "has_physics": False})["verdict"]}
    cache = world.point_cache
    record = {"exists": True, "has_physics": True,
              "is_baked": bool(cache.is_baked), "is_outdated": bool(cache.is_outdated),
              "bodies": world.collection and len(world.collection.objects) or 0,
              "use_disk_cache": bool(cache.use_disk_cache)}
    judged = cache_mod.evaluate(record)
    return {"record": record, "verdict": judged["verdict"],
            "reason": judged.get("reason", "")}


def mask_facts():
    report = stage.stage_mask()
    return {key: report.get(key) for key in (
        "rigids", "verdict", "verdict_reasons", "constraints_capped", "skipped_count",
        "blocked_and_should_collide", "nocollide_pairs_still_colliding",
        "unexpressible_pairs", "declared_pairs", "blocked_pairs", "coverage",
        "collections_non_default", "readback_mismatch_names", "wired_record",
        "scope_bodies", "exception_bodies")}


def collect(blend):
    facts = {"blend": blend, "errors": []}
    facts["provenance"] = provenance()
    try:
        facts["sha256_reads"] = sha_reads(blend, 3)
    except OSError as exc:
        facts["errors"].append("sha 读不到：%s" % exc)
        facts["sha256_reads"] = []
    try:
        bpy.ops.wm.open_mainfile(filepath=blend)
    except Exception as exc:
        facts["errors"].append("打不开 .blend：%s" % exc)
        return facts
    facts["scene"] = bpy.context.scene.name
    facts["objects_by_mmd_type"] = object_census()
    try:
        facts.update(counts())
    except Exception as exc:
        facts["errors"].append("数场景构成失败：%s" % exc)
    try:
        cache = cache_record()
        facts["cache"] = cache["record"]
        facts["cache_verdict"] = cache["verdict"]
    except Exception as exc:
        facts["errors"].append("缓存状态读不出来：%s" % exc)
    try:
        facts["mask"] = mask_facts()
    except Exception as exc:
        facts["errors"].append("stage_mask 失败：%s" % exc)
    return facts


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--blend", required=True)
    ap.add_argument("--out", default=None, help="把 FACTS_JSON 也写一份到这个文件")
    args = ap.parse_args(argv)

    facts = collect(args.blend)
    payload = json.dumps(facts, ensure_ascii=False)
    print("FACTS_JSON " + payload)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("FACTS_JSON " + payload + "\n")
    return 3 if facts.get("errors") else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        sys.exit(3)
