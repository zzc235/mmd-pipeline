# -*- coding: utf-8 -*-
"""正控/反控：复制出来的 ncc 约束**真的在挡碰撞**吗？（行为测，不是读标志位）

为什么不能用「`disable_collisions` 读回来是 True」当证据：今天已经栽过一次同形的坑——
标志位对了、行为不对的东西满项目都是。这里直接让 Bullet 解算：

    地面 G（被动，组 1，掩码只允许组 1）  ⇒ 位 {1}
    P（主动，组 0，掩码允许 {0,1}）        ⇒ 位 {0,1}；PMX 语义 G×P **不该碰**（G 不允许组 0）
    Q（主动，组 1，掩码允许 {0,1}）        ⇒ 位 {0,1}；PMX 语义 G×Q **该碰**

`P` 与 `G` 的位是重叠的（都含 bit1），所以必须在**约束**这一层把它们分开：

    预期 P 穿过地面继续下落（约束生效）      ← 正控：约束必须起作用
    预期 Q 停在地面上（没有约束，照常碰撞）  ← 反控：位还在、碰撞没被一起关掉

两条路各跑一遍（`template_copy` / `ops`），**两条路的行为必须一致**——一致性才是"复制路径
和逐条 ops 等价"的证据，不是"没报错"。

用法：
    blender -b --factory-startup -P tests_bpy/mask_template_copy_probe.py
"""
import json
import sys
import time

HERE = r"E:\code\mmdpipe-ai\A4"
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bpy                                    # noqa: E402
from mmdpipe import mask as mask_mod          # noqa: E402
from mmdpipe import stage                     # noqa: E402

FRAMES = 60
GROUND_Z = 1.0
START_Z = 3.0


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


def make_body(name, group, mask_bits, location, *, passive=False,
              size=(1.0, 1.0, 0.4)):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = size
    obj.mmd_type = "RIGID_BODY"
    obj.mmd_rigid.collision_group_number = group
    # 场景里存的是「与该组碰」（True = 碰），PMX 原始位是取其反
    obj.mmd_rigid.collision_group_mask = [
        bool((mask_bits >> n) & 1) for n in range(16)]
    bpy.ops.rigidbody.object_add()
    obj.rigid_body.type = "PASSIVE" if passive else "ACTIVE"
    obj.rigid_body.mass = 1.0
    obj.rigid_body.collision_collections = [False] * 20   # 通道会写
    return obj


def seed_template():
    """放一条不指向任何一对的空 ncc，作为复制模板（mmd_tools 的形状）。"""
    obj = bpy.data.objects.new("ncc_template", None)
    bpy.context.scene.collection.objects.link(obj)
    obj.mmd_type = mask_mod.NCC_MMD_TYPE
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.rigidbody.constraint_add(type="GENERIC")
    obj.rigid_body_constraint.disable_collisions = True
    obj.select_set(False)
    return obj


def build():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.ops.rigidbody.world_add()
    rbw = bpy.context.scene.rigidbody_world
    rbw.enabled = True
    rbw.substeps_per_frame = 10
    rbw.solver_iterations = 20
    rbw.point_cache.frame_start = 1
    rbw.point_cache.frame_end = FRAMES + 1
    ground = make_body("G", 1, 1 << 1, (0.0, 0.0, GROUND_Z),
                       passive=True, size=(6.0, 6.0, 0.2))
    p = make_body("P_should_pass", 0, (1 << 0) | (1 << 1), (-1.2, 0.0, START_Z))
    q = make_body("Q_should_stop", 1, (1 << 0) | (1 << 1), (1.2, 0.0, START_Z))
    return ground, p, q


def run(path):
    ground, p, q = build()
    template = seed_template()
    t0 = time.perf_counter()
    try:
        wired = stage.apply_collision_masks(constraint_creation=path)
    except Exception as exc:                      # 复制路不可用要看得见
        return {"path": path, "error": "%s: %s" % (type(exc).__name__, exc)}
    seconds = time.perf_counter() - t0
    # 模板本身不指向任何一对，用完删掉，免得它混进"场景里有几条约束"的账
    bpy.data.objects.remove(template, do_unlink=True)
    bpy.context.scene.frame_set(1)
    for frame in range(2, FRAMES + 2):
        bpy.context.scene.frame_set(frame)
    return {
        "path": path,
        "seconds": round(seconds, 3),
        "constraint_creation": wired.get("constraint_creation"),
        "constraints_needed": wired.get("constraints_needed"),
        "constraints_added": wired.get("constraints_added"),
        "constraints_capped": wired.get("constraints_capped"),
        "skipped_count": wired.get("skipped_count"),
        "verdict": wired.get("verdict"),
        "verdict_reasons": wired.get("verdict_reasons"),
        "P_z": round(p.matrix_world.translation.z, 4),
        "Q_z": round(q.matrix_world.translation.z, 4),
        "G_z": round(ground.matrix_world.translation.z, 4),
        "P_passed": p.matrix_world.translation.z < GROUND_Z - 0.5,
        "Q_stopped": q.matrix_world.translation.z > GROUND_Z - 0.5,
        "constraints_in_scene": len(mask_mod.disabled_pairs(bpy.data.objects)),
    }


def provenance():
    """用的是哪棵树的代码：路径 + sha256（`sys.path.insert` 会静默压掉别的树）。"""
    import hashlib
    import os
    out = {"blender": bpy.app.version_string}
    for name in ("mmdpipe.stage", "mmdpipe.mask"):
        path = getattr(sys.modules.get(name), "__file__", None)
        digest = None
        if path and os.path.exists(path):
            with open(path, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
        out[name] = {"file": path, "sha256": digest}
    return out


def main():
    out = {"addon": enable_mmd_tools(), "provenance": provenance(),
           "frames": FRAMES}
    out["runs"] = [run("template_copy"), run("ops")]
    ok = []
    for item in out["runs"]:
        ok.append(bool(item.get("constraint_creation") == item["path"]
                       and item.get("constraints_added") == 1
                       and item.get("P_passed") and item.get("Q_stopped")))
    out["both_paths_effective"] = all(ok)
    # 两条路行为一致 = 复制路径与逐条 ops 等价
    out["paths_agree"] = (len({(r.get("P_passed"), r.get("Q_stopped"))
                               for r in out["runs"]}) == 1)
    print("PROBE_JSON " + json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    # Blender 把脚本异常吞成 exit 0（`D-135`）：自己接住并给非零码。
    try:
        main()
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        sys.exit(3)
