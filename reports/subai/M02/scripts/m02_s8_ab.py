"""M02 · S8 阶段 E：Blender 层刚体实验（烘焙回放 / 解烘焙重算）+ 正控。

    blender -b -P m02_s8_ab.py -- <in.blend> <out_dir> <variant> [--allow-baked]

变体：
  A        原样                                         （需 --allow-baked 才能跑 baked 输入）
  B        324 刚体 `collision_collections` 全 0
  C        `rigidbody_world.effector_weights.gravity = 0`
  D        全部刚体 `kinematic = True`
  E        `scene.use_gravity=False` + `scene.gravity=(0,0,0)`
  F        一根下摆刚体物体坐标 +1 cm                   （F 的"恰好 1 cm 全段平移"是回放指纹）
  P0       解烘焙后重算（= S2 的 ±1.5708 基线）
  P1       同 P0，重复一遍（重算的重复性对照）
  P2       解烘焙 + 集合全 0
  P3       解烘焙 + 挪 1 cm（回放指纹的反证）
  P4       解烘焙 + 18 根关节 x 限位 ±1.5708 → ±0.7（= S2 的真 A/B）
  P6       解烘焙 + 限位 → ±0.001 rad（荒谬值：判「限位接没接进解算」）
  P8       解烘焙 + 限位 → ±0.5 rad（Human 选项里那个值会不会咬到摆动）
  P9       解烘焙 + 关掉全部 DISABLE_COLLISIONS 约束（量「掩码错配」的影响量）
  P10      解烘焙 + 只把 11 个 $name_j 占位刚体挪出原生集合（隔离跨骨架耦合）

护栏（今日教训：分不清两种假设的实验必须能拒绝这种输入）：
  输入 `point_cache.is_baked = True` 且变体不是 P* 且没给 `--allow-baked` → **拒绝运行**。
  `P*` 一律先 `bpy.ops.ptcache.free_bake_all()`，并把调用前后缓存状态写进 `meta.json`。
  10 §6 只禁 `bake_all()`（312 刚体段错误记录），`free_bake_all()` 由 D0 授权（D-20261116 13:03 条）。

脚本只产数据、不写 .blend：
  collections.json / frames.jsonl / meta.json
"""
import hashlib
import json
import os
import re
import sys

import bpy

HALF_PI = 1.5707963267948966
TOL = 0.01
NEW_LIMIT = 0.7
PREFIX = re.compile(r"^\d+_J\.")

BAKED_VARIANTS = {"A", "B", "C", "D", "E", "F"}
FREE_BAKE_VARIANTS = {"P0", "P1", "P2", "P3", "P4", "P5", "P6", "P8", "P9", "P10"}

# 这些变体按设计必须改到东西；改动计数全 0 说明脚本分支写错（P10 第一次就是这么空跑的）。
REQUIRE_CHANGE = {"P2", "P3", "P4", "P5", "P6", "P8", "P9", "B", "C", "D", "E", "F"}

DESIGNS = {
    "A": ("不改任何属性；用途是烘焙回放的基线", "无", "无", "与自身重复跑应当逐位相同"),
    "B": ("全部刚体 collision_collections 置全 0（全局关碰撞）", "324", "刚体对象（全部）", "应当改变（若解算真的在跑）"),
    "C": ("rigidbody_world.effector_weights.gravity = 0", "1", "刚体世界", "应当改变"),
    "D": ("全部刚体 kinematic = True", "非 kinematic 的那些", "刚体对象", "应当改变"),
    "E": ("scene.use_gravity=False 且 scene.gravity=(0,0,0)", "1", "场景", "应当改变"),
    "F": ("一根下摆刚体物体坐标 +1 cm", "1", "042_下擺_0_0", "应当改变；若差恰好 0.01 m 且全段恒定 = 回放指纹"),
    "P0": ("解烘焙后重算（±1.5708 基线）", "0", "无", "与 P1 逐位相同"),
    "P1": ("同 P0，重复一遍", "0", "无", "与 P0 逐位相同"),
    "P2": ("解烘焙 + 324 刚体集合全 0", "324", "刚体对象（全部）", "应当改变"),
    "P3": ("解烘焙 + 一根下摆刚体 +1 cm", "1", "042_下擺_0_0", "应当改变，且不得是 0.01 m 恒定平移"),
    "P4": ("解烘焙 + 18 根关节 limit_ang_x ±1.5708 → ±0.7", "18", "rigid_body_constraint（|limit|=π/2 结构筛）", "预注册为「可能不变」"),
    "P5": ("解烘焙 + PASSIVE 留 bit0、ACTIVE 挪 bit1（只断地面接触）", "323", "刚体对象按 rigid_body.type 分", "应当改变（地面接触）"),
    "P6": ("解烘焙 + 18 根关节 limit_ang_x → ±0.001 rad", "18", "同 P4", "应当改变（限位若已接线）"),
    "P8": ("解烘焙 + 18 根关节 limit_ang_x → ±0.5 rad", "18", "同 P4", "机制探针：预期亚毫米级改变"),
    "P9": ("解烘焙 + 全部 DISABLE_COLLISIONS 约束 enabled=False", "视数量", "rigid_body_constraint.type=='DISABLE_COLLISIONS'", "应当改变（掩码若起作用）"),
    "P10": ("解烘焙 + 11 个 $name_j 占位刚体挪到 bit1（隔离跨骨架静态碰撞体）", "11", "对象名含 $name_j", "应当改变（跨骨架耦合非零）"),
}


def parse_argv():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    allow = "--allow-baked" in argv
    rest = [a for a in argv if not a.startswith("--")]
    if len(rest) < 3:
        raise SystemExit("usage: m02_s8_ab.py -- in.blend out_dir <variant> [--allow-baked]")
    return rest[0], rest[1], rest[2].upper(), allow


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cache_state(rbw):
    pc = rbw.point_cache
    return {"is_baked": bool(pc.is_baked), "info": str(pc.info),
            "frame_start": pc.frame_start, "frame_end": pc.frame_end,
            "use_disk_cache": bool(pc.use_disk_cache),
            "is_outdated": bool(pc.is_outdated)}


def main():
    src, out_dir, variant, allow_baked = parse_argv()
    if variant not in BAKED_VARIANTS | FREE_BAKE_VARIANTS:
        raise SystemExit("unknown variant: %s" % variant)

    src_sha_before = sha256_file(src)
    bpy.ops.wm.open_mainfile(filepath=src)
    sc = bpy.context.scene
    rbw = sc.rigidbody_world

    cache_before = cache_state(rbw)
    if cache_before["is_baked"] and variant not in FREE_BAKE_VARIANTS and not allow_baked:
        raise SystemExit(
            "REFUSED: 输入 point_cache.is_baked=True，变体 %s 不是 P*（解烘焙）且未给 --allow-baked。"
            "对 baked 输入做「改参数看轨迹」的实验等于在回放缓存上取数。" % variant)

    free_bake_api = None
    if variant in FREE_BAKE_VARIANTS:
        bpy.ops.ptcache.free_bake_all()
        free_bake_api = "bpy.ops.ptcache.free_bake_all()"
    cache_after_free = cache_state(rbw)

    rigids = [o for o in bpy.data.objects if getattr(o, "rigid_body", None) is not None]
    rigids.sort(key=lambda o: o.name)
    names = [o.name for o in rigids]

    def snapshot():
        out = {}
        for ob in rigids:
            rb = ob.rigid_body
            mmd = getattr(ob, "mmd_rigid", None)
            out[ob.name] = {"cols": [int(v) for v in rb.collision_collections],
                            "type": rb.type, "kinematic": bool(rb.kinematic),
                            "mmd_group": int(mmd.collision_group_number) if mmd else None,
                            "mmd_mask_on": ([i for i, v in enumerate(mmd.collision_group_mask) if v]
                                            if mmd else None)}
        return out

    direct_changed = []          # 不进「集合/运动学/限位/禁碰撞」四类计数的直接改动
    limits_changed = []
    if variant in ("P4", "P6", "P8"):
        new_limit = {"P4": NEW_LIMIT, "P6": 0.001, "P8": 0.5}[variant]
        for ob in bpy.data.objects:
            rbc = getattr(ob, "rigid_body_constraint", None)
            if rbc is None:
                continue
            lo, hi = rbc.limit_ang_x_lower, rbc.limit_ang_x_upper
            if abs(abs(lo) - HALF_PI) < TOL and abs(abs(hi) - HALF_PI) < TOL:
                before = [lo, hi, rbc.use_limit_ang_x]
                rbc.limit_ang_x_lower = -new_limit
                rbc.limit_ang_x_upper = new_limit
                rbc.use_limit_ang_x = True
                limits_changed.append({"object": PREFIX.sub("", ob.name), "before": before,
                                       "after": [rbc.limit_ang_x_lower, rbc.limit_ang_x_upper,
                                                 rbc.use_limit_ang_x]})

    disable_collisions_changed = []
    if variant == "P9":
        for ob in bpy.data.objects:
            rbc = getattr(ob, "rigid_body_constraint", None)
            if rbc is None or getattr(rbc, "type", "") != "DISABLE_COLLISIONS":
                continue
            if getattr(rbc, "enabled", True):
                disable_collisions_changed.append(PREFIX.sub("", ob.name))
                rbc.enabled = False

    before = snapshot()
    if variant in ("B", "P2"):
        zeros = [False] * len(rigids[0].rigid_body.collision_collections)
        for ob in rigids:
            ob.rigid_body.collision_collections = zeros
    elif variant in ("A", "P0", "P1", "P4", "P6", "P8", "P9"):
        pass
    elif variant == "C":
        rbw.effector_weights.gravity = 0.0
        direct_changed.append("effector_weights.gravity")
    elif variant == "D":
        for ob in rigids:
            ob.rigid_body.kinematic = True
    elif variant == "E":
        sc.use_gravity = False
        sc.gravity = (0.0, 0.0, 0.0)
        direct_changed.append("scene.gravity")
    elif variant in ("F", "P3"):
        target = [ob for ob in rigids if ob.name.split("_", 1)[-1] == "下擺_0_0"][0]
        target.location = (target.location[0] + 0.01, target.location[1], target.location[2])
        direct_changed.append("location:" + target.name)
    elif variant == "P10":
        # 只断开 11 个 $name_j 占位刚体与其余刚体的碰撞（它们挪到 bit1，其余留在 bit0）
        for ob in rigids:
            cols = [False] * len(ob.rigid_body.collision_collections)
            cols[1 if "$name_j" in ob.name else 0] = True
            ob.rigid_body.collision_collections = cols
    elif variant == "P5":
        # 只切断「地面」接触，保留角色刚体之间的碰撞：PASSIVE 留 bit0，ACTIVE 挪 bit1。
        # 用来分辨 P2（全关）那 8 mm 到底是「角色互撞」还是「失去地面支撑」。
        for ob in rigids:
            cols = [False] * len(ob.rigid_body.collision_collections)
            cols[0 if ob.rigid_body.type == "PASSIVE" else 1] = True
            ob.rigid_body.collision_collections = cols
    after = snapshot()

    changed = [n for n in names if before[n]["cols"] != after[n]["cols"]]
    # 必须先算再进 REQUIRE_CHANGE 判据：旧版把这一行放在判据之后，导致 D/P9 这类「只改约束或
    # 运动学」的变体在计数时 UnboundLocalError（P9 首次运行就是这个崩的，13:35）。
    kinematic_changed = [n for n in names if before[n]["kinematic"] != after[n]["kinematic"]]
    if variant in REQUIRE_CHANGE:
        counters = {"changed_bodies": len(changed),
                    "kinematic_changed_bodies": len(kinematic_changed),
                    "limits_changed_count": len(limits_changed),
                    "disable_collisions_changed_count": len(disable_collisions_changed),
            "direct_changed": direct_changed,
                    "direct_changed_count": len(direct_changed)}
        if not any(counters.values()):
            raise SystemExit(
                "REFUSED: 变体 %s 应当改到东西，但四个改动计数全为 0 —— 脚本分支写错（空跑）。%s"
                % (variant, counters))
    bitwidth = len(rigids[0].rigid_body.collision_collections)

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "collections.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"variant": variant, "bodies": len(rigids), "bitwidth": bitwidth,
                   "changed_bodies": len(changed), "changed_names": changed,
                   "kinematic_changed_bodies": len(kinematic_changed),
                   "limits_changed_count": len(limits_changed),
                   "disable_collisions_changed_count": len(disable_collisions_changed),
            "direct_changed": direct_changed,
            "placeholder_bodies": sorted(n for n in names if "$name_j" in n),
                   "limits_changed": limits_changed,
                   "before": before, "after": after}, fh, ensure_ascii=False,
                  indent=1, sort_keys=True)
        fh.write("\n")

    fps = sc.render.fps / sc.render.fps_base
    rows = []
    sc.frame_set(sc.frame_start)
    for f in range(sc.frame_start, sc.frame_end + 1):
        sc.frame_set(f)
        rows.append({"frame": f, "pos": {n: [round(v, 6) for v in ob.matrix_world.translation]
                                        for n, ob in zip(names, rigids)}})

    with open(os.path.join(out_dir, "frames.jsonl"), "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    # 解算**之后**再看一次缓存：只验「清之前是 baked」不够——走完这一遍帧之后，
    # 场景设置仍有可能把它重新烘上，于是「自由解算臂」会静默变回回放臂
    # （2号 2026-11-16 15:21 的 A0 v1：240/240 帧逐位相同，成因就是回放缓存）。
    after_step = cache_state(rbw)
    pose_source = "cache_replay" if after_step.get("is_baked") else "fresh_solve"
    refuse_replay = bool(after_step.get("is_baked")) and not allow_baked

    meta = {"task": "M02", "stage": "E-s8", "variant": variant,
            "in_blend": src, "in_blend_sha256_before": src_sha_before,
            "in_blend_sha256_after": sha256_file(src),
            "source_untouched": src_sha_before == sha256_file(src),
            "allow_baked": allow_baked, "free_bake_api": free_bake_api,
            "point_cache_before": cache_before, "point_cache_after_free_bake": cache_after_free,
            "point_cache_after_step": after_step,
            # 读数来源自报：`fresh_solve` 才是「我改了什么、解算看到了什么」；
            # `cache_replay` 意味着这份轨迹是旧解算的回放，谁改都没用（不得引用）。
            "pose_source": pose_source,
            "refused_replay": refuse_replay,
            "bodies": len(rigids), "changed_bodies": len(changed),
            "kinematic_changed_bodies": len(kinematic_changed),
            "limits_changed_count": len(limits_changed),
            "disable_collisions_changed_count": len(disable_collisions_changed),
            "direct_changed": direct_changed,
            "placeholder_bodies": sorted(n for n in names if "$name_j" in n),
            "frames": [sc.frame_start, sc.frame_end], "fps": fps,
            "substeps": rbw.substeps_per_frame, "solver_iterations": rbw.solver_iterations,
            "scene_use_gravity": bool(sc.use_gravity),
            "scene_gravity": [round(v, 6) for v in sc.gravity],
            "effector_gravity": round(rbw.effector_weights.gravity, 6),
            "design": {"what": DESIGNS.get(variant, ("未登记",))[0] if variant in DESIGNS else "未登记",
                       "expected_objects": DESIGNS[variant][1] if variant in DESIGNS else "-",
                       "how_identified": DESIGNS[variant][2] if variant in DESIGNS else "-",
                       "expectation": DESIGNS[variant][3] if variant in DESIGNS else "-"},
            "rows": len(rows), "never_saved_blend": True}
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")

    print("S8 variant=%s bodies=%d changed=%d kin_changed=%d limits_changed=%d rows=%d "
          "baked_before=%s baked_after_free=%s baked_after_step=%s pose_source=%s out=%s"
          % (variant, len(rigids), len(changed), len(kinematic_changed), len(limits_changed),
             len(rows), cache_before["is_baked"], cache_after_free["is_baked"],
             after_step.get("is_baked"), pose_source, out_dir))
    if refuse_replay:
        # 产物已经落盘（轨迹是真的），但它们**是回放**，不许被引用 ⇒ 退出码 3 = CANNOT。
        print("REFUSED 解算之后 point_cache.is_baked 仍为真：这份轨迹是旧解算的回放，"
              "不是「改了什么就发生什么」的读数（未给 --allow-baked）")
        sys.stdout.flush()
        os._exit(3)
    sys.stdout.flush()
    os._exit(0)


main()
