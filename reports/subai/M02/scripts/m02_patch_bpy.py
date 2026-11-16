# -*- coding: utf-8 -*-
"""`m08_extra_bodies_patch_v1` 的 **Blender 侧**实现（读一个对象成 spec / 按 spec 造一个对象）。

只许这一份（`D-186`：交付链上不许两份实现）。两个用户：

| 用户 | 用哪两个函数 |
|---|---|
| `m02_dump_extra_bodies.py --patch-out` | `body_spec()` —— 从旧件读出 12 条 |
| `m02_rebuild_scene_v3.py --patch` | `create_body_from_spec()` + `body_spec()` 回读验回来 |

格式与校验（纯 Python、不碰 `bpy`）在 `m02_patch_format.py`；这里只负责「场景里怎么读、怎么造」。

**fail-closed**：造不出来、父级找不到、重名、rigid body 加不上，一律抛 `PatchApplyError(reason_code)`，
由调用方写进报告并以非 0 退出——绝不静默跳过某一条（少一条就又是 312 那个坑）。
"""

import bpy                                                   # noqa: F401
from mathutils import Matrix                                 # noqa: E402

import m02_patch_format as _fmt                              # noqa: E402

PATCH_VERSION = "m08_extra_bodies_patch_v1"
TOL = 6                                                      # 读出的浮点统一 round 到 6 位


class PatchApplyError(Exception):
    def __init__(self, reason_code, message, detail=None):
        Exception.__init__(self, "[%s] %s" % (reason_code, message))
        self.reason_code = reason_code
        self.message = message
        # 失败时把「已经量到的全部差异」带走，别只留一句摘要：读者要能自己看差多少
        self.detail = detail


# 前缀规则只许一份实现（在 `m02_patch_format` 里），这里直接复用，免得两处漂移
strip_prefix = _fmt.strip_prefix


def _r(v):
    return round(float(v), TOL)


def _matrix_flat(m):
    return [_r(v) for row in m for v in row]


def _flat_matrix(flat):
    if not isinstance(flat, list) or len(flat) != 16:
        raise PatchApplyError("PATCH_MATRIX_BAD", "matrix 需要 16 个数，实际 %r" % (flat,))
    return Matrix([flat[0:4], flat[4:8], flat[8:12], flat[12:16]])


def _enum(value):
    """RNA 枚举读出来可能是字符串也可能是 `_enum_...` 对象，统一成字符串。"""
    try:
        return str(value)
    except Exception:                                        # noqa: BLE001
        return None


def _mmd_type_of(obj):
    try:
        return _enum(obj.mmd_type)
    except Exception:                                        # noqa: BLE001
        return None


MMD_RIGID_FIELDS = ("name", "name_j", "name_e", "collision_group_number",
                    "collision_group_mask", "type", "shape", "bone", "size")


def mmd_rigid_of(obj):
    """MMD 刚体属性（真实的 RNA 字段名，2026-11-16 18:40 探针实测）。

    **以前这里读错名字**（`group`/`mode`/`mass` 根本不存在）⇒ 每条都抛异常、被我写成了 `null`，
    于是「交付件里 12 条都有 mmd_rigid」被读成「都没有」，重建件的通道作用域掉回 312、
    `constraints_needed` 从 10111 变 8499 —— 又是「读不到 ≠ 不存在」。
    现在：读不到**抛异常**（拒绝产出 null），字段名以 `m02_probe_mmd_rigid.py` 的实测为准。
    """
    rig = getattr(obj, "mmd_rigid", None)
    if rig is None:
        return None                                  # 真的没有（不是读失败）
    out = {}
    for field in MMD_RIGID_FIELDS:
        try:
            value = getattr(rig, field)
        except Exception as exc:                     # noqa: BLE001
            raise PatchApplyError("PATCH_MMD_RIGID_UNREADABLE",
                                  "%s 的 mmd_rigid.%s 读不到（%s: %s）——不写 null 冒充「没有」"
                                  % (obj.name, field, type(exc).__name__, exc))
        if field == "collision_group_mask":
            out[field] = [bool(b) for b in value]
        elif field == "size":
            out[field] = [_r(v) for v in value]
        elif field == "collision_group_number":
            out[field] = int(value)
        elif field == "type":
            out[field] = str(value)
        else:
            out[field] = str(value)
    return out


DIGEST_BODY_FIELDS = ("name", "parent_bone", "mass", "kinematic", "collision_shape",
                      "collision_collections", "friction")


def digest_body(obj):
    """`content_digest_v1` 要的那 7 个逐刚体字段（强摘要的原料）。

    与 `body_spec()` 分开是**故意**的：摘要只要物理字段，不要网格和矩阵（那两者是补丁/身份层的事），
    而且这里绝不能因为「读不到」就填默认值——读不到就抛，交给调用方判。
    """
    rb = getattr(obj, "rigid_body", None)
    if rb is None:
        raise PatchApplyError("DIGEST_BODY_NO_RIGID_BODY", "%s 没有 rigid_body" % obj.name)
    try:
        return {
            "name": obj.name,
            "parent_bone": obj.parent_bone or None,
            "mass": _r(rb.mass),
            "kinematic": bool(rb.kinematic),
            "collision_shape": _enum(rb.collision_shape),
            "collision_collections": [int(b) for b in rb.collision_collections],
            "friction": _r(rb.friction),
        }
    except Exception as exc:                                 # noqa: BLE001
        raise PatchApplyError("DIGEST_BODY_FAILED", "%s 逐刚体字段读失败：%s" % (obj.name, exc))


def body_spec(obj):
    """把一个对象读成补丁里的一条（12 个属性全部实测，不填默认值）。"""
    spec = {
        "name": obj.name,
        "name_stripped": strip_prefix(obj.name),
        "type": obj.type,
        "mmd_type": _mmd_type_of(obj),
        "parent": obj.parent.name if obj.parent else None,
        "parent_type": obj.parent.type if obj.parent else None,
        "parent_bone": obj.parent_bone or None,
        "matrix_world": _matrix_flat(obj.matrix_world),
        "matrix_parent_inverse": _matrix_flat(obj.matrix_parent_inverse),
        "location": [_r(v) for v in obj.location],
        "rotation_mode": obj.rotation_mode,
        "rotation_quaternion": [_r(v) for v in obj.rotation_quaternion],
        "scale": [_r(v) for v in obj.scale],
        "dimensions": [_r(v) for v in obj.dimensions],
        "mesh": {"vertices": [[_r(c) for c in v.co] for v in obj.data.vertices],
                 "faces": [[int(i) for i in p.vertices] for p in obj.data.polygons]},
        "mmd_rigid": mmd_rigid_of(obj),
    }
    rb = getattr(obj, "rigid_body", None)
    if rb is None:
        raise PatchApplyError("PATCH_SPEC_NO_RIGID_BODY",
                              "%s 没有 rigid_body，不能当补丁源" % obj.name)
    spec["rigid_body"] = {
        "mass": _r(rb.mass),
        "friction": _r(rb.friction),
        "restitution": _r(rb.restitution),
        "kinematic": bool(rb.kinematic),
        "collision_shape": _enum(rb.collision_shape),
        "collision_collections": [int(b) for b in rb.collision_collections],
        "collision_margin": _r(rb.collision_margin),
        "linear_damping": _r(rb.linear_damping),
        "angular_damping": _r(rb.angular_damping),
        "use_margin": bool(rb.use_margin),
        "enabled": bool(rb.enabled),
    }
    return spec


def ensure_rigidbody_world():
    scene = bpy.context.scene
    if scene.rigidbody_world is None:
        try:
            bpy.ops.rigidbody.world_add()
        except Exception as exc:                             # noqa: BLE001
            raise PatchApplyError("PATCH_RIGIDBODY_WORLD_FAILED",
                                  "rigidbody.world_add 失败：%s" % exc)
    return scene.rigidbody_world


def rigidbody_world_snapshot():
    """场景级物理边界（重力/时间缩放/子步）：补丁不写它，但报告必须记它，便于比对。"""
    world = bpy.context.scene.rigidbody_world
    if world is None:
        return None
    out = {"gravity": None, "time_scale": None, "substeps_per_frame": None,
           "solver_iterations": None, "fields_missing": []}
    for field in ("gravity", "time_scale", "substeps_per_frame", "solver_iterations"):
        try:
            value = getattr(world, field)
        except Exception:                                    # noqa: BLE001
            out["fields_missing"].append(field)
            continue
        if field == "gravity":
            try:
                out["gravity"] = [_r(v) for v in value]
            except Exception:                                # noqa: BLE001
                out["gravity"] = str(value)
        elif field in ("substeps_per_frame", "solver_iterations"):
            out[field] = int(value)
        else:
            out[field] = _r(value)
    return out


def warm_scene(scene=None):
    """读 `matrix_world` 之前的**顺序热身**（`D-223②` / `D-226`）。返回记录，不判。

    为什么需要：同一份件上，「开件后第一次求值」读到的 `matrix_world` 与顺序重算能差
    **1.99 m**（实测 323/323 条，`digest_warmup.json`）。`body_spec()` 里含 `matrix_world`，
    所以补丁回读属于「必须先热身」的那一族。

    为什么**不**用拒绝：断言只对将来的读数生效，已有读数既没记也没法补，会整体变成
    「不可比」——比「可能偏差」更难处理（`D-226`）。所以只记两个独立字段：
    `warmed_up`（读之前有没有走过一次顺序步进）、`first_eval_after_open`（这次是不是开件后首读）。
    """
    scene = scene or bpy.context.scene
    start = int(getattr(scene, "frame_start", 1))
    scene.frame_set(start)          # 第一次求值（把状态初始化出来）
    scene.frame_set(start + 1)      # 顺序走一帧：这才叫「热身」
    scene.frame_set(start)          # 回到读数帧；此时已不是「开件后第一次求值」
    return {"warmed_up": True, "first_eval_after_open": False,
            "evidence": "frame_set(%d) → frame_set(%d) → frame_set(%d)"
                        % (start, start + 1, start)}


def _create_mmd_rigid(spec, arm_obj):
    """用 mmd_tools 自己的算子造 MMD 刚体（唯一一份「造 MMD 刚体」的实现）。

    为什么必须走算子（2026-11-16 18:40 实测）：`stage_build` 里的 `Model.build()` 会读每个
    MMD 刚体对象上的 `mmd_tools_rigid_parent` 约束；手搓一个「有 `mmd_type` 但没有这套记账」的
    对象，会让建场直接 E-05 失败。算子是上游唯一的正确入口（`AGENTS.md` 第一条：先找现成的）。
    """
    hard = spec["mmd_rigid"]
    if arm_obj is None:
        raise PatchApplyError("PATCH_NO_ARMATURE", "%s 需要骨架才能造 MMD 刚体" % spec["name"])
    scene = bpy.context.scene
    for o in bpy.context.selected_objects:
        o.select_set(False)
    bpy.context.view_layer.objects.active = arm_obj
    arm_obj.select_set(True)
    try:
        if arm_obj.mode != "POSE":
            bpy.ops.object.mode_set(mode="POSE")
    except Exception as exc:                                 # noqa: BLE001
        raise PatchApplyError("PATCH_POSE_MODE_FAILED",
                              "进不了 POSE 模式（%s）：%s" % (arm_obj.name, exc))
    for pb in arm_obj.pose.bones:
        pb.select = False                                    # 5.2：选中状态在 PoseBone 上
    bone = hard.get("bone") or ""
    if bone:
        if bone not in arm_obj.pose.bones:
            raise PatchApplyError("PATCH_BONE_MISSING", "%s 的父骨 %r 不在骨架上"
                                  % (spec["name"], bone))
        arm_obj.pose.bones[bone].select = True
    before = set(bpy.data.objects.keys())
    rb_spec = spec["rigid_body"]
    kwargs = dict(
        name_j=hard.get("name_j") or "",
        name_e=hard.get("name_e") or "",
        collision_group_number=int(hard.get("collision_group_number") or 0),
        collision_group_mask=tuple(bool(b) for b in hard.get("collision_group_mask") or []),
        rigid_type=str(hard.get("type") or "0"),
        rigid_shape=str(hard.get("shape") or "BOX"),
        size=tuple(float(v) for v in hard.get("size") or (0.6, 0.6, 0.6)),
        mass=float(rb_spec["mass"]),
        friction=float(rb_spec["friction"]),
        bounce=float(rb_spec["restitution"]),
        linear_damping=float(rb_spec["linear_damping"]),
        angular_damping=float(rb_spec["angular_damping"]),
    )
    # 后台模式下窗口上下文里的 `context.selected_pose_bones` 不随 `pb.select` 变（18:44 实测：
    # 算子走了「没有父骨」那条分支，`mmd_rigid.bone` 空、size 被乘 empty_display_size）。
    # 所以显式用 temp_override 把「这一刻选中的是哪根骨」喂进去。
    override = {"active_object": arm_obj, "object": arm_obj}
    if bone:
        override["selected_pose_bones"] = [arm_obj.pose.bones[bone]]
        override["selected_bones"] = [arm_obj.data.bones[bone]]
    try:
        try:
            with bpy.context.temp_override(**override):
                bpy.ops.mmd_tools.rigid_body_add(**kwargs)
        except TypeError:                                    # 老版本没有 temp_override
            bpy.ops.mmd_tools.rigid_body_add(**kwargs)
    except Exception as exc:                                 # noqa: BLE001
        raise PatchApplyError("PATCH_RIGIDBODY_ADD_FAILED",
                              "%s 用 mmd_tools.rigid_body_add 造失败：%s" % (spec["name"], exc))
    new_names = [n for n in bpy.data.objects.keys() if n not in before]
    if len(new_names) != 1:
        raise PatchApplyError("PATCH_CREATE_AMBIGUOUS",
                              "%s 之后新生成了 %d 个对象：%r（不猜哪个是刚体）"
                              % (spec["name"], len(new_names), new_names[:5]))
    obj = bpy.data.objects[new_names[0]]
    try:
        bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:                                        # noqa: BLE001
        pass
    if obj.name != spec["name"]:
        if bpy.data.objects.get(spec["name"]) is not None:
            raise PatchApplyError("PATCH_NAME_EXISTS",
                                  "改名目标 %r 已被占用" % spec["name"])
        obj.name = spec["name"]                              # 交付件的对象名（带 NNN_ 前缀）
    return obj


def create_body_from_spec(spec, arm_obj=None, collection=None):
    """按一条 spec 造出对象。有 `mmd_rigid` 数据 ⇒ 走 mmd_tools 算子；否则退化成普通刚体。"""
    name = spec["name"]
    if bpy.data.objects.get(name) is not None:
        raise PatchApplyError("PATCH_NAME_EXISTS",
                              "场景里已有同名对象 %r：补丁不许覆盖既有内容" % name)
    if spec.get("mmd_rigid") is not None:
        obj = _create_mmd_rigid(spec, arm_obj)
    else:
        obj = _create_plain_rigid(spec, arm_obj, collection)
    return _finish_body(obj, spec, arm_obj)


def _finish_body(obj, spec, arm_obj):
    """两条路径共用的收尾：重挂父骨 → 世界矩阵 → 刚体属性 → mmd_rigid 参数回写。

    交付件那 12 个的形状是 `parent=骨架 + parent_bone`（不是算子默认的 `rigidbodies` EMPTY），
    所以**无条件**按补丁重挂；`mmd_rigid` 的 `size/name/...` 是**参数**，算子只负责把记账结构
    （含 `mmd_tools_rigid_parent` 约束）建好，参数由补丁写实。
    """
    name = spec["name"]
    parent_name = spec["parent"]
    if parent_name:
        parent = bpy.data.objects.get(parent_name)
        if parent is None:
            raise PatchApplyError("PATCH_PARENT_MISSING",
                                  "%s 的父级 %r 不在场景里" % (name, parent_name))
        obj.parent = parent
        if spec["parent_bone"]:
            if spec["parent_bone"] not in parent.data.bones:
                raise PatchApplyError("PATCH_BONE_MISSING",
                                      "%s 的父骨 %r 不在 %s 上"
                                      % (name, spec["parent_bone"], parent.name))
            obj.parent_type = "BONE"
            obj.parent_bone = spec["parent_bone"]
        else:
            obj.parent_type = "OBJECT"
        obj.matrix_parent_inverse = _flat_matrix(spec["matrix_parent_inverse"])
    else:
        # 无父级（`地面_物理`）：算子会挂到 `rigidbodies` EMPTY 上，必须摘掉
        obj.parent = None
        obj.parent_type = "OBJECT"
        obj.parent_bone = ""
    obj.matrix_world = _flat_matrix(spec["matrix_world"])
    ensure_rigidbody_world()
    rb = getattr(obj, "rigid_body", None)
    if rb is None:
        raise PatchApplyError("PATCH_RIGIDBODY_MISSING", "%s 没有 rigid_body" % name)
    # **顺序要紧**：先写 `mmd_rigid` 参数，再写 `rigid_body` 属性。
    # mmd_tools 的 MMDRigidBody 属性带 update 回调（改 `shape`/`type` 会把
    # `rigid_body.collision_shape`/`kinematic` 一并改回去）——反着写就会「我写了 CONVEX_HULL，
    # 回读却是 SPHERE」（18:43 实测：`地面_物理` 两条都因此判红）。
    hard = spec.get("mmd_rigid")
    rig = getattr(obj, "mmd_rigid", None)
    if hard is not None and rig is not None:
        try:
            rig.name = hard.get("name") or ""
            rig.name_j = hard.get("name_j") or ""
            rig.name_e = hard.get("name_e") or ""
            rig.collision_group_number = int(hard.get("collision_group_number") or 0)
            rig.collision_group_mask = tuple(bool(b) for b in
                                             hard.get("collision_group_mask") or [])
            rig.type = str(hard.get("type") or "0")
            rig.shape = str(hard.get("shape") or "BOX")
            rig.bone = hard.get("bone") or ""
            rig.size = tuple(float(v) for v in hard.get("size") or (0.6, 0.6, 0.6))
        except Exception as exc:                             # noqa: BLE001
            raise PatchApplyError("PATCH_MMD_RIGID_WRITE_FAILED",
                                  "%s 回写 mmd_rigid 参数失败：%s" % (name, exc))
    src = spec["rigid_body"]
    try:
        rb.kinematic = bool(src["kinematic"])
        rb.collision_shape = src["collision_shape"]           # mmd_tools 只给 SPHERE/BOX/CAPSULE
        rb.collision_collections = tuple(bool(b) for b in src["collision_collections"])
        rb.use_margin = bool(src["use_margin"])
        rb.collision_margin = float(src["collision_margin"])
        rb.mass = float(src["mass"])
        rb.friction = float(src["friction"])
        rb.restitution = float(src["restitution"])
        rb.linear_damping = float(src["linear_damping"])
        rb.angular_damping = float(src["angular_damping"])
        rb.enabled = bool(src["enabled"])
    except Exception as exc:                                 # noqa: BLE001
        raise PatchApplyError("PATCH_PROPERTY_FAILED",
                              "%s 写 rigid body 属性失败：%s" % (name, exc))
    # 最后才落 `mmd_type`：交付件里 11 个占位体是 `RIGID_BODY`（在通道作用域内），
    # `地面_物理` 是 `NONE`（**不在**作用域，单列为例外）。算子上来一律设成 RIGID_BODY，
    # 于是地面也被算进去 —— 18:45 实测：那样 `needed` 会多 36 对（10147 而不是 10111）、
    # `collections_patterns` 31 而不是 30。作用域是**边界条件**，必须照交付件落回去。
    if spec.get("mmd_type") is not None:
        try:
            obj.mmd_type = spec["mmd_type"]
        except Exception as exc:                             # noqa: BLE001
            raise PatchApplyError("PATCH_MMD_TYPE_FAILED",
                                  "%s 写 mmd_type=%r 失败：%s"
                                  % (name, spec["mmd_type"], exc))
    bpy.context.view_layer.update()
    return obj


def _create_plain_rigid(spec, arm_obj=None, collection=None):
    """没有 mmd_rigid 数据时的退化路径：自建网格 + Blender 刚体（不是 MMD 刚体）。"""
    name = spec["name"]
    me = bpy.data.meshes.new(name + "__patch_mesh")
    verts = [tuple(float(c) for c in v) for v in spec["mesh"]["vertices"]]
    faces = [tuple(int(i) for i in f) for f in spec["mesh"]["faces"]]
    try:
        me.from_pydata(verts, [], faces)
        me.update()
    except Exception as exc:                                 # noqa: BLE001
        raise PatchApplyError("PATCH_MESH_FAILED", "%s 建网格失败：%s" % (name, exc))

    obj = bpy.data.objects.new(name, me)
    target = collection
    if target is None and arm_obj is not None and arm_obj.users_collection:
        target = arm_obj.users_collection[0]
    (target or bpy.context.scene.collection).objects.link(obj)

    if spec["parent"]:
        parent = bpy.data.objects.get(spec["parent"])
        if parent is None:
            raise PatchApplyError("PATCH_PARENT_MISSING",
                                  "%s 的父级 %r 不在场景里" % (name, spec["parent"]))
        obj.parent = parent
        if spec["parent_bone"]:
            if spec["parent_bone"] not in parent.data.bones:
                raise PatchApplyError("PATCH_BONE_MISSING",
                                      "%s 的父骨 %r 不在 %s 上"
                                      % (name, spec["parent_bone"], parent.name))
            obj.parent_bone = spec["parent_bone"]
        obj.matrix_parent_inverse = _flat_matrix(spec["matrix_parent_inverse"])

    obj.rotation_mode = spec["rotation_mode"]
    obj.matrix_world = _flat_matrix(spec["matrix_world"])

    ensure_rigidbody_world()
    for o in bpy.context.selected_objects:
        o.select_set(False)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    try:
        # `rigidbody.object_add(type=...)` 的 `type` 是 **ACTIVE/PASSIVE**（刚体角色），
        # 不是碰撞形状 —— 实测传 "BOX" 会报 `enum "BOX" not found in ('ACTIVE', 'PASSIVE')`。
        bpy.ops.rigidbody.object_add(type="ACTIVE")
    except Exception as exc:                                 # noqa: BLE001
        raise PatchApplyError("PATCH_RIGIDBODY_ADD_FAILED",
                              "%s 加 rigid body 失败：%s" % (name, exc))
    if getattr(obj, "rigid_body", None) is None:
        raise PatchApplyError("PATCH_RIGIDBODY_MISSING", "%s 加了 rigid body 却读不到" % name)
    bpy.context.view_layer.update()
    return obj
