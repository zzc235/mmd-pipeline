# -*- coding: utf-8 -*-
"""Blender 碰撞位语义实测（spec §2.5：不许拿理解当前提）。

三个刚体 + 一组对照，跑 40 帧，看谁真的挡住了谁：

* `G1` 被动块（passive）在 x=0，collections = bit1
* `D1` 动态块（active） 在 G1 上方，collections = bit1      → 共享 bit1
* `G2` 被动块在 x=5，collections = bit2
* `D2` 动态块在 G2 上方，collections = bit1                 → 与 G2 不共享任何位
* `G3` 被动块在 x=10，collections = bit1+bit2
* `D3` 动态块在 G3 上方，collections = bit1                 → 与 G3 共享 bit1

判定：
  D1 停在 G1 上、D2 穿过 G2 掉下去 ⇒ **共享位即碰撞**（交集语义）
  D3 停住 ⇒ 一侧有位就够（不是"必须双向声明"）
用法：
  blender -b --factory-startup -P mask_semantics_probe.py
"""
import json
import sys

import bpy


def make_block(name, loc, collections, active):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc)
    obj = bpy.context.active_object
    obj.name = name
    bpy.ops.rigidbody.object_add()
    body = obj.rigid_body
    body.type = "ACTIVE" if active else "PASSIVE"
    body.collision_shape = "BOX"
    body.mass = 1.0
    body.friction = 0.5
    body.restitution = 0.0
    # 只留给定的位（默认是 bit0 全开之类，必须显式清干净）
    flags = [False] * 16
    for i in collections:
        flags[i] = True
    body.collision_collections = flags
    return obj


def reset():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    world = bpy.context.scene.rigidbody_world
    if world is not None:
        # 重新建一个干净的刚体世界
        bpy.ops.rigidbody.world_remove()
    bpy.ops.rigidbody.world_add()
    world = bpy.context.scene.rigidbody_world
    world.substeps_per_frame = 10
    world.solver_iterations = 20
    world.point_cache.frame_start = 1
    world.point_cache.frame_end = 60
    return world


def run(frames=40):
    scene = bpy.context.scene
    scene.frame_set(1)
    for f in range(1, frames + 1):
        scene.frame_set(f)


def drop_test(collections_of, label):
    """跑一次：两个配置相同的动态块落到两个不同 collections 的被动块上。"""
    reset()
    g1 = make_block("G1", (0.0, 0.0, 0.0), [1], active=False)
    d1 = make_block("D1", (0.0, 0.0, 3.0), collections_of, active=True)
    g2 = make_block("G2", (5.0, 0.0, 0.0), [2], active=False)
    d2 = make_block("D2", (5.0, 0.0, 3.0), collections_of, active=True)
    run()
    return {
        "label": label,
        "D1_z": round(d1.matrix_world.translation.z, 3),
        "D2_z": round(d2.matrix_world.translation.z, 3),
        "G1_z": round(g1.matrix_world.translation.z, 3),
        "blocked_by_shared_bit": d1.matrix_world.translation.z > 0.3,
        "passed_through_disjoint": d2.matrix_world.translation.z < -0.3,
    }


def main():
    out = {"blender": bpy.app.version_string}
    # (A) 动态块 = bit1：与 G1(bit1) 共享 → 应挡住；与 G2(bit2) 不共享 → 应穿过
    out["shared_vs_disjoint"] = drop_test([1], "dynamic=bit1 vs passive bit1 / bit2")
    # (B) 动态块 = bit1+bit2：两侧都共享 → 都该挡住（一侧有位就够？）
    reset()
    g1 = make_block("G1", (0.0, 0.0, 0.0), [1], active=False)
    d1 = make_block("D1", (0.0, 0.0, 3.0), [1, 2], active=True)
    g2 = make_block("G2", (5.0, 0.0, 0.0), [2], active=False)
    d2 = make_block("D2", (5.0, 0.0, 3.0), [1, 2], active=True)
    run()
    out["one_side_bit_enough"] = {
        "label": "dynamic=bit1+bit2 vs passive bit1 / bit2",
        "D1_z": round(d1.matrix_world.translation.z, 3),
        "D2_z": round(d2.matrix_world.translation.z, 3),
        "both_blocked": (d1.matrix_world.translation.z > 0.3
                         and d2.matrix_world.translation.z > 0.3),
    }
    # (C) 全 0 位 vs 全 1 位：单元级判据的机器版
    reset()
    a = make_block("A_zero", (0.0, 0.0, 0.0), [0], active=False)
    b = make_block("B_all", (5.0, 0.0, 0.0), list(range(16)), active=False)
    out["bits_snapshot"] = {
        "A_zero": [bool(x) for x in a.rigid_body.collision_collections],
        "B_all": [bool(x) for x in b.rigid_body.collision_collections],
        "distinct": (list(a.rigid_body.collision_collections)
                     != list(b.rigid_body.collision_collections)),
    }
    out["rna_description"] = (
        bpy.types.RigidBodyObject.bl_rna.properties["collision_collections"].description)
    print("PROBE_JSON " + json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
