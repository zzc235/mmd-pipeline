"""Blender 侧的各阶段实现。依赖 bpy。

每个阶段都返回 StageResult：数字 + 问题清单。阶段内不打印结论，
是否放过由调用方（runner）按 block 判定。
"""
from __future__ import annotations

import os
import subprocess
import time

import bpy
from mathutils import Vector

from . import preset as preset_mod
from . import mask as mask_mod
from .report import BLOCK, INFO, WARN, StageResult

# HSR 插件暴露的场景级光照/着色滑杆（卡通渲染路线，替代通用三点光）
HSR_LOOK_KEYS = ("cool", "shadow", "brightness", "skin_brightness", "skin_warmth",
                 "specular", "matcap", "source_sphere", "face_softness", "face_depth")

SIX_STEPS = ("ENV", "MAT", "SDF", "LIGHT", "OUTLINE", "REFENV")

# 换模型时骨名/刚体名的差异：日系常用 下擺/スカート/裾，国模常见 下摆/skirt/hem
SKIRT_PATTERNS = ("下擺", "下摆", "裙", "skirt", "hem", "スカート", "裾")
# 头发刚体：日系 髪/長髮，英文导出器常叫 HairA1_JNT
HAIR_PATTERNS = ("髪", "長髮", "hair", "ヘア")


def is_skirt(name: str) -> bool:
    low = name.lower()
    return any(p.lower() in low for p in SKIRT_PATTERNS)


def is_hair(name: str) -> bool:
    low = name.lower()
    return any(p.lower() in low for p in HAIR_PATTERNS)


# ---------------------------------------------------------------- 取景检查
# 来自社区技能的两条原则：
#   1) 取景按"整条运动路径"算，不是按某一帧（起 / 中 / 终画框）
#   2) 构图是可量化的：主体要留在安全框内，且不要一路漂到边上
# 控制骨不承载可见网格，位置常贴地/在原点，统计进去会把"出框"变成误报
# （实测 つま先ＩＫ.L 的 NDC y 到 -0.23，而画面里脚是全的）。
_CONTROL_BONE = ("ＩＫ", "IK", "操作中心", "全ての親", "グルーブ", "センター")

SAFE_MIN = 0.02          # NDC 安全边（0=画面左/下缘，1=右/上缘）
SAFE_MAX = 0.98
CENTER_TOL_X = 0.22      # 主体质心允许偏离画面中心的量
CENTER_TOL_Y = 0.28


def check_framing(cam, frames, step=10):
    """把整条动画的骨骼投影到相机画面，看有没有出框 / 构图漂移。

    只取骨骼（不取网格）：刚体解算在不同进程间会分叉，但骨骼是确定的，
    结果可复现。返回 (metrics, issues)。
    """
    from bpy_extras.object_utils import world_to_camera_view

    scene = bpy.context.scene
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        return {"samples": 0}, [("E-16", "WARN", "没有网格，跳过取景检查", "")]

    # 用"求值后的网格包围盒"，不用骨点：
    # MMD 的 つま先.L / つま先ＩＫ.L 是伸出网格外的尖端与控制骨，
    # 按骨点算会把出框判成 -0.22，而画面里脚是全的（实测）。
    pts_x, pts_y, depths = [], [], []
    per_frame = {}
    for f in frames:
        scene.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        xs, ys = [], []
        for obj in meshes:
            ev = obj.evaluated_get(dg)
            mw = ev.matrix_world
            for corner in ev.bound_box:
                v = world_to_camera_view(scene, cam, mw @ Vector(corner))
                if v.z <= 0:
                    continue
                xs.append(v.x)
                ys.append(v.y)
        if xs:
            per_frame[f] = (min(xs), max(xs), min(ys), max(ys))
            pts_x.extend(xs)
            pts_y.extend(ys)

    if not pts_x:
        return {"samples": 0}, [("E-16", "WARN", "所有采样点都在相机背后", "")]

    mn_x, mx_x = min(pts_x), max(pts_x)
    mn_y, mx_y = min(pts_y), max(pts_y)
    worst = min(per_frame, key=lambda f: per_frame[f][0])
    metrics = {
        "samples": len(per_frame),
        "ndc_x": [round(mn_x, 3), round(mx_x, 3)],
        "ndc_y": [round(mn_y, 3), round(mx_y, 3)],
        "centroid_x_range": [round(min((a + b) / 2 for a, b, _, _ in per_frame.values()), 3),
                             round(max((a + b) / 2 for a, b, _, _ in per_frame.values()), 3)],
        "worst_left_frame": worst,
    }
    issues = []
    # 这里不判"出框"：网格包围盒是轴对齐且基于静止姿态的，估得偏大（实测 NDC y 到 -0.38，
    # 画面里人却是全的）。真正的出框交给 S8 用渲染像素判。
    if mn_x < -0.25 or mx_x > 1.25:
        issues.append(("E-16", "INFO",
                       "构图超出很多：NDC x[%.2f, %.2f]，建议改 auto_refit" % (mn_x, mx_x),
                       "最左帧 f%d" % worst))
    cxs = metrics["centroid_x_range"]
    if max(abs(cxs[0] - 0.5), abs(cxs[1] - 0.5)) > CENTER_TOL_X:
        issues.append(("E-16", "WARN",
                       "构图漂移：主体横向质心 %.2f → %.2f（偏离中心超过 %.2f）"
                       % (cxs[0], cxs[1], CENTER_TOL_X),
                       "固定机位不跟拍，长走位的动作会漂出构图"))
    return metrics, issues


def _now():
    return time.time()


# ---------------------------------------------------------------- 场景准备

# 扩展的模块名可能带仓库前缀：Blender 4.2+ 从扩展目录装的是 `bl_ext.<repo>.<id>`，
# 而老的 addons 目录里是裸名。2026-11-16 实测：本机 mmd_tools 装在扩展目录里且
# **未启用**，`addon_utils.enable("mmd_tools", …)` 返回成功、`bpy.ops.mmd_tools`
# 也**看起来**存在（命名空间是懒建的），但 `import_model` 根本没注册 ⇒
# `ensure_addons()` 报 `{'mmd_tools': True}` 而 `stage_import` 静默产出「0 刚体」
# 的场景。所以这里改成：先按候选名逐个试，**再断言算子真的在**，名字与断言都要。
ADDON_CANDIDATES = {
    "mmd_tools": ("bl_ext.user_default.mmd_tools", "mmd_tools"),
    "jinfengling_hsr_addon": ("bl_ext.user_default.jinfengling_hsr_addon",
                              "jinfengling_hsr_addon"),
}
# 每个插件必须真的注册上的算子（没写就不做算子级断言，退回"模块已启用"）
ADDON_OPERATORS = {"mmd_tools": "import_model"}


def operator_registered(namespace, op: str) -> bool:
    """算子在不在：**不能用 `hasattr`**。

    2026-11-16 实测（三种环境各一遍）：算子没注册时
    `hasattr(bpy.ops.mmd_tools, "import_model")` 仍然是 **True**（命名空间是懒建的，
    属性访问才在 `poll()`/调用时报 `could not be found`）。可靠的探针是
    `getattr(ns, op).get_rna_type()`：注册上了返回 RNA，没注册抛 `KeyError`。
    """
    try:
        getattr(namespace, op).get_rna_type()
    except Exception:
        return False
    return True


def addon_ready(name: str, operators: dict | None = None) -> bool:
    """插件真的可用吗——`addon_utils.enable` 的返回值与 `hasattr` 都不可信。"""
    ops = ADDON_OPERATORS if operators is None else operators
    namespace = getattr(bpy.ops, name, None)
    if namespace is None:
        return False
    op = ops.get(name)
    if op is not None:
        return operator_registered(namespace, op)
    try:
        import addon_utils
    except ImportError:          # 不在 Blender 里：没有可查的模块状态 ⇒ 不能当"就绪"
        return False
    for module in ADDON_CANDIDATES.get(name, (name,)):
        try:
            if addon_utils.check(module)[1]:
                return True
        except Exception:
            continue
    return False


def ensure_addons(names=("mmd_tools", "jinfengling_hsr_addon"), ready=None) -> dict:
    """逐个启用插件，返回 {插件名: 是否真的可用}。

    `ready` 可注入（默认读 bpy 算子），测试用它把「enable 成功但算子没注册」
    这条缺陷钉住：即使 enable 不抛异常，`ready() == False` 也必须返回 False。

    `addon_utils` 不在（纯 Python 环境）时**不抛异常、直接判红**：没有启用器就只能
    验证「本来就就绪」，验不出来就是 False。抛 ImportError 那种写法会被外层的
    `except Exception` 吞成一句「导入失败」，又是一次「看起来通过」。
    """
    try:
        import addon_utils
    except ImportError:
        addon_utils = None
    probe = addon_ready if ready is None else ready
    status = {}
    for name in names:
        ok = bool(probe(name))
        for module in ADDON_CANDIDATES.get(name, (name,)):
            if ok:
                break
            if addon_utils is None:
                continue
            try:
                # default_set/persistent 都关：headless 跑流水线不该改用户偏好
                addon_utils.enable(module, default_set=False, persistent=False)
            except Exception:
                continue
            ok = bool(probe(name))
        status[name] = ok
    return status


def require_importer(namespace=None) -> None:
    """导入前最后一道闸：算子不在就抛，绝不静默跑出一份空场景。"""
    ns = bpy.ops.mmd_tools if namespace is None else namespace
    if not operator_registered(ns, "import_model"):
        raise RuntimeError(
            "mmd_tools 的 import_model 算子没注册（插件装了但没启用，或名字不是 "
            "bl_ext.user_default.mmd_tools）。先跑 stage.ensure_addons() 并确认返回 True。"
        )


def reset_scene() -> int:
    removed = 0
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
        removed += 1
    return removed


def find_root():
    for obj in bpy.data.objects:
        if getattr(obj, "mmd_type", None) == "ROOT":
            return obj
    return None


def find_parts(root):
    """优先按 root.name+'_arm'/'_mesh' 取；取不到再按类型兜底。

    换模型时的坑（mmd-physics 文档 03）：部分骨架的 mmd_type 是 'NONE'，
    按 mmd_type=='ARMATURE' 找会直接空手而归。
    """
    arm = bpy.data.objects.get(root.name + "_arm")
    mesh = bpy.data.objects.get(root.name + "_mesh")
    if arm is None:
        arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
        arm = max(arms, key=lambda o: len(o.data.bones)) if arms else None
    if mesh is None:
        meshes = [o for o in bpy.data.objects if o.type == "MESH"]
        mesh = max(meshes, key=lambda o: len(o.data.vertices)) if meshes else None
    return arm, mesh


def rigid_bodies():
    return [o for o in bpy.data.objects if getattr(o, "mmd_type", None) == "RIGID_BODY"]


def collision_scope():
    """通道的**作用域**与**作用域外的例外**（D0 2026-11-16 15:02，`D-20261116-133`）。

    作用域 = `mmd_type == "RIGID_BODY"`（= U323）= 通道把这些 PMX 刚体的掩码落到
    碰撞位与约束上。**不按 `rigid_body is not None` 扩**，理由（D0 定，原话三条）：
    ① 像 `地面_物理` 这种旧场景里手工加的对象不是 PMX 骨名，通道语义是「把 PMX 掩码落到
    PMX 刚体上」；② 它在 PMX 里没有对应刚体，「PMX 说它不该碰」这条判据对它本就不适用；
    ③ 纳进来是接口变更，换来的只是 40418 里的 62 对（0.15%）。

    但**跳过必须写在纸上**：例外对象逐条返回，报告里单列一行（名字 / 组 / 掩码 /
    「在"共享位即碰"语义下仍与多少个刚体互撞」），不进 `skipped[]`（它不是"没做成"，
    是"不在作用域"）。
    """
    inside, outside = [], []
    for obj in bpy.data.objects:
        if getattr(obj, "rigid_body", None) is None:
            continue
        if getattr(obj, "mmd_rigid", None) is None:
            continue
        if getattr(obj, "mmd_type", None) == "RIGID_BODY":
            inside.append(obj)
        else:
            outside.append(obj)
    return inside, outside


def exception_rows(bodies, exceptions) -> list:
    """作用域外的刚体：仍会与多少作用域内刚体互撞（逻辑在 `mmdpipe/mask.py`，可单测）。"""
    return mask_mod.exception_rows(bodies, exceptions)


# ---------------------------------------------------------------- 碰撞掩码（PMX collision_group_mask）
#
# 逻辑在 `mmdpipe/mask.py`（纯 Python，不 import bpy，可单测）。这里只做两件 bpy 侧的事：
# 把场景喂给它、把结果折进 metrics 与 S8 判据。动机与实测数字见 mask.py 的模块说明：
# 掩码 145/145 个都写了、声明 7367 对不该碰（占 70.6%）、其中 1462 对是单向的（不能写成
# 集合位），而 mmd_tools 只给"距离够近"的对建 disable_collisions 约束。语义与证据链见
# `mmdpipe/mask.py` 的模块说明。
NCC_TYPE = "NON_COLLISION_CONSTRAINT"

# `stage_build` 折进 metrics 的字段清单（**只此一处**：指标清单和判据清单分开写就会漂，
# 判「通道够不够」要看的数与报出去的数必须是同一批）。
MASK_WIRED_KEYS = (
    "bodies", "collections_set", "collections_patterns",
    "constraints_needed", "constraints_already_blocked",
    "constraints_to_add", "constraints_added",
    "constraints_released", "constraints_identity",
    "constraints_capped", "guardrail_hit", "skipped_count",
    "constraint_creation", "readback_mismatch",
    "unexpressible", "asymmetric_pairs",
    "verdict", "verdict_reasons")


def constraint_limit(needed_count, max_constraints=None) -> tuple:
    """建约束上限：**由 plan 推出**，`DEFAULT_MAX_CONSTRAINTS` 只当护栏（D-144③）。

    返回 `(limit, guardrail_hit)`：

    * `max_constraints is None`（默认）⇒ `limit = 需求本身`。需求多少就建多少，
      上限**不是**一个写死的预算；只有需求超过护栏量级时才被护栏咬住并置
      `guardrail_hit`——那时说明场景形状不对，不是"预算不够"。
    * 显式给了 `max_constraints` ⇒ 那个值就是上限（调用者要一个更小的预算）。
      这时 `needs > cap` 是**可预知的返工**，`coordination.preflight` 会在开工前拦下。

    `mmdpipe.stage.apply_collision_masks()` 与 `mask_preflight_fields()` 都走这一个函数：
    上限、预检读数、建场实际行为必须是同一处口径（"一处口径，别两个数各说各话"）。
    """
    needed = max(0, int(needed_count))
    if max_constraints is not None:
        return max(0, int(max_constraints)), False
    if needed > mask_mod.DEFAULT_MAX_CONSTRAINTS:
        return int(mask_mod.DEFAULT_MAX_CONSTRAINTS), True
    return needed, False


# 「通道接全了」的四条判据（`coordination/mask_channel_spec.md` §4，D0 `D-20261116-145`）。
# **分开给、不许合成一个 `and`**：合取式里一位写错，整体永远是绿的，读数的人还看不出是哪条坏。
# 名字进 `verdict_reasons`，红的那几条由 `mask_wired_missing()` 取反列出。
MASK_WIRED_CRITERIA = (
    "verdict_wired", "not_capped", "no_skipped", "added_plus_already_equals_needed")


def mask_wired_checks(report) -> dict:
    """四条判据逐条给 bool（读 `apply_collision_masks()` / `stage_mask()` 的报告）。"""
    report = dict(report or {})
    needed = report.get("constraints_needed")
    added = report.get("constraints_added")
    already = report.get("constraints_already_blocked")
    identity = (needed is not None and added is not None and already is not None
                and int(added) + int(already) == int(needed))
    return {
        "verdict_wired": report.get("verdict") == "WIRED",
        # 必须是**显式的 False**：缺这个键（旧场景/外部搭的场景）不算"没 cap"
        "not_capped": report.get("constraints_capped") is False,
        # 同一件事：得显式说 0。`skipped_count` 缺失 ⇒ 红（"没记录"≠"没跳过"）
        "no_skipped": report.get("skipped_count") == 0
                      and not (report.get("skipped") or []),
        "added_plus_already_equals_needed": bool(identity),
    }


def mask_wired_missing(report) -> list:
    """没过的判据名（空列表 = 四条全绿）。判红的理由要能一条条念出来。"""
    checks = mask_wired_checks(report)
    return [name for name in MASK_WIRED_CRITERIA if not checks[name]]


def mask_gate_reason(wired) -> str:
    """通道开着（`wired is not None`）但四条判据没全绿 ⇒ 返回停机理由，否则 None。

    `stage_build()` 在**烘焙之前**调用它（D0 15:11 / 总控 17:31②）：半套通道 + 已烘焙
    是最贵的「看起来像干净」。`wired is None` 是「通道没开」（预设里显式关了），
    那是另一种场景，不归这条闸管——所以这里返回 None，不许把它当成"接好了"。
    """
    if wired is None:
        return None
    missing = mask_wired_missing(wired)
    if not missing:
        return None
    return ("碰撞通道没接全：verdict=%s，红项 %s（skipped %s 对）"
            % (wired.get("verdict"),
               ",".join(missing) or "-",
               wired.get("skipped_count", 0)))


def mask_preflight_fields(wired) -> dict:
    """把通道读数接成 `coordination.preflight` 的三项：`needs` / `cap` / `skipped`。

    **`cap` 取的是 `constraint_limit()` 的返回值**，与建场用的是同一个函数——
    在请求 JSON 里手写 `8298` / `20000` 只证明那段 JSON 能解析，不证明上限真的由需求推出
    （总控 17:31③）。`needs` = 这次要补的条数（`constraints_to_add`），不是总对数。
    """
    wired = wired or {}
    needed = wired.get("constraints_needed")
    to_add = wired.get("constraints_to_add")
    if to_add is None and needed is not None:
        to_add = max(0, int(needed) - int(wired.get("constraints_already_blocked") or 0))
    cap, guardrail = constraint_limit(needed if needed is not None else (to_add or 0))
    return {"needs": int(to_add or 0), "cap": int(cap),
            "skipped": int(wired.get("skipped_count") or 0),
            "guardrail_hit": bool(guardrail)}


def mask_report(rigids=None, objects=None) -> dict:
    """逐刚体回读 + 汇总（bpy 侧薄封装，逻辑在 `mmdpipe/mask.py`）。"""
    inside, outside = collision_scope()
    bodies = inside if rigids is None else rigids
    pool = bpy.data.objects if objects is None else objects
    result = mask_mod.mask_report(bodies, pool)
    result["scope_bodies"] = len(inside)
    result["exception_bodies"] = exception_rows(inside, outside)
    return result


def _ncc_template():
    """找一条**可以复制**的 ncc 模板：带 `rigid_body_constraint` 且 `disable_collisions`。

    优先 `mmd_type == NON_COLLISION_CONSTRAINT`（`mmd_tools` 造的 ncc 就是这个形状），
    退而求其次任何 `disable_collisions=True` 的约束对象。都没有就返回 `None`，
    调用方退回逐条 `bpy.ops`（并把这个事实写进结果，不做静默选择）。
    """
    fallback = None
    for obj in bpy.data.objects:
        con = getattr(obj, "rigid_body_constraint", None)
        if con is None or not getattr(con, "disable_collisions", False):
            continue
        if getattr(obj, "mmd_type", None) == mask_mod.NCC_MMD_TYPE:
            return obj
        if fallback is None:
            fallback = obj
    return fallback


def _new_constraint_object(name: str, template=None):
    """造一个只承担 DISABLE_COLLISIONS 的空物体（mmd_tools 的 ncc 同形状）。

    `template` 给了就**复制**它，不走 `bpy.ops.rigidbody.constraint_add()`：那个算子每次
    调用都触发整场景 depsgraph 求值（实测 60 ms/条 @145 刚体；带依赖环的 323 刚体场景
    2号 测到 0.39–0.48 s/条）。全尺寸交付场景要补 8 298 条 ⇒ 旧路 8 分钟到 1 小时，
    复制路是毫秒级。**复制这条路是"测出来的"不是"想出来的"**：
    `tests_bpy/mask_channel_small_probe.py --factory template_copy --factory ops` 在小场景
    上跑两遍，判据是两条路的后态相同（`blocked_and_should_collide == 0`、
    `nocollide_pairs_still_colliding == 0`、`constraints_added` 相同）而不是"没报错"。
    """
    scene = bpy.context.scene
    if template is not None:
        obj = template.copy()
        obj.name = name
        scene.collection.objects.link(obj)
        obj.mmd_type = mask_mod.NCC_MMD_TYPE
        obj.hide_render = True
        con = obj.rigid_body_constraint
        if con is None:
            raise RuntimeError("复制出来的对象没有 rigid_body_constraint（模板形状变了）")
        # 复制会带走模板的 object1/object2 指针，必须显式改成这一对
        con.object1 = None
        con.object2 = None
        con.enabled = True
        con.disable_collisions = True
        return obj
    obj = bpy.data.objects.new(name, None)
    scene.collection.objects.link(obj)
    obj.mmd_type = mask_mod.NCC_MMD_TYPE
    obj.hide_render = True
    # 只在需要时切换活动对象：`select_all(action="DESELECT")` 每次都是全场景操作，
    # 在 300+ 刚体、12 个依赖环的场景里逐条调用的代价极高（实测见 mask.py 的注释）。
    view_layer = bpy.context.view_layer
    previous = view_layer.objects.active
    if previous is not None and previous.name != obj.name:
        previous.select_set(False)
    obj.select_set(True)
    view_layer.objects.active = obj
    try:
        bpy.ops.rigidbody.constraint_add(type="GENERIC")
    finally:
        obj.select_set(False)
        if previous is not None:
            try:
                view_layer.objects.active = previous
            except (ReferenceError, RuntimeError):
                pass
    con = obj.rigid_body_constraint
    con.disable_collisions = True
    return obj


def apply_collision_masks(scene=None, *, collection_index_of=None,
                          max_constraints=None, constraint_factory=None,
                          constraint_creation=None) -> dict:
    """把 PMX 的组号与掩码接进 Blender（`coordination/mask_channel_spec.md` §1 的接口）。

    做两件事，缺一不可：

    1. **位**：`collision_collections = mask | (1 << own_group)`。加自己组那一位的理由与
       可证性质见 `mmdpipe/mask.py` 的「位映射」一节（结论：PMX 该碰的每一对必然共享
       某一位，「表达不了」= 0）。
    2. **约束**：位是「共享即碰」的对称语义，于是会出现**假碰**（两个都「与第 5 组碰」
       但彼此不该碰）。每一对这样的刚体补一条 `DISABLE_COLLISIONS` 约束，把它们分开。
       **不许拿「交集近似」代替约束**——那会把该碰的成对静默停碰。

    只读源数据（`mmd_rigid.collision_group/mask` 一个字节都不改），可重复调用：
    第二次进来时已存在的约束会被认出，`constraints_added` 归 0。

    `collection_index_of` 保留给将来换编码用；当前实现不用它（位号就是组号）。

    `constraint_factory(name) -> 对象` 是注入点：给了就完全由它造约束（单测/替身用），
    否则走「复制已有 ncc」，复制失败才退回逐条 `bpy.ops`。

    `constraint_creation`：`None`（默认，自动选）/ `"template_copy"` / `"ops"`。
    显式指定 `"template_copy"` 而场景里没有可复制的模板时**抛异常**，不静默降级——
    探针要对比两条路时，最怕的就是"以为走的是复制路、其实走了 ops"。
    """
    bodies, outside = collision_scope()
    if scene is not None:
        bodies = [o for o in bodies if o.name in {x.name for x in scene.objects}]
    already = mask_mod.disabled_pairs(bpy.data.objects)
    plan = mask_mod.plans(bodies, blocked=already)
    needed_pairs = [mask_mod.pair_key(a, b) for a, b in plan["constraints_needed"]]
    already_needed = sum(1 for pair in needed_pairs if pair in already)
    result = dict(plan)
    for key in ("bits_of", "constraints_needed", "release_pairs"):
        result.pop(key, None)
    # 三个数一起报，才能分清「不用补」「已经挡好了」「该补没补」：
    # `constraints_needed` 是 PMX 语义下必须靠约束分开的总对数，
    # `constraints_already_blocked` 是场景里已经挡对的，`constraints_to_add` 才是这条通道的活。
    result["constraints_needed"] = len(needed_pairs)
    result["constraints_already_blocked"] = already_needed
    result["constraints_to_add"] = len(needed_pairs) - already_needed
    # 这些键**在每条返回路径上都必须存在**（`MASK_WIRED_KEYS` 是折 metrics 的唯一清单，
    # 少一个键就是 `stage_build` 那边 KeyError 或者一个"没测"被读成 0）。
    result.setdefault("constraints_capped", False)
    result.setdefault("guardrail_hit", False)
    result.setdefault("constraints_released", 0)
    result.setdefault("constraints_added", 0)
    result.setdefault("readback_mismatch", 0)
    result.setdefault("constraint_creation", "none")
    result.setdefault("verdict_reasons", [])
    result.setdefault("constraints_identity", len(needed_pairs) == already_needed)
    result["encoding"] = mask_mod.ENCODING_NOTE
    result["blender_semantics"] = dict(mask_mod.MEASURED_SEMANTICS)
    # 作用域与例外（D-20261116-133）：U323 是 1c 等式的宇宙，例外单列一行
    result["scope_bodies"] = len(bodies)
    result["exception_bodies"] = exception_rows(bodies, outside)

    if not bodies:
        # `scanned==0` 同族：0 个刚体不是"通道接好了"，是"没东西可接"（spec §4.6）
        result.update({"collections_set": 0, "collections_patterns": 0,
                       "skipped_count": len(result.get("skipped") or []),
                       "verdict_reasons": ["no_bodies"],
                       "verdict": "EMPTY"})
        return result

    # 1) 写位
    expected = plan["bits_of"]
    set_count = 0
    touched_names = set()
    for obj in bodies:
        wants = expected[obj.name]
        flags = mask_mod.collection_flags(wants)
        body = getattr(obj, "rigid_body", None)
        if body is None:
            result.setdefault("skipped", []).append(
                {"name": obj.name, "reason": "没有 rigid_body（不是刚体对象）"})
            continue
        body.collision_collections = flags
        set_count += 1
        touched_names.add(obj.name)
    result["objects_modified"] = len(touched_names)
    # 改动范围正控（2号 的要求）：只许碰 `mmd_rigid` 存在的刚体对象
    result["objects_touched_outside_mmd_rigid"] = sum(
        1 for name in touched_names
        if getattr(bpy.data.objects.get(name), "mmd_rigid", None) is None)

    # 2) 回读（逐刚体，与源掩码一致）
    mismatch = []
    for obj in bodies:
        body = getattr(obj, "rigid_body", None)
        if body is None:
            continue
        got = 0
        for n, bit in enumerate(body.collision_collections):
            if bit:
                got |= 1 << n
        if got != expected[obj.name]:
            mismatch.append(obj.name)
    result["collections_set"] = set_count
    result["collections_patterns"] = len({expected[o.name] for o in bodies})
    result["readback_mismatch"] = len(mismatch)
    result["readback_mismatch_names"] = mismatch[:5]

    # 3) 放掉挡错的约束（mmd_tools 的 buildRigids() 相对它自己的导入器是反的：
    #    实测 J_baked.blend 4009 条里有 2196 条挡的是「本该互碰」的对）。
    #    只置 disable_collisions=False，不删对象——删是别人的数据，改标志是可逆的最小动作。
    released = 0
    for obj in bpy.data.objects:
        con = getattr(obj, "rigid_body_constraint", None)
        if con is None or not getattr(con, "disable_collisions", False):
            continue
        a = getattr(getattr(con, "object1", None), "name", None)
        b = getattr(getattr(con, "object2", None), "name", None)
        if not a or not b or a == b:
            continue
        if mask_mod.pair_key(a, b) in set(plan["release_pairs"]):
            con.disable_collisions = False
            released += 1
    result["constraints_released"] = released

    # 4) 补 DISABLE_COLLISIONS（幂等：已挡住的对不再建）
    #
    # 上限**由 plan 推出，不吃默认值**（D0 15:11：「一处口径，别两个数各说各话」）。
    # `DEFAULT_MAX_CONSTRAINTS` 只作护栏：需求超过它说明场景形状不对，不是"预算不够"——
    # 那时停下、把 `guardrail_hit` 与逐条 `skipped` 写出来，绝不静默跑飞。
    # 算法在 `constraint_limit()`（与 `mask_preflight_fields()` 同一处，预检读数才可信）。
    added = 0
    limit, guardrail_hit = constraint_limit(len(needed_pairs), max_constraints)
    if guardrail_hit:
        result["guardrail_hit"] = True
    if constraint_creation not in (None, "template_copy", "ops"):
        raise ValueError("constraint_creation 只能是 None / 'template_copy' / 'ops'，收到 %r"
                         % (constraint_creation,))
    template = _ncc_template() if constraint_factory is None else None
    if constraint_creation == "ops":
        template = None
    elif (constraint_creation == "template_copy" and constraint_factory is None
          and template is None):
        raise RuntimeError("要求走 template_copy，但场景里没有可复制的 ncc 模板"
                           "（任何 disable_collisions=True 的约束对象都没有）")
    modes = set()
    copy_errors = 0
    for name_a, name_b in plan["constraints_needed"]:
        pair = mask_mod.pair_key(name_a, name_b)
        if pair in already:
            continue
        obj_a = bpy.data.objects.get(name_a)
        obj_b = bpy.data.objects.get(name_b)
        if obj_a is None or obj_b is None:
            result.setdefault("skipped", []).append(
                {"pair": [name_a, name_b], "reason": "取不到刚体对象"})
            continue
        if added >= limit:
            # **不许无声跑飞**：超出上限就停下，并把没做的逐条记进 skipped（spec §1 / D-086）
            result.setdefault("skipped", []).append(
                {"pair": [name_a, name_b],
                 "reason": "达到建约束上限 %d（未做的逐条记在这里，不许当没发生）" % limit})
            result["constraints_capped"] = True
            continue
        if constraint_factory is not None:
            ncc = constraint_factory("ncc_mask_%04d" % added)
            modes.add("injected")
        elif template is not None:
            try:
                ncc = _new_constraint_object("ncc_mask_%04d" % added, template=template)
                modes.add("template_copy")
            except Exception:
                # 复制这条路失败要留痕，再退回逐条 ops（慢，但正确）——不做静默降级
                copy_errors += 1
                template = None
                ncc = _new_constraint_object("ncc_mask_%04d" % added)
                modes.add("ops")
        else:
            ncc = _new_constraint_object("ncc_mask_%04d" % added)
            modes.add("ops")
        ncc.rigid_body_constraint.object1 = obj_a
        ncc.rigid_body_constraint.object2 = obj_b
        ncc.rigid_body_constraint.disable_collisions = True
        added += 1
    result["constraints_added"] = added
    result["constraint_creation"] = "+".join(sorted(modes)) if modes else "none"
    if copy_errors:
        result["copy_errors"] = copy_errors

    # 记账恒等式：该补的 = 已经挡好的 + 这次补上的。**不等就是不完整**（跳过/被 cap 都会破）。
    result["constraints_identity"] = (added + already_needed == len(needed_pairs))

    # 判词：`PARTIAL` 只说"不是 WIRED"，不说**为什么**——所以必须把原因逐项列出来，
    # 否则「cap 了」「表达不了」「回读不一致」在读数的人眼里长得一模一样。
    result["skipped_count"] = len(result.get("skipped", []))
    reasons = []
    if not set_count:
        reasons.append("no_collections_written")
    if result.get("constraints_capped"):
        reasons.append("constraints_capped")
    if result.get("guardrail_hit"):
        reasons.append("guardrail_hit")
    if result["readback_mismatch"]:
        reasons.append("readback_mismatch")
    if plan["unexpressible"]:
        reasons.append("unexpressible")
    if result["skipped_count"]:
        reasons.append("skipped")
    if not result["constraints_identity"]:
        reasons.append("constraints_identity_broken")
    result["verdict_reasons"] = reasons
    result["verdict"] = "PARTIAL" if reasons else "WIRED"

    # 建场事实写进**场景自身**（D-142「意图写进产物」）：`stage_mask()` 事后读它。
    # 不写的话，"这次 cap 过"只活在本次运行的返回值里，场景一存盘就看不见了。
    try:
        bpy.context.scene["mask_wired"] = {
            "verdict": result["verdict"],
            "verdict_reasons": list(result["verdict_reasons"]),
            "constraints_needed": result["constraints_needed"],
            "constraints_already_blocked": result["constraints_already_blocked"],
            "constraints_to_add": result["constraints_to_add"],
            "constraints_added": result["constraints_added"],
            "constraints_capped": bool(result["constraints_capped"]),
            "guardrail_hit": bool(result["guardrail_hit"]),
            "skipped_count": int(result["skipped_count"]),
            "readback_mismatch": int(result["readback_mismatch"]),
            "constraint_creation": result["constraint_creation"],
        }
    except (AttributeError, TypeError, KeyError):
        pass          # 没有场景上下文（单测替身/离屏）时不影响返回值
    return result


def stage_mask(root=None) -> dict:
    """给外部实验/验收用的最小接口（1号 的 S8 第三层、2号 的准入 ②直接调这个）。

    返回 `mask_report()` 的完整结果（含 `rows` 逐刚体读回：PMX 的 `mask` 位图、
    忽略的组、Bullet 侧 `collision_collections` 位）**外加判词**。**只读，不改场景。**

    `WIRED` 的四条（`coordination/mask_channel_spec.md` §4，D0 `D-20261116-145`）：
    ① 位型 ≥ 2 种；② 逐刚体回读全等于 `mask | (1 << group)`；
    ③ 两个归零量为 0（`blocked_and_should_collide` / `nocollide_pairs_still_colliding`）；
    ④ 建场记录里 `constraints_capped == False` 且 `skipped_count == 0`。

    第 ④ 条吃的是**建场时写在场景上的记录**（`scene["mask_wired"]`）。场景没有这条记录
    （别人手搭的、或旧文件）时判词**不可能是 WIRED**——"没记录"不许当成"没问题"。
    """
    report = mask_report()
    scene = bpy.context.scene
    record = {}
    try:
        stored = scene.get("mask_wired")
        if stored:
            record = {k: stored[k] for k in stored.keys()}
    except (AttributeError, TypeError):
        record = {}
    report["wired_record"] = record
    report["constraints_capped"] = record.get("constraints_capped")
    report["skipped_count"] = record.get("skipped_count")

    if not report["rigids"]:
        report["verdict_reasons"] = ["no_bodies"]
        report["verdict"] = "EMPTY"
        return report

    patterns = {row["collections"] for row in report["rows"]}
    mismatched = [row["name"] for row in report["rows"]
                  if row["collections"] != (row["mask"] | (1 << row["group"]))]
    reasons = []
    if len(patterns) < 2:
        reasons.append("bit_patterns_below_2")
    if mismatched:
        reasons.append("readback_mismatch")
    if report["blocked_and_should_collide"]:
        reasons.append("blocked_and_should_collide")
    if report["nocollide_pairs_still_colliding"]:
        reasons.append("nocollide_pairs_still_colliding")
    if report["unexpressible_pairs"]:
        reasons.append("unexpressible")
    if not record:
        reasons.append("no_wired_record")
    else:
        if record.get("constraints_capped"):
            reasons.append("constraints_capped")
        if record.get("skipped_count"):
            reasons.append("skipped")
    report["readback_mismatch_names"] = mismatched[:5]
    report["verdict_reasons"] = reasons
    report["verdict"] = "PARTIAL" if reasons else "WIRED"
    return report



def constraint_histogram(arm) -> dict:
    hist = {}
    for pbone in arm.pose.bones:
        for con in pbone.constraints:
            hist[con.type] = hist.get(con.type, 0) + 1
    return hist


# ---------------------------------------------------------------- S2 导入建链

def stage_import(preset, pmx_path: str):
    res = StageResult("S2_import")
    t0 = _now()
    # 预设是差分文件：磁盘上可能没有 import 段，直接取会 KeyError（1号 实测）
    cfg = preset_mod.section(preset, "import")

    try:
        require_importer()
    except RuntimeError as exc:
        res.add("E-16", BLOCK, "PMX 导入失败：%s" % exc)
        res.elapsed = _now() - t0
        return res, None, None, None

    before = len(bpy.data.objects)
    try:
        bpy.ops.mmd_tools.import_model(
            filepath=pmx_path,
            scale=cfg["scale"],
            types=set(cfg["types"]),
            clean_model=cfg["clean_model"],
            remove_doubles=cfg["remove_doubles"],
            rename_bones=cfg["rename_bones"],
            log_level="ERROR",
        )
    except Exception as exc:
        res.add("E-16", BLOCK, "PMX 导入失败：%s" % exc)
        res.elapsed = _now() - t0
        return res, None, None, None

    root = find_root()
    if root is None:
        res.add("E-17", BLOCK,
                "找不到 mmd_type=='ROOT' 的对象（mmd_tools 没加载或枚举变了）",
                "objects=%d" % len(bpy.data.objects))
        res.elapsed = _now() - t0
        return res, None, None, None

    arm, mesh = find_parts(root)
    if arm is None or mesh is None:
        res.add("E-17", BLOCK,
                "按 root.name+'_arm'/'_mesh' 取不到对象",
                "root=%s" % root.name)
        res.elapsed = _now() - t0
        return res, root, arm, mesh

    rigids = rigid_bodies()
    res.metrics.update({
        "root": root.name,
        "vertices": len(mesh.data.vertices),
        "bones": len(arm.data.bones),
        "rigids": len(rigids),
        "objects_added": len(bpy.data.objects) - before,
    })
    if not rigids:
        res.add("G1", BLOCK, "这个模型没有刚体，物理无从谈起")
    if not mesh.data.materials:
        res.add("E-15", WARN, "网格没有材质")
    res.elapsed = _now() - t0
    return res, root, arm, mesh


# ---------------------------------------------------------------- 烘焙（契约 B / D-067 / D-173）
#
# 为什么是「显式参数 + 行为探针」而不是「在 stage_build 里顺手烘一下」：
#
# * `bake=None`（默认）必须逐字保持旧行为——`runner.py`、交付构建链、各席的臂都不传它，
#   这条改动一旦悄悄改了别人的读数，比不烘更坏；
# * 「烘过了」不是判据：`point_cache.is_baked` 在健康件和缺陷件上都可能为真（D-155/D-158），
#   所以烘完必须**冷跳读回来和烘焙前顺序解算的那次姿态比**，不是看标志位；
# * 烘的不是我们这次解算的姿态，就等于把另一条轨迹钉进交付件——所以比较的参照物必须是
#   **本进程烘焙前**逐帧步进得到的那批指纹。
BAKE_FIELDS = ("requested", "applied", "frame_start", "frame_end", "fps")
BAKE_EXTRA_FIELDS = ("pose_source", "is_baked", "is_outdated")
BAKE_TOL = 1e-6
BAKE_KEYS = ("frame_start", "frame_end", "fps")


def bake_request(bake=None) -> dict | None:
    """规范化 `bake` 参数：`None` ⇒ `None`（不烘）；字典只认 `frame_start/frame_end/fps`。

    不认识的键**直接拒**：多一个拼错的键被静默忽略，就是「以为调了 fps、其实没调」。
    """
    if bake is None:
        return None
    if not isinstance(bake, dict):
        raise ValueError("bake 必须是 None 或 dict，给的是 %s"
                         % type(bake).__name__)
    unknown = sorted(set(bake) - set(BAKE_KEYS))
    if unknown:
        raise ValueError("bake 里有不认识的键：%s（只认 %s）"
                         % (", ".join(unknown), "/".join(BAKE_KEYS)))
    start = int(bake["frame_start"]) if bake.get("frame_start") is not None else 1
    end = int(bake["frame_end"]) if bake.get("frame_end") is not None else start
    if end < start:
        raise ValueError("bake.frame_end(%d) < bake.frame_start(%d)" % (end, start))
    req = {"frame_start": start, "frame_end": end}
    if bake.get("fps") is not None:
        fps = int(bake["fps"])
        if fps <= 0:
            raise ValueError("bake.fps 必须为正，给的是 %d" % fps)
        req["fps"] = fps
    return req


def pose_snapshot(objects) -> dict:
    """逐刚体的世界矩阵（16 个浮点，9 位小数）。烘焙前后的**同一批帧**都用它取指纹。"""
    snap = {}
    for obj in objects:
        matrix = getattr(obj, "matrix_world", None)
        if matrix is None:
            continue
        values = []
        for row in matrix:
            for value in row:
                values.append(round(float(value), 9))
        snap[obj.name] = values
    return snap


def _snapshots_differ(frames_snapshots) -> bool:
    """采样帧之间的姿态有没有**真的不同**（同一帧不算；空输入算 False）。"""
    seen = set()
    for snapshot in (frames_snapshots or {}).values():
        seen.add(tuple(sorted((name, tuple(values)) for name, values in snapshot.items())))
        if len(seen) > 1:
            return True
    return False


def bake_probe(fresh, cached, tol=BAKE_TOL) -> dict:
    """纯函数：`fresh`（烘焙前顺序解算）对比 `cached`（烘焙后冷跳）逐帧逐值。

    返回的 `matched` 只有「帧齐、刚体齐、每个值都在 `tol` 内」才为真；缺帧缺刚体都算红
    （`bodies=[]` 那种「读不到当 0」的假绿在这里同样不许出现）。
    """
    fresh = dict(fresh or {})
    cached = dict(cached or {})
    missing_frames = sorted(set(fresh) - set(cached))
    extra_frames = sorted(set(cached) - set(fresh))
    mismatches = []
    missing_objects = []
    max_delta = 0.0
    compared_bodies = set()
    for frame in sorted(set(fresh) & set(cached)):
        want, got = fresh[frame], cached[frame]
        for name in sorted(want):
            if name not in got:
                missing_objects.append({"frame": frame, "object": name})
                continue
            compared_bodies.add(name)
            a, b = want[name], got[name]
            if len(a) != len(b):
                mismatches.append({"frame": frame, "object": name, "field": "matrix_length",
                                   "fresh": len(a), "cached": len(b)})
                continue
            for index, (va, vb) in enumerate(zip(a, b)):
                delta = abs(float(va) - float(vb))
                max_delta = max(max_delta, delta)
                if delta > tol:
                    mismatches.append({"frame": frame, "object": name, "index": index,
                                       "fresh": va, "cached": vb, "delta": delta})
    return {
        "matched": not (mismatches or missing_objects or missing_frames or extra_frames)
                   and bool(compared_bodies),
        # 参照姿态若在采样帧之间**完全相同**，「一致」只证明了「两次读到同一个静态值」——
        # 那不是"缓存忠实"，是"没东西可忠实"。静态场景照样会给出 max_delta=0。
        "reference_moved": _snapshots_differ(fresh),
        "tol": tol,
        "frames": sorted(set(fresh) & set(cached)),
        "bodies": len(compared_bodies),
        "max_delta": max_delta,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:20],
        "missing_frames": missing_frames,
        "extra_frames": extra_frames,
        "missing_objects": missing_objects[:20],
    }


def bake_checks(record) -> dict:
    """「这件算按契约 B 烘过吗」——六条**分开给**，不合成一个 `and`（一位坏就看不见）。"""
    record = record or {}
    probe = record.get("probe") or {}
    return {
        "requested": record.get("requested") is not None,
        "applied": record.get("applied") is True,
        "not_outdated": record.get("is_outdated") is False,
        "probe_matched": probe.get("matched") is True,
        # 「一致」只有在参照姿态真的动过时才算证据：静态场景逐位相同是必然的
        "probe_informative": probe.get("reference_moved") is True,
        "fields_complete": all(key in record for key in BAKE_FIELDS + BAKE_EXTRA_FIELDS),
    }


def bake_missing(record) -> list:
    return [key for key, ok in bake_checks(record).items() if not ok]


def bake_gate_reason(record) -> str | None:
    """五条全绿才算「烘过」。返回 None 或一句能直接进 BLOCK 的理由。"""
    missing = bake_missing(record)
    if not missing:
        return None
    probe = (record or {}).get("probe") or {}
    detail = ""
    if "probe_matched" in missing:
        detail = "（不一致 %d 处，最大差 %s，帧 %s）" % (
            probe.get("mismatch_count", 0), probe.get("max_delta"),
            probe.get("frames"))
    return "烘焙不合格：%s%s" % ("、".join(missing), detail)


def bake_record(scene, req, probe, applied, is_baked, is_outdated) -> dict:
    """落盘形状（读者不用打开 `stage.py` 就知道这件是什么状态）。"""
    cache = scene.rigidbody_world.point_cache if scene and scene.rigidbody_world else None
    req = req or {}

    def _int(value, default=0):
        return default if value is None else int(value)

    return {
        "requested": req or None,
        "applied": bool(applied),
        "frame_start": _int(getattr(cache, "frame_start", None), _int(req.get("frame_start"))),
        "frame_end": _int(getattr(cache, "frame_end", None), _int(req.get("frame_end"))),
        "fps": _int(getattr(getattr(scene, "render", None), "fps", None),
                    _int(req.get("fps"))),
        "pose_source": "cache_replay" if applied else "fresh_solve",
        "is_baked": bool(is_baked),
        "is_outdated": bool(is_outdated),
        "probe": probe,
    }


def stage_bake(scene, bake, objects=None, bake_call=None) -> dict:
    """烘一次 + 行为探针（契约 B）。返回落盘记录；**不判**，判在 `bake_gate_reason()`。

    探针口径：烘焙前从 `frame_start` 逐帧步进记下采样帧的刚体世界矩阵（`fresh_solve`）→
    烘焙 → 每帧「先跳回起点前、再冷跳到该帧」重读（`cache_replay`）→ 逐值比。两次读数
    若一致，说明缓存里钉的就是这次解算；不一致说明烘进去的是另一条轨迹。
    """
    req = bake_request(bake)
    objects = list(rigid_bodies() if objects is None else objects)
    if req is None:
        return bake_record(scene, None, {}, False, False, False)
    rbw = getattr(scene, "rigidbody_world", None)
    if rbw is None:
        return bake_record(scene, req, {"error": "no_rigidbody_world"}, False, False, False)
    cache = rbw.point_cache
    cache.frame_start = req["frame_start"]
    cache.frame_end = req["frame_end"]
    if req.get("fps"):
        scene.render.fps = req["fps"]

    samples = sorted({req["frame_start"],
                      (req["frame_start"] + req["frame_end"]) // 2,
                      req["frame_end"]})
    fresh = {}
    for frame in range(req["frame_start"], max(samples) + 1):
        scene.frame_set(frame)
        if frame in samples:
            fresh[frame] = pose_snapshot(objects)

    if bake_call is None:
        bake_call = lambda **_kw: bpy.ops.ptcache.bake_all(bake=True)      # noqa: E731
    bake_call(bake=True)

    cold = req["frame_start"] - 1
    cached = {}
    for frame in samples:
        scene.frame_set(cold)          # 先离开目标帧，否则「读到的是上一帧留下的缓存」
        scene.frame_set(frame)
        cached[frame] = pose_snapshot(objects)

    probe = bake_probe(fresh, cached)
    return bake_record(scene, req, probe, bool(getattr(cache, "is_baked", True)),
                       bool(getattr(cache, "is_baked", True)),
                       bool(getattr(cache, "is_outdated", False)))


def stage_build(preset, root, arm, bake=None):
    """Model.build() + 刚体世界参数 + 裙摆阻尼 + 碰撞掩码读回。"""
    from bl_ext.user_default.mmd_tools.core import model as MModel
    from bl_ext.user_default.mmd_tools.core import rigid_body as MRigid

    res = StageResult("S2_build")
    t0 = _now()
    cfg = preset["physics"]

    # 掩码通道：`buildRigids()` 只给"距离够近"的被排除对建 disable_collisions 约束，
    # 这个比例决定多近才算够近。1.5 是 mmd_tools 上游默认；预设调大 → 覆盖更多对，
    # 代价是场景里约束对象变多、建场变慢。**读回的数（mask.coverage）才是判据**，
    # 不是"我把参数调大了"。
    scale = cfg.get("non_collision_distance_scale", 1.5)
    try:
        MModel.Model(root).build(non_collision_distance_scale=float(scale))
    except ValueError as exc:
        res.add("S8", BLOCK, "non_collision_distance_scale 不是数字：%r（%s）" % (scale, exc),
                "建议给 1.5（上游默认）或更大")
        res.elapsed = _now() - t0
        return res
    except Exception as exc:
        res.add("E-05", BLOCK, "Model.build() 失败：%s" % exc)
        res.elapsed = _now() - t0
        return res

    MRigid.setRigidBodyWorldEnabled(True)
    rbw = bpy.context.scene.rigidbody_world
    if rbw is None:
        res.add("G1", BLOCK, "场景没有 rigidbody_world")
        res.elapsed = _now() - t0
        return res
    rbw.enabled = True
    rbw.substeps_per_frame = cfg["substeps_per_frame"]
    rbw.solver_iterations = cfg["solver_iterations"]
    rbw.point_cache.frame_start = 1
    rbw.point_cache.frame_end = 2400        # 真实上界在 S3 拿到动作长度后收紧

    skirt = [o for o in rigid_bodies() if is_skirt(o.name)]
    for obj in skirt:
        if obj.rigid_body:
            obj.rigid_body.angular_damping = cfg["angular_damping"]
            obj.rigid_body.linear_damping = cfg["linear_damping"]
    if not skirt:
        res.add("E-00", WARN,
                "没有匹配到裙/下擺类刚体，阻尼 %s/%s 未施加（沿用模型自带值）"
                % (cfg["angular_damping"], cfg["linear_damping"]))

    hist = constraint_histogram(arm)
    chained = hist.get("COPY_ROTATION", 0) + hist.get("COPY_TRANSFORMS", 0)
    rigids = len(rigid_bodies())
    mask = mask_report()
    wired = None
    if cfg.get("apply_collision_masks", True):
        wired = apply_collision_masks()
        mask = mask_report()               # 打完之后重新读回，报的是**实际生效**的数

    res.metrics.update({
        "is_built": bool(root.mmd_root.is_built),
        "skirt_bodies": len(skirt),
        "constraints": hist,
        "chained": chained,
        "chain_ratio": round(chained / rigids, 3) if rigids else 0.0,
        "substeps": rbw.substeps_per_frame,
        "solver_iterations": rbw.solver_iterations,
        "mask": {k: v for k, v in mask.items() if k != "rows"},
        "mask_scale": scale,
        "mask_wired": None if wired is None else {
            k: wired.get(k) for k in MASK_WIRED_KEYS},
    })
    if chained == 0:
        res.add("G2", BLOCK, "骨骼上没有 COPY_ROTATION/COPY_TRANSFORMS，衣摆不会动")
    elif rigids and chained < 0.8 * rigids:
        res.add("G2", WARN, "约束链覆盖率 %d/%d，低于 0.8" % (chained, rigids))
    if not rbw.enabled:
        res.add("G1", BLOCK, "刚体世界没开")

    # **fail-closed：通道开着而四条判据没全绿 ⇒ 在烘焙之前停下**（D0 15:11 / 总控 17:31②）。
    # 判据本身在 `mask_gate_reason()`（纯函数，离屏可测）；这里只负责把它变成 BLOCK 并 return，
    # 让 `runner.record()` 把 `blocked_by` 记上——`--force` 之外，后面到不了烘焙。
    # 半套通道 + 已烘焙的场景是最贵的「看起来像干净」：烧几十秒烘焙，然后被当作交付件
    # 引用几小时。这里宁可让建场红着，也不产出一个"通道部分生效"的可烘焙场景。
    gate_reason = mask_gate_reason(wired)
    if gate_reason is not None:
        res.add("S8", BLOCK, gate_reason,
                "补 constraint_factory / 放宽 max_constraints 之前不要烘焙；"
                "要出无通道的对照场景请显式设 physics.apply_collision_masks=false")
        res.elapsed = _now() - t0
        return res

    # S8 掩码判据（D0 2026-11-16：「交付场景的物理没按 MMD 的碰撞约定在跑」）。
    # 只在**能判**的时候判：没声明任何排除 → 无从谈起（不是满分）。
    if mask["declared_pairs"] and mask["blocked_pairs"] == 0:
        res.add("S8", BLOCK,
                "PMX 声明了 %d 对不该碰，场景里一对都没挡（disable_collisions 约束 0 条）"
                % mask["declared_pairs"],
                "non_collision_distance_scale=%.3g" % scale)
    elif mask["declared_pairs"]:
        want = float(cfg.get("mask_coverage_min") or 0.0)
        if want > 0 and mask["coverage"] < want:
            res.add("S8", WARN,
                    "掩码覆盖 %d/%d 对（%.1f%%），低于预设下限 %.1f%%"
                    % (mask["blocked_pairs"], mask["declared_pairs"],
                       100.0 * mask["coverage"], 100.0 * want),
                    "调大 non_collision_distance_scale（当前 %.3g）" % scale)
    elif mask["rigids"]:
        res.add("S8", INFO,
                "掩码没有声明任何排除（%d 个刚体全为「与所有组碰」），覆盖无从谈起"
                % mask["all_on_bodies"])

    # 烘焙（契约 B / `D-067` / `D-173`）：**显式参数**。`bake=None` 时这一段整段不执行，
    # metrics 里也不会多出 `bake` 键——不传 bake 的调用方（`runner.py`、交付构建链、
    # 各席的臂）读数逐字不变，这条有测试盯着。
    if bake is not None:
        try:
            record = stage_bake(bpy.context.scene, bake)
        except ValueError as exc:
            res.add("S8", BLOCK, "bake 参数不合法：%s" % exc,
                    "只认 frame_start/frame_end/fps，且 frame_end >= frame_start")
            res.elapsed = _now() - t0
            return res
        res.metrics["bake"] = dict(record)
        reason = bake_gate_reason(record)
        if reason is not None:
            res.add("S8", BLOCK, reason,
                    "烘焙没通过行为探针 ⇒ 这份场景不是「按契约 B 烘过」的交付件"
                    "（D-155/D-158：`is_baked` 标志位本身证明不了任何事）")
            res.elapsed = _now() - t0
            return res
    res.elapsed = _now() - t0
    return res


# ---------------------------------------------------------------- 物理资格修理

def stage_physics_policy(arm, mute_bones, policy_name: str):
    """把「判断器」的结论落到场景上：静音目标骨上的 COPY_ROTATION / COPY_TRANSFORMS。

    这一步是"修理"，必须可验证：修完回头看，目标骨上不应再有无静音的 COPY_*。
    """
    res = StageResult("S2_policy")
    t0 = _now()
    target = set(mute_bones)
    res.metrics["policy"] = policy_name
    res.metrics["bones_requested"] = len(target)

    if not target:
        res.metrics["constraints_muted"] = 0
        res.elapsed = _now() - t0
        return res

    muted = []
    for pbone in arm.pose.bones:
        if pbone.name not in target:
            continue
        for con in pbone.constraints:
            if con.type in ("COPY_ROTATION", "COPY_TRANSFORMS") and not con.mute:
                con.mute = True
                muted.append(pbone.name)
    res.metrics["constraints_muted"] = len(muted)
    res.metrics["bones_hit"] = len(set(muted))

    # 匹配校验：骨名对不上（rename_bones 改了名 / 模型自带后缀）会一根都静音不到
    if not muted:
        res.add("E-05", WARN,
                "要静音 %d 根骨，但场景里一根匹配的约束都没有（骨名对不上？）" % len(target),
                ", ".join(sorted(target)[:6]))

    # 修理后自校验
    still = []
    for pbone in arm.pose.bones:
        if pbone.name in target:
            for con in pbone.constraints:
                if con.type in ("COPY_ROTATION", "COPY_TRANSFORMS") and not con.mute:
                    still.append(pbone.name)
    res.metrics["still_unmuted"] = len(set(still))
    if still:
        res.add("E-05", WARN, "仍有约束未静音", ", ".join(sorted(set(still))[:6]))

    res.elapsed = _now() - t0
    return res


# ---------------------------------------------------------------- S3 动作接入
def stage_motion(preset, root, arm, vmd_path: str, frame_end_hint: int):
    res = StageResult("S3_motion")
    t0 = _now()
    cfg = preset["motion"]

    bpy.ops.object.select_all(action="DESELECT")
    root.select_set(True)
    bpy.context.view_layer.objects.active = root
    # mmd_tools 的 ImportVmd 把动作落在 scene.frame_current + 1 起，任何残留帧位都会
    # 整体平移整条动作（实测 NLA 拼接后残留 453 → action 变成 [454, 1286]，前半段全空）。
    bpy.context.scene.frame_current = 1
    try:
        bpy.ops.mmd_tools.import_vmd(
            filepath=vmd_path,
            scale=cfg["scale"] if "scale" in cfg else preset_mod.section(preset, "import")["scale"],
            bone_mapper=cfg["bone_mapper"],
            rename_bones=cfg["rename_bones"],
            use_underscore=cfg["use_underscore"],
            update_scene_settings=cfg["update_scene_settings"],
        )
    except Exception as exc:
        res.add("E-14", BLOCK, "import_vmd 参数或文件出错：%s" % exc)
        res.elapsed = _now() - t0
        return res, None

    action = arm.animation_data.action if arm.animation_data else None
    if action is None:
        res.add("G3", BLOCK, "动作没导入（action is None）——再渲就是 360 帧静止")
        res.elapsed = _now() - t0
        return res, None

    fcurves = len(action.fcurves)
    fr = action.frame_range
    action_end = int(fr[1])
    res.metrics.update({
        "action": action.name[:40],
        "frame_range": [int(fr[0]), action_end],
        "fcurves": fcurves,
    })
    if fcurves <= 100:
        res.add("G3", BLOCK, "只有 %d 条曲线，不像有效动作" % fcurves)

    # 帧率口径：VMD 帧号以 30fps 为基准。改 fps 不重采样，只改播放速度。
    fps = preset["render"]["fps"]
    if abs(fps - 30) > 1e-6:
        res.add("E-00", WARN,
                "VMD 基准 30fps，当前 %d fps 且不重采样：动作按 %.2f 倍速播放"
                % (fps, fps / 30.0),
                "%d 帧 → %.2f s（30fps 下 %.2f s）"
                % (action_end, action_end / fps, action_end / 30.0))

    # 不变量 #2：缓存必须覆盖动作全长（同时覆盖本次要渲的长度）
    rbw = bpy.context.scene.rigidbody_world
    cover = max(action_end, frame_end_hint)
    if rbw is not None:
        rbw.point_cache.frame_start = 1
        rbw.point_cache.frame_end = cover
        res.metrics["point_cache_end"] = cover
        if cover < action_end:
            res.add("E-10", BLOCK, "缓存范围 %d 没覆盖动作 %d" % (cover, action_end))

    res.elapsed = _now() - t0
    return res, action_end




def apply_unit_damping(phys, preset):
    """按**物理单元**加阻尼，而不是按名字。

    名字匹配只能覆盖"裙/下擺"，袖子/头发/挂件这类结构单元覆盖不到，只能沿用 PMX 自带参数。
    实测（卡芙卡袖子：25 刚体 / 24 闭环 / 焊接比 0.5 / 无 mode2，配 LaLaLand 高速手臂）：
        原始 10/20      → 袖刚体逐帧最大转角突变 46.8°（f47），有 1 帧 >45°
        只加阻尼        → 38.8°，>45° 的帧归零
        只提求解预算 20/60 → 37.5°，>45° 的帧归零
    两者收益接近，阻尼几乎不花时间。
    """
    cfg = preset["physics"]
    if cfg.get("unit_damping") is False:
        return {"skipped": "unit_damping=false"}
    ang = cfg.get("unit_angular_damping", cfg.get("angular_damping", 0.75))
    lin = cfg.get("unit_linear_damping", cfg.get("linear_damping", 0.25))

    # 过约束动态单元：多刚体 + 有闭环 + 焊接多 + 没有 mode2（纯动态，靠约束互拉）
    picked = []
    for u in getattr(phys, "units", []):
        bodies = getattr(u, "bodies", [])
        if len(bodies) < 8:
            continue
        if getattr(u, "cycle_rank", 0) < 3:
            continue
        if getattr(u, "welded_ratio", 0) < 0.35:
            continue
        modes = getattr(u, "modes", set()) or set()
        if 2 in modes:
            continue
        picked.append(u)
    ids = sorted({b for u in picked for b in u.bodies})

    objs = [o for o in bpy.data.objects if getattr(o, "mmd_type", None) == "RIGID_BODY"]
    by_index = {}
    for o in objs:
        head = o.name.split("_", 1)[0]
        if head.isdigit():
            by_index[int(head)] = o

    touched = 0
    for i in ids:
        o = by_index.get(i)
        if o is not None and o.rigid_body:
            o.rigid_body.angular_damping = ang
            o.rigid_body.linear_damping = lin
            touched += 1
    return {"units": len(picked), "rigid_bodies": touched,
            "angular_damping": ang, "linear_damping": lin,
            "unit_indices": [getattr(u, "uid", None) for u in picked][:8]}

# ---------------------------------------------------------------- 三点光（native 路线）
def _aim_at(light_obj, target):
    direction = (target - light_obj.location).normalized()
    light_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _setup_three_point(subject_center, extent, profile="skin", scale=0.05):
    """标准三点光。来自社区 cc-blender-skill 的 blender-lighting Recipe 0b。

    只用于 native 路线：HSR 走 ramp/SDF 卡通体系，那套不能用 PBR 三点光去打。
    比例/颜色/能量随距离的算法都是技能里给好的，不自己发明数。
    """
    from mathutils import Vector
    profiles = {
        "skin": (dict(ratio=(4.0, 1.0, 1.0), key=(1.0, 0.93, 0.82),
                      fill=(0.95, 0.96, 1.0), rim=(0.92, 0.92, 1.0))),
        "fabric": (dict(ratio=(3.0, 1.0, 0.5), key=(1.0, 0.97, 0.92),
                        fill=(0.92, 0.95, 1.0), rim=(0.95, 0.95, 1.0))),
    }
    p = profiles.get(profile, profiles["skin"])
    center = Vector(subject_center)
    light_dist = max(extent * 1.5, 1.0)
    # 技能里的能量是按 Cycles + 1m 主体算的；本管线是 EEVEE，实测要缩到 ~5%
    # （×1.0 时主体亮度 0.845、79% 过曝；×0.05 时 0.475、2.2%）
    base = 100.0 * (light_dist / 1.5) ** 2 * float(scale)
    key_e, fill_e, rim_e = (base * r for r in p["ratio"])

    made = []
    specs = (
        ("LGT-key", "AREA", key_e, p["key"], 0.5,
         (center.x + light_dist * 0.7, center.y - light_dist * 0.7, center.z + light_dist * 0.5)),
        ("LGT-fill", "AREA", fill_e, p["fill"], 1.0,
         (center.x - light_dist * 0.7, center.y - light_dist * 0.5, center.z + light_dist * 0.3)),
        ("LGT-rim", "SPOT", rim_e, p["rim"], None,
         (center.x, center.y + light_dist, center.z + light_dist * 0.5)),
    )
    for name, kind, energy, color, size, loc in specs:
        old = bpy.data.objects.get(name)
        if old:
            bpy.data.objects.remove(old, do_unlink=True)
        data = bpy.data.lights.new(name, type=kind)
        data.energy = energy
        data.color = color
        if kind == "SPOT":
            data.spot_size = 0.8727   # 50°
        else:
            data.size = size
        obj = bpy.data.objects.new(name, data)
        bpy.context.collection.objects.link(obj)
        obj.location = loc
        _aim_at(obj, center)
        made.append(name)
    return {"lights": made, "dist": round(light_dist, 3),
            "energy": [round(key_e, 1), round(fill_e, 1), round(rim_e, 1)],
            "ratio": list(p["ratio"]), "profile": profile}

# ---------------------------------------------------------------- S5 表现层

def stage_look(preset, mesh, arm):
    res = StageResult("S5_look")
    t0 = _now()
    cfg = preset["look"]
    scene = bpy.context.scene

    bpy.ops.object.select_all(action="DESELECT")
    mesh.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = mesh

    # 卡通着色的光照/明暗滑杆：以前从没碰过，一直是插件默认值。
    # 通用三点光是给 PBR 写的，硬套会破坏 HSR 的 ramp/SDF 体系，所以走这套。
    applied, unknown = {}, []
    for key, val in (cfg.get("hsr") or {}).items():
        attr = "morningstar_hsr_" + key
        if key in HSR_LOOK_KEYS and hasattr(scene, attr):
            setattr(scene, attr, float(val))
            applied[key] = round(float(val), 3)
        else:
            unknown.append(key)
    res.metrics["hsr_look_applied"] = applied
    if unknown:
        res.add("E-07", WARN, "未知的 look.hsr 键：%s" % ", ".join(unknown))

    # 外观路线：
    #   hsr    星铁角色专用（材质/SDF/描边全套）——宵宫这种原神模型会直接报"未找到对应角色"
    #   native 保留模型自带的 MMD 材质，只做世界背景
    #   auto   先试 hsr，材质那步失败就回退 native 并记一条 WARN（不阻断）
    route = (cfg.get("route") or "auto").lower()
    steps = {}
    route_effective = "native"
    if route in ("auto", "hsr"):
        calls = {
            "ENV": lambda: bpy.ops.jflhsr.setup_star_rail_environment(),
            "MAT": lambda: bpy.ops.jflhsr.assign_star_rail_materials(reset_legacy_ramp=False),
            "SDF": lambda: bpy.ops.jflhsr.set_star_rail_sdf(body_type=cfg["sdf_body_type"],
                                                           variant=cfg["sdf_variant"]),
            "LIGHT": lambda: bpy.ops.jflhsr.setup_light_vectors(),
            "OUTLINE": lambda: bpy.ops.jflhsr.setup_outlines(),
            "REFENV": lambda: bpy.ops.jflhsr.apply_reference_environment(),
        }
        for name in SIX_STEPS:
            try:
                steps[name] = str(calls[name]())
            except Exception as exc:
                steps[name] = "ERR:%s" % type(exc).__name__
                res.add("E-07", BLOCK, "HSR 第 %s 步失败：%s" % (name, exc))
        route_effective = "hsr"

        # 自动回退：HSR 材质只认星铁角色。别的模型不该因此整条流程挂掉。
        # 但 ENV / LIGHT / REFENV 是**场景级**的，对非星铁模型一样有效——
        # 所以只丢掉角色专属的 MAT / SDF / OUTLINE，其余保留，观感仍是"崩铁同款"。
        if route == "auto" and str(steps.get("MAT", "")).startswith("ERR"):
            route_effective = "hsr_scene"
            for it in list(res.issues):
                if it.code == "E-07" and any(k in it.hint for k in ("HSR 第 MAT", "HSR 第 SDF",
                                                                   "HSR 第 OUTLINE")):
                    res.issues.remove(it)
            res.ok = not res.blocked
            res.add("E-07", WARN,
                    "角色材质不适用（%s），保留场景级光照/环境，跳过角色专属材质与描边"
                    % str(steps.get("MAT"))[6:], "route=auto → hsr_scene")

        # 官方后期处理：插件自带 HoYoverse - Post Processing 节点组。
        if cfg.get("post_processing") and route_effective in ("hsr", "hsr_scene"):
            try:
                bpy.ops.jflhsr.import_post_processing()
                steps["POST"] = "FINISHED"
                scene.render.use_compositing = True
                res.metrics["post_processing"] = True
            except Exception as exc:
                steps["POST"] = "ERR:%s" % type(exc).__name__
                res.add("E-07", WARN, "后期处理没接上：%s" % exc)

    if route_effective in ("native", "hsr_scene"):
        # 两种情况都需要三点光，但原因不同：
        #   native     场景里一盏灯都没有，只剩 0.6 强度世界背景 → 发闷
        #   hsr_scene  HSR 的 setup_light_vectors 是给星铁材质接光向量的，
        #              原生材质接不上，实测主体亮度和"完全没灯"一样（0.244 vs 0.266）
        #              所以崩铁的环境/后期照用，灯还是要补。
        meshes_n = [o for o in bpy.data.objects if o.type == "MESH"]
        if meshes_n and (cfg.get("lighting") is not False):
            dg = bpy.context.evaluated_depsgraph_get()
            pts = []
            for obj in meshes_n:
                ev = obj.evaluated_get(dg)
                mw = ev.matrix_world
                pts.extend(mw @ Vector(c) for c in ev.bound_box)
            mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
            mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
            extent = max(mx.x - mn.x, mx.y - mn.y, mx.z - mn.z)
            res.metrics["lighting"] = _setup_three_point(
                (mn + mx) / 2, extent, cfg.get("lighting_profile", "skin"),
                cfg.get("light_scale", 0.05))

    res.metrics["route_requested"] = route
    res.metrics["route_effective"] = route_effective
    res.metrics["steps"] = steps
    res.metrics["materials"] = len(mesh.data.materials)



    # REFENV 之后必须覆盖世界颜色，否则纯黑
    if scene.world and scene.world.node_tree:
        bg = next((n for n in scene.world.node_tree.nodes if n.type == "BACKGROUND"), None)
        if bg:
            bg.inputs[0].default_value = tuple(cfg["bg_color"])
            bg.inputs[1].default_value = cfg["bg_strength"]
            res.metrics["bg"] = [round(v, 3) for v in cfg["bg_color"]] + [cfg["bg_strength"]]
        else:
            res.add("G6", WARN, "世界节点里没有 Background，可能渲出黑底")

    # 描边存在性：它是几何节点修改器，不是材质槽
    outline_mods = []
    for mod in mesh.modifiers:
        if mod.type == "NODES" and mod.node_group and "Outlines" in mod.node_group.name:
            outline_mods.append(mod.name)
    res.metrics["outline_modifiers"] = outline_mods
    if cfg["outline"] and not outline_mods:
        res.add("E-07", WARN, "网格上没有 Outlines 几何节点，描边可能没生效")

    res.elapsed = _now() - t0
    return res


# ---------------------------------------------------------------- 道具挂接

# 换模型时骨名习惯不同：日系常用 手首.R，也见过 右手首 / hand.R
BONE_ALIASES = {
    "右手首": ("右手首", "手首.R", "手首右", "hand.R", "righthand"),
    "左手首": ("左手首", "手首.L", "手首左", "hand.L", "lefthand"),
    "右手": ("右手", "手.R", "hand.R"),
    "左手": ("左手", "手.L", "hand.L"),
    "頭": ("頭", "头", "head"),
}


def resolve_bone(arm, name: str):
    """返回 (真实骨名, 说明)；找不到返回 (None, 候选列表)。"""
    names = [b.name for b in arm.data.bones]
    if name in names:
        return name, "exact"
    for cand in BONE_ALIASES.get(name, ()):
        if cand in names:
            return cand, "别名 %s→%s" % (name, cand)
    hits = [n for n in names if name in n]
    if len(hits) == 1:
        return hits[0], "子串 %s→%s" % (name, hits[0])
    return None, hits[:8]


def stage_props(preset, arm):
    """把独立道具 PMX 挂到角色骨骼上。

    道具是单骨模型，建模在自己的局部空间（离角色很远），所以必须：
    导入 → 父级设为角色骨 → 用 matrix_world 把道具那根骨对准目标骨 head。
    """
    from mathutils import Euler, Matrix

    res = StageResult("S6_props")
    t0 = _now()
    specs = preset.get("props") or []
    if not specs:
        res.elapsed = _now() - t0
        return res

    bpy.context.scene.frame_set(1)
    attached = []

    for spec in specs:
        path = spec.get("pmx")
        bone_req = spec.get("bone", "手首.R")
        if not path or not os.path.exists(path):
            res.add("E-16", BLOCK, "道具文件不存在：%s" % path)
            continue
        bone, note = resolve_bone(arm, bone_req)
        if bone is None:
            res.add("E-17", BLOCK, "找不到挂接骨 %s" % bone_req,
                    "候选：%s" % (", ".join(note) if isinstance(note, list) else note))
            continue

        before = set(o.name for o in bpy.data.objects)
        try:
            bpy.ops.mmd_tools.import_model(
                filepath=path, scale=preset_mod.section(preset, "import")["scale"],
                types={"MESH", "ARMATURE"}, clean_model=True,
                rename_bones=True, log_level="ERROR")
        except Exception as exc:
            res.add("E-16", BLOCK, "道具导入失败 %s：%s" % (os.path.basename(path), exc))
            continue

        added = [bpy.data.objects[n] for n in set(o.name for o in bpy.data.objects) - before]
        prop_root = next((o for o in added if getattr(o, "mmd_type", None) == "ROOT"), None)
        if prop_root is None:
            res.add("E-16", BLOCK, "道具没有 ROOT 对象：%s" % os.path.basename(path))
            continue
        prop_arm = bpy.data.objects.get(prop_root.name + "_arm")
        if prop_arm is None or not prop_arm.pose.bones:
            res.add("E-16", BLOCK, "道具没有骨架：%s" % os.path.basename(path))
            continue

        pbone = arm.pose.bones[bone]
        target_w = arm.matrix_world @ pbone.head
        prop_bone = prop_arm.pose.bones[0]

        prop_root.parent = arm
        prop_root.parent_type = "BONE"
        prop_root.parent_bone = bone
        bpy.context.view_layer.update()

        err_before = ((prop_arm.matrix_world @ prop_bone.head) - target_w).length
        delta = target_w - (prop_arm.matrix_world @ prop_bone.head)
        prop_root.matrix_world = Matrix.Translation(delta) @ prop_root.matrix_world

        rot = spec.get("rot")
        if rot:
            rot_m = Euler([float(v) for v in rot], "XYZ").to_matrix().to_4x4()
            pivot = Matrix.Translation(target_w) @ rot_m @ Matrix.Translation(-target_w)
            prop_root.matrix_world = pivot @ prop_root.matrix_world
        loc = spec.get("loc")
        if loc:
            prop_root.matrix_world = Matrix.Translation(
                [float(v) for v in loc]) @ prop_root.matrix_world

        bpy.context.view_layer.update()
        err = ((prop_arm.matrix_world @ prop_bone.head) - target_w).length
        attached.append({"pmx": os.path.basename(path), "bone": bone,
                         "resolved_by": note,
                         "root": prop_root.name, "err_mm": round(err * 1000, 3),
                         "moved_m": round(err_before, 3)})
        if err > 1e-4:
            res.add("G9", WARN, "%s 挂接后偏差 %.3f mm"
                    % (os.path.basename(path), err * 1000))

    res.metrics["attached"] = attached
    res.metrics["count"] = len(attached)
    if len(attached) != len(specs):
        res.add("G9", BLOCK, "要求挂 %d 个道具，成功 %d 个" % (len(specs), len(attached)))
    res.elapsed = _now() - t0
    return res


# ---------------------------------------------------------------- S6 预演取景

def stage_camera(preset, frame_start: int, frame_end: int):
    res = StageResult("S6_camera")
    t0 = _now()
    cfg = preset["camera"]
    rcfg = preset["render"]
    scene = bpy.context.scene

    scene.frame_start = frame_start
    scene.frame_end = frame_end
    scene.render.fps = rcfg["fps"]

    # 冻结相机：有值就直接用，不测包围盒。
    # 理由（实测）：全片包围盒由裙摆/头发刚体决定，而 270 刚体 + 339 弹簧
    # 这套系统逐次重算会分叉；同一文件两次进程测出 X 1.005 / 1.159。
    # 渲同一帧却是逐像素相同的 —— 所以不稳定的是取景，不是渲染。
    if cfg.get("loc") and cfg.get("rot"):
        cam_data = bpy.data.cameras.new("CAM_sample")
        cam_data.lens = cfg["lens"]
        cam = bpy.data.objects.new("CAM_sample", cam_data)
        scene.collection.objects.link(cam)
        cam.location = tuple(cfg["loc"])
        cam.rotation_euler = tuple(cfg["rot"])
        scene.camera = cam
        res.metrics.update({
            "source": "frozen",
            "loc": [round(v, 4) for v in cam.location],
            "rot": [round(v, 4) for v in cam.rotation_euler],
            "lens": cfg["lens"],
        })
        # 冻结机位也必须验一遍覆盖：预设可能是按别的动作做的，
        # 长走位动作会直接跑出框。只报不改（要改就显式给 auto_refit）。
        f0, f1 = scene.frame_start, scene.frame_end
        fmetrics, fissues = check_framing(cam, range(f0, f1 + 1, 10))
        res.metrics["framing"] = fmetrics
        for code, level, msg, detail in fissues:
            res.add(code, level, msg, detail)
        if fissues and cfg.get("auto_refit"):
            bpy.data.objects.remove(cam, do_unlink=True)
            res.metrics["refit_reason"] = "冻结机位未覆盖运动路径，改按全片包围盒重新取景"
            return _fit_camera(res, preset, frame_start, frame_end, t0)
        res.elapsed = _now() - t0
        return res, cam

    # 没有冻结机位 → 按全片包围盒取景（抽取函数时漏了这条返回路径，会返回 None）
    return _fit_camera(res, preset, frame_start, frame_end, t0)



def _fit_camera(res, preset, frame_start: int, frame_end: int, t0):
    """按全片包围盒取景（原本内联在 stage_camera 里，抽出来给冻结机位回退用）。"""
    cfg = preset["camera"]
    rcfg = preset["render"]
    scene = bpy.context.scene

    rigids = rigid_bodies()
    if not rigids:
        res.add("G7", BLOCK, "没有刚体，无法测全片包围盒")
        res.elapsed = _now() - t0
        return res, None

    # 取景必须按"看得见的东西"算：网格（含形变）+ 骨骼 + 刚体。
    # 只统计刚体会漏掉脚底/头顶——卡芙卡 145 个刚体只覆盖 1.258 m，实际身高约 1.7 m，
    # 结果按"矮个子"取景，脚下贴边。
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]

    pts = []
    for frame in range(frame_start, frame_end + 1):
        scene.frame_set(frame)
        dg = bpy.context.evaluated_depsgraph_get()
        for obj in meshes:
            evaluated = obj.evaluated_get(dg)
            mw = evaluated.matrix_world
            for corner in evaluated.bound_box:
                pts.append(mw @ Vector(corner))
        for obj in arms:
            mw = obj.matrix_world
            for pbone in obj.pose.bones:
                pts.append(mw @ pbone.head)
        for obj in rigids:
            pts.append(obj.matrix_world.translation)

    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    center = (mn + mx) / 2
    size = mx - mn

    res_w, res_h = rcfg["resolution"]
    sensor = cfg["sensor"]
    lens = cfg["lens"]
    aspect = res_w / res_h
    tan_h = (sensor / 2.0) / lens
    tan_v = ((sensor / aspect) / 2.0) / lens
    margin = cfg["margin"]
    dist = max(size.x / 2 * margin / tan_h,
               size.z / 2 * margin / tan_v,
               size.y / 2 + 1.0)

    cam_data = bpy.data.cameras.new("CAM_sample")
    cam_data.lens = lens
    cam = bpy.data.objects.new("CAM_sample", cam_data)
    scene.collection.objects.link(cam)
    dx, dy, dz = cfg["direction"]
    cam.location = (center.x + dist * dx, center.y + dist * dy, center.z + dist * dz)
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam

    horizontal_deg = 2 * 57.29577951308232 * __import__("math").atan(tan_h)
    res.metrics.update({
        "source": "measured",
        "frames_sampled": frame_end - frame_start + 1,
        "points_collected": len(pts),
        "bbox": [round(v, 3) for v in size],
        "center": [round(v, 3) for v in center],
        "dist": round(dist, 3),
        "fov_h_deg": round(horizontal_deg, 2),
        "subject_height_pct": round(size.z / (2 * dist * tan_v) * 100, 1),
        "loc": [round(v, 4) for v in cam.location],
        "rot": [round(v, 4) for v in cam.rotation_euler],
    })
    if size.z <= 0.01:
        res.add("G7", BLOCK, "包围盒高度≈0，角色可能没被渲染进来")
    fmetrics, fissues = check_framing(cam, range(frame_start, frame_end + 1, 10))
    res.metrics["framing"] = fmetrics
    for code, level, msg, detail in fissues:
        res.add(code, level, msg, detail)
    res.elapsed = _now() - t0
    return res, cam


# ---------------------------------------------------------------- S7 渲染

def stage_render(preset, out_dir: str, frame_start: int, frame_end: int, encode_to: str):
    res = StageResult("S7_render")
    t0 = _now()
    rcfg = preset["render"]
    scene = bpy.context.scene

    os.makedirs(out_dir, exist_ok=True)
    for name in os.listdir(out_dir):
        if name.endswith(".png"):
            os.remove(os.path.join(out_dir, name))

    scene.render.resolution_x = rcfg["resolution"][0]
    scene.render.resolution_y = rcfg["resolution"][1]
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.eevee.taa_render_samples = rcfg["taa_render_samples"]

    # 不变量 #3：从第 1 帧连续 frame_set，段内不跳帧、不改 frame_start
    for frame in range(frame_start, frame_end + 1):
        scene.frame_set(frame)
        scene.render.filepath = os.path.join(out_dir, "s_%04d" % frame)
        bpy.ops.render.render(write_still=True)
        if (frame - frame_start) % 60 == 0:
            elapsed = _now() - t0
            print("  f %4d elapsed %.0fs per_frame %.2f"
                  % (frame, elapsed, elapsed / (frame - frame_start + 1)), flush=True)

    res.metrics["render_seconds"] = round(_now() - t0, 1)
    res.metrics["frames_rendered"] = frame_end - frame_start + 1

    mp4 = encode_to
    cmd = [rcfg["ffmpeg"], "-y", "-framerate", str(rcfg["fps"]),
           "-start_number", str(frame_start),
           "-i", os.path.join(out_dir, "s_%04d.png"),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", str(rcfg["crf"]),
           "-movflags", "+faststart", mp4]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        res.add("E-21", BLOCK, "ffmpeg 编码失败", proc.stderr[-300:])
    if not os.path.exists(mp4):
        res.add("E-21", BLOCK, "编码产物不存在：%s" % mp4)
    else:
        res.metrics["mp4_mb"] = round(os.path.getsize(mp4) / 1024 / 1024, 2)
        res.artifacts.append(mp4)

    res.elapsed = _now() - t0
    return res


# ---------------------------------------------------------------- S4 物理活性

def stage_probe(preset, frame_start=1, frames=12, step=10):
    res = StageResult("S4_probe")
    t0 = _now()
    scene = bpy.context.scene
    rbw = scene.rigidbody_world
    res.metrics["baked"] = bool(rbw.point_cache.is_baked) if rbw else None
    res.metrics["enabled"] = bool(rbw.enabled) if rbw else None

    rigids = rigid_bodies()
    hip = next((o for o in rigids if "下半身" in o.name), None)
    skirt = next((o for o in rigids if is_skirt(o.name)), None)
    hair = next((o for o in rigids if is_hair(o.name)), None)

    # 名字无关的回退：换模型时命名习惯会变（卡芙卡的刚体全是 HairA1_JNT 这种英文名）。
    # 与其不停补模式，不如直接找"相对髋部 10 帧位移最大"的刚体当探针对象。
    picked = "skirt" if skirt else ("hair" if hair else None)
    if hip and not (skirt or hair):
        scene.frame_set(frame_start)
        base = {o.name: (o.matrix_world.translation - hip.matrix_world.translation).copy()
                for o in rigids}
        scene.frame_set(frame_start + step)
        moves = {}
        for o in rigids:
            if o.name == hip.name:
                continue
            cur = o.matrix_world.translation - hip.matrix_world.translation
            moves[o.name] = (cur - base[o.name]).length
        if moves:
            top_name = max(moves, key=moves.get)
            skirt = bpy.data.objects.get(top_name)
            hair = None
            picked = "top_mover"
            res.metrics["top_mover"] = top_name
            res.metrics["top_mover_10f_m"] = round(moves[top_name], 4)

    if not hip or not (skirt or hair):
        res.add("G5", WARN, "找不到髋部或可动刚体，跳过活性探针",
                "hip=%s skirt=%s hair=%s" % (bool(hip), bool(skirt), bool(hair)))
        res.elapsed = _now() - t0
        return res

    target = skirt if skirt else hair
    other = hair if (hair is not None and hair is not target) else None

    samples = []
    for i in range(frames):
        frame = frame_start + i * step
        scene.frame_set(frame)
        rel = (target.matrix_world.translation - hip.matrix_world.translation).copy()
        rel2 = None
        if other is not None:
            rel2 = (other.matrix_world.translation - hip.matrix_world.translation).copy()
        samples.append((frame, rel, rel2))

    def max_change(idx):
        """相邻采样之间的位移（对应报告里的「每 10 帧变化量」），不是相对第 1 帧的累计。"""
        vals = []
        for prev, cur in zip(samples, samples[1:]):
            if prev[idx] is not None and cur[idx] is not None:
                vals.append((cur[idx] - prev[idx]).length)
        return max(vals) if vals else 0.0

    main_chg = max_change(1)
    other_chg = max_change(2)
    res.metrics.update({
        "hip": hip.name,
        "probe_target": target.name,
        "other": other.name if other else None,
        "target_max_change_m": round(main_chg, 4),
        "other_max_change_m": round(other_chg, 4),
        "frames_probed": frames * step,
    })
    if main_chg <= 0.005:
        res.add("G5", BLOCK,
                "探针刚体相对髋部几乎不动（%.4f m），物理没生效——刚性绑在骨骼上" % main_chg)
    res.elapsed = _now() - t0
    return res


# ---------------------------------------------------------------- S8 验收

def _load_pixels(path: str):
    img = bpy.data.images.load(path, check_existing=False)
    try:
        w, h = img.size
        px = list(img.pixels)
    finally:
        bpy.data.images.remove(img)
    return w, h, px


def _quick_stats(path: str):
    w, h, px = _load_pixels(path)
    n = w * h
    total = 0.0
    for i in range(0, n * 4, 4):
        total += px[i] + px[i + 1] + px[i + 2]
    return total / (n * 3)


def _frame_diff(path_a: str, path_b: str):
    w, h, a = _load_pixels(path_a)
    w2, h2, b = _load_pixels(path_b)
    if (w, h) != (w2, h2):
        return None
    n = min(len(a), len(b))
    total = 0.0
    for i in range(0, n, 4):
        total += abs(a[i] - b[i]) + abs(a[i + 1] - b[i + 1]) + abs(a[i + 2] - b[i + 2])
    return total / ((n // 4) * 3)


def stage_verify(preset, png_dir: str, mp4: str, frame_start: int, frame_end: int):
    res = StageResult("S8_verify")
    t0 = _now()
    rcfg = preset["render"]
    expected = frame_end - frame_start + 1

    # 1 帧数连续
    names = sorted(n for n in os.listdir(png_dir) if n.endswith(".png")) if os.path.isdir(png_dir) else []
    res.metrics["png_count"] = len(names)
    nums = []
    for name in names:
        try:
            nums.append(int(name[2:6]))
        except ValueError:
            pass
    if len(names) != expected:
        res.add("G8", BLOCK, "PNG 数量 %d ≠ 期望 %d" % (len(names), expected))
    elif nums != list(range(frame_start, frame_end + 1)):
        res.add("G8", BLOCK, "PNG 编号不连续（E-21：ffmpeg 序列要求连续）")

    # 2 时长 / 帧率
    if os.path.exists(mp4):
        cmd = [rcfg["ffprobe"], "-v", "error", "-count_frames", "-select_streams", "v:0",
               "-show_entries", "stream=nb_read_frames,avg_frame_rate,duration",
               "-of", "default=nw=1", mp4]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        info = {}
        for line in proc.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                info[k.strip()] = v.strip()
        res.metrics["mp4_frames"] = info.get("nb_read_frames")
        res.metrics["mp4_duration"] = info.get("duration")
        res.metrics["mp4_fps"] = info.get("avg_frame_rate")
        try:
            got_frames = int(info.get("nb_read_frames", 0))
            got_dur = float(info.get("duration", 0))
        except ValueError:
            got_frames, got_dur = 0, 0.0
        if got_frames != expected:
            res.add("G8", BLOCK, "成片帧数 %d ≠ 期望 %d" % (got_frames, expected))
        want_dur = expected / rcfg["fps"]
        if abs(got_dur - want_dur) > 1.0 / rcfg["fps"]:
            res.add("G8", BLOCK, "时长 %.3fs ≠ 期望 %.3fs" % (got_dur, want_dur))
        res.metrics["duration_delta_s"] = round(got_dur - want_dur, 4)
    else:
        res.add("G8", BLOCK, "成片不存在")

    # 3 可见性 + 非静止（读两张已渲的图，不额外渲染）
    first = os.path.join(png_dir, "s_%04d.png" % frame_start)
    mid = os.path.join(png_dir, "s_%04d.png" % (frame_start + (expected - 1) // 2))
    if os.path.exists(first) and os.path.exists(mid):
        lum = _quick_stats(first)
        res.metrics["first_frame_mean_luma"] = round(lum, 4)
        if lum < 0.02:
            res.add("G6", BLOCK, "首帧平均亮度 %.4f，几乎是黑片" % lum)
        diff = _frame_diff(first, mid)
        res.metrics["first_vs_mid_diff"] = round(diff, 5) if diff is not None else None
        if diff is not None and diff < 0.002:
            # 片段太短时首帧与中帧本来可以几乎一样（例如只渲 24 帧、动作刚起步），
            # 这时判 BLOCK 是误报。48 帧（1.6 s @30fps）以上才有判据意义。
            if expected < 48:
                res.add("G4", WARN,
                        "片段仅 %d 帧，首帧与中帧差异 %.5f 不足以判定静止（跳过）"
                        % (expected, diff))
            else:
                res.add("G4", BLOCK,
                        "首帧与中帧几乎相同（%.5f），动作可能是静止的" % diff)

    # 3.5 取景门禁：用**渲染出来的像素**判出框与构图漂移。
    # 这是唯一可信的口径——骨点会被 つま先ＩＫ 这类控制骨拉偏，网格包围盒是轴对齐且含静止姿态。
    check_frames = [f for f in range(frame_start, frame_end + 1, max(1, expected // 40))]
    fb = _framing_from_images(png_dir, check_frames)
    if fb:
        res.metrics["framing_from_images"] = fb
        if fb["worst_margin"] < 0.01:
            res.add("G9", WARN,
                    "角色贴边/出框：最窄边距 %.3f（帧 %d）"
                    % (fb["worst_margin"], fb["worst_frame"]))
        if fb["centroid_span"] > 0.30:
            res.add("G9", WARN,
                    "构图漂移：主体横向质心跨度 %.2f（%.2f → %.2f），固定机位没跟拍"
                    % (fb["centroid_span"], fb["centroid_x"][0], fb["centroid_x"][1]))

    # 联络表：用 ffmpeg 的 tile 滤镜拼一张缩略图总览（现成工具，不自己写拼图）。
    # 目的：验收时先看一张图，而不是逐帧翻。
    try:
        step = max(1, expected // 12)
        sheet = os.path.abspath(os.path.join(png_dir, "..", "contact_sheet.png"))
        cmd = [rcfg["ffmpeg"], "-y",
               "-start_number", str(frame_start),
               "-i", os.path.join(png_dir, "s_%04d.png"),
               "-vf", r"select='not(mod(n\,%d))',scale=320:-1,tile=4x3" % step,
               "-frames:v", "1", "-update", "1", sheet]
        r = subprocess.run(cmd, capture_output=True, timeout=180)
        if os.path.exists(sheet):
            res.artifacts.append(sheet)
            res.metrics["contact_sheet"] = sheet
            res.metrics["contact_sheet_step"] = step
        else:
            res.add("E-00", WARN, "联络表没生成：%s" % (r.stderr[-200:].decode("utf-8", "replace")))
    except (OSError, subprocess.SubprocessError) as exc:
        res.add("E-00", WARN, "联络表生成失败：%s" % exc)

    res.elapsed = _now() - t0
    return res


def _framing_from_images(png_dir, frames):
    """在已渲的帧上量主体包围盒与质心。

    用项目自带的 _load_pixels 读图（Blender 的 Python 没有 PIL），
    背景取四角中位亮度，不假设具体颜色。
    """
    import statistics

    lefts, rights, cents, margins = [], [], [], []
    worst = (1.0, frames[0] if frames else 0)
    used = 0
    for f in frames:
        p = os.path.join(png_dir, "s_%04d.png" % f)
        if not os.path.exists(p):
            continue
        try:
            w, h, px = _load_pixels(p)
        except (OSError, ValueError):
            continue
        def lum(x, y):
            i = (y * w + x) * 4
            return (px[i] + px[i + 1] + px[i + 2]) / 3.0
        bg = statistics.median([lum(0, 0), lum(w - 1, 0), lum(0, h - 1), lum(w - 1, h - 1)])
        step = max(1, min(w, h) // 160)
        xs = []
        for y in range(0, h, step):
            for x in range(0, w, step):
                if abs(lum(x, y) - bg) > 0.07:   # pixels 是 0..1 浮点，不是 0..255
                    xs.append(x)
        if not xs:
            continue
        used += 1
        lo, hi = min(xs) / w, max(xs) / w
        lefts.append(lo)
        rights.append(hi)
        cents.append((lo + hi) / 2)
        m = min(lo, 1.0 - hi)
        margins.append(m)
        if m < worst[0]:
            worst = (m, f)
    if not used:
        return None
    return {
        "frames_checked": used,
        "left_range": [round(min(lefts), 3), round(max(lefts), 3)],
        "right_range": [round(min(rights), 3), round(max(rights), 3)],
        "centroid_x": [round(min(cents), 3), round(max(cents), 3)],
        "centroid_span": round(max(cents) - min(cents), 3),
        "worst_margin": round(worst[0], 3),
        "worst_frame": worst[1],
    }