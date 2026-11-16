"""交付链的「应用动作」这一步（`D-186` / M05）。

**为什么是「一个函数 + 一条 CLI」，而不是重写一段流水线**：`stage.stage_motion`
（`stage.py:1009`）已经把「`import_vmd` → 断言 action 非空 → 覆盖物理缓存范围」做完了，
真流水线 `runner.py:661` 就在用它。交付包装器 `m02_rebuild_scene_v3.py` 只调了
`stage_import` + `stage_build` 就收工，所以交付件 `actions == []`。

缺的从来不是「导入动作」这段代码，而是它外面的三件事：

1. **幂等**：重跑前清掉上一次的 action / NLA 轨道。不清就会在同一个骨架上叠加两个动作，
   第二次跑出来的东西和第一次不是一件事，而报告里看不出来。
2. **窗口**：`--trim-end` / `--hold-until`，把动作对齐到预注册的帧窗口
   （`C@W1` = 1..240、`C@W2` = 1..832 且 301..832 末帧定格、`D` = 1..832）。
3. **回读**：`scene.frame_end` 只按 `action.frame_range` 的**读回值**设，并把
   `point_cache.is_baked` 读回 —— **应用 ≠ 烘焙**，应用完仍必须是 false。

帧号口径：mmd_tools 的 `ImportVmd` 落在 `scene.frame_current + 1`（`stage.py:1017-1019`
已经为此把 `frame_current` 复位到 1），所以 VMD `0..832` 应用后是 `1..833`。
`plan()` 把这笔换算显式写进记录，不留给下游猜。

`blender -b <in.blend> -P mmdpipe/apply_action.py -- --vmd A.vmd --preset P.json --out-blend B.blend --json R.json [--trim-end 240]`
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys

try:                       # 作为包的一部分（Blender 扩展里是 mmd_pipeline.mmdpipe）
    from . import vmd as vmd_mod
except ImportError:        # 作为独立脚本跑：blender -b -P mmdpipe/apply_action.py
    if __package__ in (None, ""):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from mmdpipe import vmd as vmd_mod

# `stage_motion` 自己用 100 条曲线当「不像有效动作」的界线（`stage.py:1048`），
# 这里沿用同一个数，不另立一个阈值。
MIN_FCURVES = 100
# mmd_tools ImportVmd 落在 frame_current + 1
IMPORT_OFFSET = 1


class PlanError(ValueError):
    """窗口参数自相矛盾 —— 此时一个字节都不该写进场景。"""


def lock_tail_verdict(start, end):
    """开局与收尾两处锁身份的对照（`D-188` 尾部闸，纯函数，离屏可测）。

    开头 assert 只证明「**开始时**锁是你的」，不证明「结束时还是」：心跳过 10 分钟可能被别人
    `reclaim`，也可能你先放了、别人 `acquire` 到你下一阶段 —— 那时的景象最坏：两边都觉得自己
    在锁里，各写各的产物，事后查不出来谁越界。所以两处 ident 必须相同，不同即该臂作废。
    """
    sid = (start or {}).get("ident")
    eid = (end or {}).get("ident")
    if not sid or not eid:
        return False, "锁身份缺失（start=%r end=%r），无法证明收尾时仍持锁 ⇒ 该臂作废" % (sid, eid)
    if sid != eid:
        return False, ("锁在中途易主：开局 %r → 收尾 %r ⇒ 该臂作废（读数不得使用）"
                       % (sid, eid))
    return True, "锁身份一致：%r（开局心跳 %ss / 收尾心跳 %ss）" % (
        sid, (start or {}).get("heartbeat_age"), (end or {}).get("heartbeat_age"))


def versioned_out_path(out_dir, batch_id, name):
    """臂产物的**版本化落盘**路径：`<out_dir>/<batch_id>/<name>.blend`（`D-189`）。

    为什么：臂件是「那次读数的物证」，不是中间产物。覆盖同一路径会让读数与文件的对应关系断掉
    ——`2号` 钉的 `251146e9…` 一度在盘上找不到，下一个拿 sha 去核的人会怀疑整批。所以重跑一律
    落新路径，旧件留着（并冻结成只读）。
    """
    if not out_dir or not batch_id or not name:
        raise PlanError("版本化落盘要三样都给：out_dir=%r batch_id=%r name=%r"
                        % (out_dir, batch_id, name))
    safe = re.sub(r"[^0-9A-Za-z_.@-]+", "_", str(batch_id))
    arm = re.sub(r"[^0-9A-Za-z_.@-]+", "_", str(name))
    return os.path.join(out_dir, safe, arm + ".blend")


def freeze_file(path):
    """把已交付的臂件设成只读（落地「旧件留着当物证」）。返回实际生效的模式。"""
    os.chmod(path, 0o444)
    return oct(os.stat(path).st_mode & 0o777)


def assert_lock_owner(owner, *, lock_dir=None, checker=None):
    """**跑 Blender 之前的第一句**：这把锁现在必须是自己的，否则立刻失败（`D-188`）。

    为什么：`coordination.lock acquire` 在锁被占时本来就 exit 3，但**退出码管不住不看的人** ——
    我 11-16 18:18 拿到 `LOCK_HELD` 没看就起了 7 个 Blender 进程。这条检查把「没持锁跑」
    变成「进程根本不往下走」，而不是「跑完了才发现」。

    `checker` 可注入（离屏测试用），默认 `coordination.lock.assert_owner`（只读不写）。
    """
    if not owner or "|" not in str(owner):
        raise SystemExit("用法错误：--owner 必须写成 `模块|工作树`（例如 `模块负责3|A3`）")
    if checker is None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root not in sys.path:
            sys.path.insert(0, root)
        try:
            from coordination import lock as lock_mod
        except Exception as exc:              # 校验不了就不许跑（fail-closed）
            raise SystemExit("LOCK_CHECK_UNAVAILABLE 无法导入 coordination.lock（%s）⇒ 拒绝起 Blender"
                             % (exc,))
        checker = lock_mod.assert_owner
    try:
        return checker(owner, lock_dir=lock_dir) if lock_dir else checker(owner)
    except SystemExit:
        raise
    except Exception as exc:                  # NotOwner / IncompleteLock / ValueError
        raise _owner_refusal(exc)


def _owner_refusal(exc):
    # 只用 GBK 能编的字符：Windows 控制台默认 gbk，打印 `⇒` 会自己抛 UnicodeEncodeError，
    # 那就变成「为了报一个错而先崩一次」。
    msg = "NOT_OWNER %s -> 拒绝起 Blender（先 acquire，再跑）" % (exc,)
    print(msg)
    sys.stdout.flush()
    return SystemExit(3)


# --------------------------------------------------------------- 纯 Python 层
def plan(source_last_frame, *, frame_start=1, trim_end=None, hold_until=None):
    """源末帧 → 本步要做的操作 + 最终窗口。**不碰 bpy**，离屏可测。"""
    if not isinstance(source_last_frame, int) or source_last_frame < 0:
        raise PlanError("源末帧必须是非负整数，收到 %r" % (source_last_frame,))
    if not isinstance(frame_start, int) or frame_start < 1:
        raise PlanError("frame_start 必须 >= 1，收到 %r" % (frame_start,))
    if trim_end is not None and hold_until is not None:
        raise PlanError("--trim-end 与 --hold-until 互斥（一个截短、一个补长，同时给没有意义）")
    for name, val in (("trim_end", trim_end), ("hold_until", hold_until)):
        if val is not None and (not isinstance(val, int) or val < 1):
            raise PlanError("%s 必须是正整数，收到 %r" % (name, val))

    applied_first = frame_start
    # stage_motion 把 frame_current 复位到 1，import_vmd 再 +1 ⇒ 动作落点是 1..源末帧+1。
    # frame_start 只在「读回后设 scene.frame_start」时用，不改变动作落点。
    applied_last = source_last_frame + IMPORT_OFFSET

    ops, notes = [], []
    final_last = applied_last
    if trim_end is not None:
        if trim_end >= applied_last:
            raise PlanError(
                "源应用后到 %d 帧，--trim-end %d 截不到任何东西（要截短必须小于 %d）"
                % (applied_last, trim_end, applied_last))
        if trim_end < applied_first + 1:
            raise PlanError("--trim-end %d 会把动作截到 1 帧以内" % trim_end)
        ops.append({"op": "trim", "keep_until": trim_end, "dropped_frames": applied_last - trim_end})
        final_last = trim_end
        notes.append("源末帧 %d → 应用后 %d → 截到 %d（丢 %d 帧）"
                     % (source_last_frame, applied_last, trim_end, applied_last - trim_end))
    elif hold_until is not None:
        if hold_until <= applied_last:
            raise PlanError(
                "源应用后已到 %d 帧，--hold-until %d 补不出定格（必须大于 %d）"
                % (applied_last, hold_until, applied_last))
        ops.append({"op": "hold", "from": applied_last, "to": hold_until,
                    "frames": hold_until - applied_last})
        final_last = hold_until
        notes.append("源末帧 %d → 应用后 %d → %d..%d 保持末帧姿态（%d 帧定格，按预注册进 known_risks）"
                     % (source_last_frame, applied_last, applied_last, hold_until,
                        hold_until - applied_last))
    else:
        notes.append("源末帧 %d → 应用后 %d，不截不补" % (source_last_frame, applied_last))

    return {
        "source_last_frame": source_last_frame,
        "import_offset": IMPORT_OFFSET,
        "applied_first": applied_first,
        "applied_last": applied_last,
        "frame_start": frame_start,
        "final_first": frame_start,
        "final_last": final_last,
        "ops": ops,
        "notes": notes,
    }


def describe_source(vmd_path):
    """动作源的身份：路径 + sha256 + 帧跨度 + 骨数 + 键数。纯 Python。"""
    motion = vmd_mod.load(vmd_path)
    with open(vmd_path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    return {
        "path": os.path.abspath(vmd_path),
        "sha256": digest,
        "bytes": os.path.getsize(vmd_path),
        "frame_range": [int(motion.frame_range[0]), int(motion.frame_range[1])],
        "bones": len(motion.bone_tracks),
        "bone_frames": int(motion.keyframes),
    }


def check_record(rec):
    """对一条记录下判。**只吃 dict，不吃 bpy** —— 缺字段一律判红，不猜。

    喂一个应当被拒的 record 必须能红（`tests/test_apply_action.py` 里有反控）。
    """
    checks = []

    def add(cid, ok, detail):
        checks.append({"id": cid, "ok": bool(ok), "detail": detail})

    act = rec.get("action") or {}
    win = rec.get("window") or {}
    cache = rec.get("cache") or {}
    pl = rec.get("plan") or {}

    fcurves = act.get("fcurves")
    prof = (rec.get("profile") or {}).get("ensure_addons") or {}
    add("A0_profile_ready",
        prof.get("mmd_tools") is True,
        "ensure_addons=%r（`hasattr` 在没装上时也返回 True，只能信这个）" % (prof,))

    add("A1_action_applied",
        isinstance(fcurves, int) and fcurves > MIN_FCURVES,
        "action=%r fcurves=%r（门槛 > %d）" % (act.get("name"), fcurves, MIN_FCURVES))

    frange = act.get("frame_range") or [None, None]
    end_read = frange[1] if len(frange) > 1 else None
    add("A2_frame_end_readback",
        end_read is not None and win.get("frame_end") == end_read
        and str(win.get("frame_end_source", "")).startswith("readback"),
        "scene.frame_end=%r，action.frame_range[1]=%r，来源=%r"
        % (win.get("frame_end"), end_read, win.get("frame_end_source")))

    add("A3_is_baked_false",
        cache.get("has_rigidbody_world") is True and cache.get("is_baked") is False,
        "rigidbody_world=%r is_baked=%r is_outdated=%r freed_bake=%r"
        % (cache.get("has_rigidbody_world"), cache.get("is_baked"),
           cache.get("is_outdated"), cache.get("freed_bake")))

    add("A4_no_nla_stacking",
        act.get("nla_tracks") == 0,
        "nla_tracks=%r（单动作这一步不许留 NLA 轨道）" % (act.get("nla_tracks"),))

    add("A5_window_matches_plan",
        win.get("frame_end") is not None and win.get("frame_end") == pl.get("final_last"),
        "scene.frame_end=%r，plan.final_last=%r"
        % (win.get("frame_end"), pl.get("final_last")))

    # 物理步长 dt = 1/fps ⇒ fps 被导入动作改掉，等于把 `C vs B` 变成跨 dt 比较（D-104）。
    # 这一条是新加的**红**判据，不是 warn：预设里的 fps 是仓库写死的场景身份。
    preset_fps = (rec.get("profile") or {}).get("preset_fps")
    scene_fps = (rec.get("scene") or {}).get("fps_after")
    add("A6_fps_matches_preset",
        preset_fps is not None and scene_fps == preset_fps,
        "scene.fps_after=%r，preset=%r%s"
        % (scene_fps, preset_fps,
           "" if preset_fps is None else ("（导入动作改了容器 fps）" if scene_fps != preset_fps else "")))

    return {"checks": checks, "verdict": "READY" if all(c["ok"] for c in checks) else "BLOCKED"}


def _new_record(source, pl, *, arm_name, scene, extra=None):
    rec = {
        "schema": "m05.apply_action/1",
        "source": source,
        "plan": pl,
        "arm": arm_name,
        "scene": scene,
        "action": {},
        "window": {},
        "cache": {},
    }
    if extra:
        rec.update(extra)
    return rec


# --------------------------------------------------------------- Blender 层
def _clear_previous(arm):
    """幂等第一步：把上一次留下的 action / NLA 轨道清干净。

    不清就重跑 = 同一骨架上两个动作叠加，第二次的读数和第一次不是一件事。
    """
    import bpy
    removed = {"action": False, "nla_tracks": 0, "orphan_actions": 0}
    ad = arm.animation_data
    if ad is not None:
        removed["action"] = ad.action is not None
        for track in list(ad.nla_tracks):
            ad.nla_tracks.remove(track)
            removed["nla_tracks"] += 1
        ad.action = None
    for action in list(bpy.data.actions):
        if action.users == 0:
            bpy.data.actions.remove(action)
            removed["orphan_actions"] += 1
    return removed


def _channelbags_of(action):
    """分层动作里的 `channelbag` 列表（`layers[].strips[].channelbags[]`）。

    读侧（`fcurves_of`）与写侧（`fcurve_container`）**共用这一处遍历**：层级一变只改这里。
    今天已经为「同一形状两份实现」付过三次代价（`mask_wired` 手抄 11 键 vs 清单 18 键、
    两份锁逻辑、`use_disk_cache` 差点被「好心打开」）——`4号` 在 `b300c5c` 之后复审时点的。
    """
    out = []
    for layer in getattr(action, "layers", []) or []:
        for strip in getattr(layer, "strips", []) or []:
            for bag in getattr(strip, "channelbags", None) or []:
                out.append(bag)
    return out


def fcurves_of(action):
    """取一个 `Action` 的全部 fcurve —— **Blender 4.4+ 的分层/槽位动作没有 `.fcurves`**。

    为什么要有这层：`Action.fcurves` 只在「本会话里刚由导入器造出来的动作」上可读；
    一旦动作随 `.blend` 存盘再读回来（分层动作 + 槽位），这个属性直接 `AttributeError`。
    于是「可重复运行」这件事在真件上从来没有人验过 —— 2026-11-16 我在 324 批次的
    产物回读里撞上（`C@W1.blend` 的 `B_aligned_bone` 只有 `layers/strips/channelbags`）。
    返回 `(fcurves 列表, 走的是哪条路)`，`how` 进记录，别让下一个人猜读数从哪来。
    """
    try:
        return list(action.fcurves), "action.fcurves"
    except AttributeError:
        pass
    except TypeError:                       # 某些版本给 None，同样按「没有」处理
        pass
    return [fc for bag in _channelbags_of(action) for fc in bag.fcurves], \
        "layers.strips.channelbags"


class FcurveShapeError(RuntimeError):
    """写侧找不到**唯一**可写的曲线容器。

    读可以全部拼成一个列表，写不行：写要 `find()/new()` 这对方法，得先挑定
    哪一个容器。挑不准的时候宁可红，也不许随手挑一个 —— 那是往别人的动作上改键。
    """


def fcurve_container(action, datablock=None):
    """取一个**可写**的 fcurve 容器（有 `.find/.new`），`fcurves_of` 的写侧。

    顺序照 `AGENTS.md` 第一条「先找现成的」，也就是从最省事到最手工：
      1. `action.fcurves` —— 同会话刚由导入器造出来的动作；`chain_nla` 今天走的就是这条
      2. 分层动作里「槽位正好是 `datablock` 现在用的那个」channelbag
      3. 分层动作里只有一个 channelbag 时，就是它
      4. 多个又对不上槽位 ⇒ 抛 `FcurveShapeError`（不猜）
    返回 `(容器, how)`；`how` 进记录，别让下一个人猜曲线写去了哪里。
    """
    try:
        legacy = action.fcurves
    except (AttributeError, TypeError):
        legacy = None
    if legacy is not None:
        return legacy, "action.fcurves"
    bags = _channelbags_of(action)
    if not bags:
        raise FcurveShapeError(
            "动作 %r 既没有 .fcurves 也没有 channelbags：没有可写的地方"
            % getattr(action, "name", "?"))
    slot = None
    if datablock is not None:
        slot = getattr(getattr(datablock, "animation_data", None), "action_slot", None)
    if slot is not None:
        hit = [b for b in bags if getattr(b, "slot", None) is slot]
        if len(hit) == 1:
            return hit[0].fcurves, "channelbags[slot]"
    if len(bags) == 1:
        return bags[0].fcurves, "channelbags[0]"
    raise FcurveShapeError(
        "分层动作 %r 有 %d 个 channelbag 且槽位对不上，不敢挑一个"
        % (getattr(action, "name", "?"), len(bags)))


def ensure_fcurve(action, datablock, path, index=0, group=""):
    """拿到（必要时新建）某条曲线，返回 `(fcurve, how)`。

    分层动作上写曲线，Blender 5.2 有上游接口 `Action.fcurve_ensure_for_datablock`。
    **它不是假设了，是量过的**（2026-11-16 只读探针，臂件 `C@W1.blend`，文件 sha 不变）：

        exists_on_class    = false      ← `hasattr(bpy.types.Action, ...)` 会说不存在
        exists_on_instance = true       ← 所以只能 `getattr(action, ...)`
        __doc__            = "Action.fcurve_ensure_for_datablock(datablock, data_path,
                              index=0, group_name=\"\") ... This action must already be
                              assigned to the data-block. ..."
        真调（对一份没挂到 ID 上的 `action.copy()`）= RuntimeError

    所以顺序是：老形状 → 上游接口（**前置条件成立**才用）→ 自己走 channelbag。
    前置条件不成立时不调用、只记 `upstream_skipped:<原因>` —— 拿异常当流程控制会让
    每次正常拼接都背一条假故障，读记录的人分不清「真出事」和「本来就走这条」。
    `how` 里会写清走了哪条，不藏。
    """
    try:
        legacy = action.fcurves
    except (AttributeError, TypeError):
        legacy = None
    if legacy is not None:
        fc = legacy.find(path, index=index)
        if fc is None:
            fc = legacy.new(path, index=index, action_group=group)
        return fc, "action.fcurves"
    upstream = getattr(action, "fcurve_ensure_for_datablock", None)
    note = ""
    # 上游接口有**前置条件**（2026-11-16 真机量到，见 M05 报告 §十三）：
    # 文档原话 "This action must already be assigned to the data-block"，
    # 拿一份没挂到 ID 上的动作（NLA 条带上的动作就是这种）去调直接 RuntimeError。
    # 所以先判前置条件，别靠异常当流程控制 —— 那条路每次都会在记录里留一条假故障。
    assigned = datablock is not None and \
        getattr(getattr(datablock, "animation_data", None), "action", None) is action
    if callable(upstream):
        if not assigned:
            note = "; upstream_skipped:" + (
                "no_datablock" if datablock is None else "action_not_assigned")
        else:
            try:
                fc = upstream(datablock, path, index=index, group_name=group)
                if fc is not None:
                    return fc, "fcurve_ensure_for_datablock"
                note = "; upstream_returned_None"
            except Exception as exc:        # noqa: BLE001 —— 前置条件之外还会因为别的抛，抛了就退
                note = "; upstream_raised:" + type(exc).__name__
    cont, how = fcurve_container(action, datablock)
    fc = cont.find(path, index=index)
    if fc is None:
        fc = cont.new(path, index=index, action_group=group)
        how += "(new)"
    else:
        how += "(find)"
    return fc, how + note


def _trim_action(action, keep_until):
    """丢掉 keep_until 之后的关键帧；返回被丢掉的帧数（按曲线逐个算）。"""
    dropped = 0
    for fcu in fcurves_of(action)[0]:
        pts = fcu.keyframe_points
        for i in range(len(pts) - 1, -1, -1):
            if pts[i].co[0] > keep_until:
                pts.remove(pts[i])
                dropped += 1
        fcu.update()
    return dropped


def _hold_action(action, hold_until):
    """给每条曲线在 hold_until 补一个「末帧姿态」的键 —— 值相同，插值自然是常值。"""
    added = 0
    for fcu in fcurves_of(action)[0]:
        pts = fcu.keyframe_points
        if len(pts) == 0:
            continue
        last = pts[len(pts) - 1]
        if last.co[0] >= hold_until:
            continue
        fcu.keyframe_points.insert(hold_until, last.co[1], options={"FAST"})
        fcu.update()
        added += 1
    return added


def _free_bake(rbw):
    """把已有的烘焙清掉：交付件要 fresh_solve，`is_baked` 只读，只能走算子。"""
    import bpy
    info = {"attempted": False, "ok": False, "error": None}
    try:
        info["attempted"] = True
        bpy.ops.ptcache.free_bake_all()
        info["ok"] = True
    except Exception as exc:                       # 算子上下文不对就如实记下来
        info["error"] = "%s: %s" % (type(exc).__name__, exc)
    return info


def apply_action(preset, root, arm, vmd_path, *, frame_start=1, trim_end=None,
                 hold_until=None, frame_end_hint=None, ensure=True,
                 keep_scene_settings=True, verbose=True):
    """在一个已建好物理的场景里应用一条动作，回读读数并下判。

    **本函数不校验锁**：`owner` 校验在 CLI 入口（`--owner` + `assert_lock_owner`），
    库函数可能被离屏调用，强制它只会逼所有人编一个假身份。调用方须先 assert-owner。

    复用 `stage.stage_motion`（不复制第二份导入实现）。返回 `(record, ok)`。
    """
    import bpy
    try:                       # 作为包的一部分
        from . import stage as stage_mod
    except ImportError:        # 作为独立脚本跑（blender -b -P mmdpipe/apply_action.py）
        from mmdpipe import stage as stage_mod

    source = describe_source(vmd_path)                      # 先校验，后动场景
    pl = plan(source["frame_range"][1], frame_start=frame_start,
              trim_end=trim_end, hold_until=hold_until)
    scene = bpy.context.scene
    hint = frame_end_hint if frame_end_hint is not None else pl["final_last"]

    removed = _clear_previous(arm)
    scene.frame_current = 1                                  # stage_motion 里也会复位，这里先摆正
    fps_before = scene.render.fps

    # **不让输入改环境**：`import_vmd(update_scene_settings=True)` 会按 VMD 的 30fps 基准
    # 把场景 fps 改成 30。Blender 刚体步长 dt = 1/fps ⇒ 改 fps 就是改物理，
    # 而 `C vs B` 的 A/B 组在老场景（24 fps）上 ⇒ 会变成跨 dt 比较（D-104）。
    # preset 里的 fps 是仓库写死的场景身份，所以这里强制关掉，并让 A6 判它有没有被改。
    preset = copy.deepcopy(preset)
    forced = False
    if keep_scene_settings:
        motion_cfg = preset.setdefault("motion", {})
        if motion_cfg.get("update_scene_settings"):
            motion_cfg["update_scene_settings"] = False
            forced = True
    preset_fps = (preset.get("render") or {}).get("fps")

    # 插件先就位再导入：`-b <blend> -P 脚本` 是新进程，blend 里存的是数据不是已启用的插件。
    # 不先 ensure，`stage_motion` 只会拿到一句 `import_vmd ... could not be found`（E-14）。
    # `ensure=False` 只给反控用（证明这条闸门真的是它挡住的），正常调用不许关。
    addons = stage_mod.ensure_addons(("mmd_tools",)) if ensure else {"mmd_tools": None}

    st, action_end = stage_mod.stage_motion(preset, root, arm, vmd_path, hint)
    from dataclasses import asdict
    issues = [asdict(i) for i in (getattr(st, "issues", None) or [])]
    rec = _new_record(source, pl, arm_name=arm.name,
                      scene={"name": scene.name, "fps_before": fps_before},
                      extra={"profile": {"ensure_addons": addons,
                                         "preset_fps": preset_fps,
                                         "update_scene_settings_forced_off": forced},
                             "stage_motion": {"ok": getattr(st, "ok", None),
                                              "metrics": dict(getattr(st, "metrics", {}) or {}),
                                              "issues": issues},
                             "cleared": removed, "applied": {}})

    action = arm.animation_data.action if arm.animation_data else None
    if action is None:
        rec["action"] = {"name": None, "fcurves": 0, "frame_range": [None, None], "nla_tracks": 0}
        rec["window"] = {"frame_start": scene.frame_start, "frame_end": scene.frame_end,
                         "frame_end_source": "not-applied"}
        rec["cache"] = {"has_rigidbody_world": bpy.context.scene.rigidbody_world is not None,
                        "is_baked": None, "freed_bake": False}
        out = check_record(rec)
        rec.update(out)
        return rec, False

    pre_op_end = int(round(action.frame_range[1]))       # 动手前的回读值，留给「预注册口径 vs 实测」两列
    dropped = added = 0
    op_log = []
    for op in pl["ops"]:
        if op["op"] == "trim":
            n = _trim_action(action, op["keep_until"])
            dropped += n
            op_log.append({"op": "trim", "keep_until": op["keep_until"],
                           "dropped_keys_readback": n, "end_before": pre_op_end,
                           "end_after": int(round(action.frame_range[1]))})
        elif op["op"] == "hold":
            n = _hold_action(action, op["to"])
            added += n
            op_log.append({"op": "hold", "to": op["to"],
                           "from_readback": pre_op_end,          # 实测起点（预注册口径见 plan.notes）
                           "from_expected_by_offset": op["from"],
                           "held_fcurves": n,
                           "end_after": int(round(action.frame_range[1]))})
    rec["applied"] = {"trimmed_keys": dropped, "held_keys": added,
                      "stage_motion_action_end": action_end,
                      "end_before_ops_readback": pre_op_end, "ops": op_log}

    end_read = int(round(action.frame_range[1]))
    start_read = int(round(action.frame_range[0]))
    scene.frame_start = frame_start
    scene.frame_end = end_read                              # 回读值，不是预期值

    rbw = bpy.context.scene.rigidbody_world
    cache = {"has_rigidbody_world": rbw is not None, "is_baked": None,
             "is_outdated": None, "freed_bake": False, "bake_free": None,
             "point_cache_range": None}
    if rbw is not None:
        pc = rbw.point_cache
        cache["is_baked"] = bool(pc.is_baked)
        # `is_outdated` **无条件读**：上一版只在 is_baked 时才读，于是 D 臂留了个 null，
        # 让人去猜「是没值还是没读」——沉默的缺就是缺。
        cache["is_outdated"] = bool(pc.is_outdated)
        if pc.is_baked:                                     # 应用完必须是可 fresh_solve 的
            info = _free_bake(rbw)
            cache["bake_free"] = info
            cache["freed_bake"] = bool(info["ok"])
            cache["is_baked"] = bool(pc.is_baked)
            cache["is_outdated"] = bool(pc.is_outdated)
        pc.frame_start = 1
        pc.frame_end = max(end_read, start_read)
        cache["point_cache_range"] = [int(pc.frame_start), int(pc.frame_end)]

    fcurves, fcurves_how = fcurves_of(action)
    rec["action"] = {"name": action.name, "fcurves": len(fcurves),
                     "fcurves_via": fcurves_how,
                     "frame_range": [start_read, end_read],
                     "nla_tracks": len(arm.animation_data.nla_tracks) if arm.animation_data else 0,
                     "action_users": action.users}
    rec["window"] = {"frame_start": int(scene.frame_start), "frame_end": int(scene.frame_end),
                     "frame_end_source": "readback:arm.animation_data.action.frame_range[1]"}
    # `import_vmd(update_scene_settings=True)` 会自己改 fps —— 改了就改，但要看得见。
    # （实测：交付件 24 fps，导入 VMD 后被设成 30，因为 VMD 以 30fps 为基准。
    #   `stage_motion` 的 E-00 用的是**预设里的** fps，所以它那句 warn 与实际读回值不是一回事。）
    rec["scene"]["fps_after"] = scene.render.fps
    rec["scene"]["fps_changed"] = scene.render.fps != fps_before
    rec["cache"] = cache
    out = check_record(rec)
    rec.update(out)
    if verbose:
        print("  APPLY %s fcurves=%d(%s) range=%s frame_end=%d is_baked=%s → %s"
              % (action.name, len(fcurves), fcurves_how, rec["action"]["frame_range"],
                 scene.frame_end, cache["is_baked"], rec["verdict"]))
    return rec, out["verdict"] == "READY"


# --------------------------------------------------------------- CLI
def _find_arm(name=None):
    import bpy
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if name:
        hit = [o for o in arms if o.name == name]
        if not hit:
            raise SystemExit("找不到骨架 %r（场景里有：%s）" % (name, [o.name for o in arms]))
        return hit[0]
    if len(arms) != 1:
        raise SystemExit("场景里有 %d 个骨架，必须用 --arm 指定：%s"
                         % (len(arms), [o.name for o in arms]))
    return arms[0]


def _find_root(arm):
    import bpy
    cur = arm
    while cur.parent is not None:
        cur = cur.parent
        if getattr(cur, "mmd_type", None):
            return cur
    return cur


def main(argv=None):
    argv = argv if argv is not None else (sys.argv[sys.argv.index("--") + 1:]
                                          if "--" in sys.argv else sys.argv[1:])
    ap = argparse.ArgumentParser(prog="mmdpipe.apply_action",
                                 description="交付链·应用动作（幂等、回读 frame_end 与 is_baked）")
    ap.add_argument("--vmd", required=True, help="动作源 VMD")
    ap.add_argument("--preset", required=True, help="预设 JSON（stage_motion 要 motion/render 段）")
    ap.add_argument("--out-blend", required=False, default=None,
                    help="写出路径；给了 --out-dir 时忽略此项（走版本化路径）")
    ap.add_argument("--out-dir", default=None,
                    help="版本化落盘根目录：产物写到 <out-dir>/<batch-id>/<arm-role>.blend")
    ap.add_argument("--batch-id", default=None, help="批次号（配 --out-dir 用；不覆盖同名旧件）")
    ap.add_argument("--allow-overwrite", action="store_true",
                    help="**只给反控用**：允许覆盖已存在的臂件（默认拒绝）")
    ap.add_argument("--freeze", action="store_true",
                    help="写出后把臂件设成只读（已交付的臂件应当冻结）")
    ap.add_argument("--json", required=True)
    ap.add_argument("--arm", default=None)
    ap.add_argument("--frame-start", type=int, default=1)
    ap.add_argument("--trim-end", type=int, default=None)
    ap.add_argument("--hold-until", type=int, default=None)
    ap.add_argument("--frame-end-hint", type=int, default=None,
                    help="给 stage_motion 的 frame_end_hint（只影响物理缓存覆盖范围）")
    ap.add_argument("--note", action="append", default=[],
                    help="写进记录的附注（例如「尾帧未测」「对照行不进判词」），可重复")
    ap.add_argument("--arm-role", default=None,
                    help="本臂标签（C@W1 / C@W2 / D / 对照），只做记录用")
    ap.add_argument("--owner", default=None,
                    help="`模块|工作树`；**不给就不许起**：第一步校验这把锁是不是自己的（D-188）")
    ap.add_argument("--skip-ensure", action="store_true",
                    help="**只给反控用**：跳过插件闸门，用来证明「判红真的是这条闸门挡的」")
    ap.add_argument("--allow-scene-settings", action="store_true",
                    help="**只给反控用**：允许 import_vmd 改场景 fps（A6 会因此判红）")
    args = ap.parse_args(argv)

    # 第一句：这把锁不是我的就一个字节都不动（D-188）。放在 import bpy 之前。
    lock_start = assert_lock_owner(args.owner)

    # 版本化落盘（D-189）：臂件是物证，默认**不覆盖**已有文件。
    if args.out_dir:
        out_blend = versioned_out_path(args.out_dir, args.batch_id, args.arm_role or "arm")
    else:
        out_blend = args.out_blend
    if not out_blend:
        raise SystemExit("用法错误：--out-blend 与（--out-dir + --batch-id）二者必给其一")
    if os.path.exists(out_blend) and not args.allow_overwrite:
        print("REFUSED 已存在同名臂件（%s）：臂件是那次读数的物证，重跑请换 --batch-id"
              % out_blend)
        sys.stdout.flush()
        return 3

    import bpy
    try:                       # 作为包的一部分
        from . import preset as preset_mod
    except ImportError:        # 作为独立脚本跑
        from mmdpipe import preset as preset_mod
    from coordination import lock as lock_mod

    preset = preset_mod.load(args.preset)
    arm = _find_arm(args.arm)
    root = _find_root(arm)
    rec, ok = apply_action(preset, root, arm, args.vmd, frame_start=args.frame_start,
                           trim_end=args.trim_end, hold_until=args.hold_until,
                           frame_end_hint=args.frame_end_hint,
                           ensure=not args.skip_ensure,
                           keep_scene_settings=not args.allow_scene_settings)
    rec["arm_role"] = args.arm_role
    rec["notes"] = list(args.note)
    rec["profile"]["lock_start"] = lock_start          # 开局：ident + heartbeat_age 两个值
    src_blend = bpy.data.filepath            # ← 本进程打开的那份场景（不是我要写出的那份）
    if src_blend and os.path.exists(src_blend):
        with open(src_blend, "rb") as fh:
            rec["in_blend"] = {"path": os.path.abspath(src_blend),
                               "bytes": os.path.getsize(src_blend),
                               "sha256": hashlib.sha256(fh.read()).hexdigest()}

    def _dump(tag, code):
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            # default=str：压不动的值（Vector/IDProperty 之类）落成字符串**留在记录里**，
            # 不静默丢 —— 看不见就当红，这条与 `mask_wired_checks` 同脾气。
            json.dump(rec, fh, ensure_ascii=False, indent=1, sort_keys=True, default=str)
            fh.write("\n")
        print("%s verdict=%s json=%s" % (tag, rec["verdict"], args.json))
        sys.stdout.flush()
        return code

    # 判红就**不写交付件**：一个注定不合格的 .blend 留在盘上，下一个人会当成已有交付。
    if not ok:
        rec["out_blend"] = None
        return _dump("REFUSED", 3)

    # 落盘**之前**再确认一次锁还是自己的（尾部闸第一步）：中途掉了就不落盘，
    # 宁可少一份读数，不要一份「来源锁存疑」的读数。
    lock_mod.touch(args.owner)                          # 长阶段之间刷心跳
    try:
        rec["profile"]["lock_before_save"] = lock_mod.assert_owner(args.owner)
    except Exception as exc:
        rec["verdict"] = "BLOCKED"
        rec["out_blend"] = None
        rec["known_risks"] = ["锁在保存前易主（%s）⇒ 不落盘" % (exc,)]
        return _dump("REFUSED", 3)

    os.makedirs(os.path.dirname(os.path.abspath(out_blend)) or ".", exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(out_blend))
    with open(out_blend, "rb") as fh:
        rec["out_blend"] = {"path": os.path.abspath(out_blend),
                            "batch_id": args.batch_id,
                            "bytes": os.path.getsize(out_blend),
                            "sha256": hashlib.sha256(fh.read()).hexdigest()}

    # 收尾再确认一次，并比对两处 ident（尾部闸第二步）：不同即该臂作废，产物删掉。
    try:
        lock_end = lock_mod.assert_owner(args.owner)
    except Exception as exc:
        lock_end = {"ident": None, "error": str(exc)}
    rec["profile"]["lock_end"] = lock_end
    tail_ok, tail_msg = lock_tail_verdict(lock_start, lock_end)
    rec["profile"]["lock_tail"] = {"ok": tail_ok, "detail": tail_msg}
    if not tail_ok:
        try:
            os.chmod(out_blend, 0o666)
            os.remove(os.path.abspath(out_blend))
        except OSError:
            pass
        rec["out_blend"] = None
        rec["verdict"] = "NOT_APPLICABLE"
        rec.setdefault("known_risks", []).append(tail_msg)
        return _dump("VOID", 3)

    if args.freeze:
        rec["out_blend"]["frozen_mode"] = freeze_file(out_blend)

    return _dump("DONE", 0 if ok else 3)


if __name__ == "__main__":
    _rc = main()
    sys.stdout.flush()
    os._exit(_rc)          # Blender 的事件循环会吞掉正常退出，这里给硬码
