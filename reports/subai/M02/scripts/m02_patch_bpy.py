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
    def __init__(self, reason_code, message):
        Exception.__init__(self, "[%s] %s" % (reason_code, message))
        self.reason_code = reason_code
        self.message = message


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


def mmd_rigid_of(obj):
    """MMD 刚体属性；读不到返回 `None`（**键仍写进 spec**，以便区分「读不到」与「没读过」）。"""
    rig = getattr(obj, "mmd_rigid", None)
    if rig is None:
        return None
    try:
        return {"group": int(rig.group), "mask": int(rig.collision_group_mask),
                "shape": int(rig.shape), "mode": int(rig.mode),
                "mass": _r(rig.mass)}
    except Exception:                                        # noqa: BLE001
        return None


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
    try:
        return {"gravity": [_r(v) for v in world.effector_weights.gravity
                            if isinstance(v, (int, float))] or None,
                "time_scale": _r(getattr(world, "time_scale", 0.0) or 0.0),
                "substeps_per_frame": int(getattr(world, "substeps_per_frame", 0)),
                "solver_iterations": int(getattr(world, "solver_iterations", 0))}
    except Exception:                                        # noqa: BLE001
        return {"unreadable": True}


def create_body_from_spec(spec, arm_obj=None, collection=None):
    """按一条 spec 造出对象（网格 + 父级/父骨 + 世界矩阵 + rigid body 全部属性）。"""
    name = spec["name"]
    if bpy.data.objects.get(name) is not None:
        raise PatchApplyError("PATCH_NAME_EXISTS",
                              "场景里已有同名对象 %r：补丁不许覆盖既有内容" % name)

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
    shape = spec["rigid_body"]["collision_shape"]
    try:
        bpy.ops.rigidbody.object_add(type=shape)
    except Exception as exc:                                 # noqa: BLE001
        raise PatchApplyError("PATCH_RIGIDBODY_ADD_FAILED",
                              "%s 加 rigid body(%s) 失败：%s" % (name, shape, exc))
    rb = getattr(obj, "rigid_body", None)
    if rb is None:
        raise PatchApplyError("PATCH_RIGIDBODY_MISSING", "%s 加了 rigid body 却读不到" % name)

    src = spec["rigid_body"]
    try:
        rb.mass = float(src["mass"])
        rb.friction = float(src["friction"])
        rb.restitution = float(src["restitution"])
        rb.kinematic = bool(src["kinematic"])
        rb.collision_shape = src["collision_shape"]
        rb.collision_collections = tuple(bool(b) for b in src["collision_collections"])
        rb.collision_margin = float(src["collision_margin"])
        rb.linear_damping = float(src["linear_damping"])
        rb.angular_damping = float(src["angular_damping"])
        rb.use_margin = bool(src["use_margin"])
        rb.enabled = bool(src["enabled"])
    except Exception as exc:                                 # noqa: BLE001
        raise PatchApplyError("PATCH_PROPERTY_FAILED",
                              "%s 写 rigid body 属性失败：%s" % (name, exc))
    if spec.get("mmd_type") is not None:
        try:
            obj.mmd_type = spec["mmd_type"]
        except Exception:                                    # noqa: BLE001
            pass                                             # mmd_type 只影响读回对照，记在 soft 层
    bpy.context.view_layer.update()
    return obj
