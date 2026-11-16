"""刚体 point cache 一致性判据（纯 Python，不 import bpy）。

## 为什么需要它

交付的 `.blend` 可能带着**已烘焙但标记为过期**的缓存（`point_cache.is_baked = True` 且
`is_outdated = True`）。这种工程打开就能播放，但：

- **默认消费路径**（打开 + `frame_set`）= 回放缓存；
- **任何触发重算的路径**（解烘焙、改物理参数、重新导入）= 另一条轨迹。

M02 在 `B_from_blend1.blend` 上实测过：两条轨迹差**下摆骨 0.9087 m / 全刚体 1.5867 m**，
且单帧跳转与逐帧步进给出逐位相同的数字（回放指纹）。同一个文件两种动画 ⇒ 动画不可复现。

## 关键：**标志位只是筛选信号，结论必须由行为探针给**

`is_baked && is_outdated` 的真实含义是「**打开时无法证明缓存与当前设置一致**」，**不是**
「缓存坏了」。两次实测（P13，2026-11-16）：

| 文件 | 标志位 | 冷跳 vs 顺序重算 | 实际 |
|---|---|---|---|
| `J_baked.blend`（本次真烘焙） | `true && true` | **0.000000 m**（逐位，f109/f240 都对） | **健康** |
| `B_from_blend1.blend`（Nov-7 交付） | `true && true` | **0.9087 m**（== 回放指纹） | **缺陷** |

**同样两个布尔，一个健康一个有缺陷。**所以判定分成两级：

1. 标志位不合（`is_baked && is_outdated`）→ 只能判**「未验证」**，不是不合格；
2. 要通过，必须给**行为证据**（`behavior`：冷跳某中间帧的坐标 vs 顺序重算同一帧的距离）。

## 七个判定词

| 条件 | 判定 | 退出码 |
|---|---|---|
| 无 `rigidbody_world` | `OK_NO_PHYSICS` | 0 |
| `is_baked=False` | `OK_UNBAKED`（首次 `frame_set` 会重算；**消费方必须从 `scene.frame_start` 顺序求值**） | 0 |
| `is_baked=True, is_outdated=False` | `OK_BAKED_CONSISTENT` | 0 |
| `is_baked=True, is_outdated=True` + 行为证据一致 | `OK_BAKED_VERIFIED` | 0 |
| 同上 + 行为证据不一致 | `DEFECT_BAKED_OUTDATED` | 3 |
| 同上 + **没有**行为证据 | `SUSPECT_BAKED_OUTDATED`（**未测 ≠ 不合格**，但不许静默放行） | 4 |
| 读不到 / 字段缺失 / 行为记录格式不对 | `UNREADABLE`（fail closed，不猜） | 4 |

行为证据的形态（`behavior` 字段，可选）：

    {"cold_jump_frame": 109, "cold_jump_vs_recompute_m": 0.0, "tolerance_m": 0.001}

`tolerance_m` 缺省 `1e-6`（逐位相等是这条判据的常态，见 P13）。行为证据**优先于标志位**：
标志位说一致而行为证据说不一致，按**不一致**判（量到的比声明可信）。

## 用法

判据本身不碰 bpy：调用方（Blender 侧探针、`stage.py`、CI）把观测值喂进来。

    from mmdpipe import cache_state
    rec = cache_state.evaluate({"exists": True, "has_physics": True,
                                "is_baked": True, "is_outdated": True})
    rec["verdict"], rec["exit_code"]        # 'SUSPECT_BAKED_OUTDATED', 4 —— 未验证

批量与 CLI（便于把探针输出直接判）：

    python -m mmdpipe.cache_state records.json    # 退出码 = 最坏的一条

## 别信 `point_cache.info`

`info` 是**存进 `.blend` 的字符串**，帧数据不在里面。P12 实测：一份「解烘焙 → 顺序步进 1→240
→ 存盘」的工程，重开后 `info` 仍写着 `240 frames in memory (2.1 MiB).`，而 `is_outdated` 已经
翻回 `True`——数据没了。**`info` 当线索不当证据。**
"""
from __future__ import annotations

import json
import sys

OK = 0
DEFECT = 3
UNREADABLE = 4

OK_UNBAKED = "OK_UNBAKED"
OK_BAKED_CONSISTENT = "OK_BAKED_CONSISTENT"
OK_BAKED_VERIFIED = "OK_BAKED_VERIFIED"
OK_NO_PHYSICS = "OK_NO_PHYSICS"
DEFECT_BAKED_OUTDATED = "DEFECT_BAKED_OUTDATED"
SUSPECT_BAKED_OUTDATED = "SUSPECT_BAKED_OUTDATED"
UNREADABLE_VERDICT = "UNREADABLE"

VERDICTS = (OK_UNBAKED, OK_BAKED_CONSISTENT, OK_BAKED_VERIFIED, OK_NO_PHYSICS,
            DEFECT_BAKED_OUTDATED, SUSPECT_BAKED_OUTDATED, UNREADABLE_VERDICT)

#: 默认容差：这条判据上「冷跳 == 顺序重算」是常态（P13 两次都是逐位 0）。
DEFAULT_TOLERANCE_M = 1e-6

_EXIT = {
    OK_UNBAKED: OK,
    OK_BAKED_CONSISTENT: OK,
    OK_BAKED_VERIFIED: OK,
    OK_NO_PHYSICS: OK,
    DEFECT_BAKED_OUTDATED: DEFECT,
    SUSPECT_BAKED_OUTDATED: UNREADABLE,
    UNREADABLE_VERDICT: UNREADABLE,
}

DEFECT_REASON = (
    "行为探针测到「冷跳中间帧」与「顺序重算同一帧」不是同一条动画（> tolerance）；"
    "该工程回放与重算分叉。修法二选一：重烘焙并保存（`bpy.ops.ptcache.bake_all()`，"
    "P13 实测 exit 0 / 32.2 s / 冷跳逐位等于重算，需 10 §6 逐场景豁免），"
    "或解烘焙交付并要求消费方从 `scene.frame_start` 顺序求值。"
)

SUSPECT_REASON = (
    "产物 is_baked=true 且 is_outdated=true：**打开时无法证明缓存与当前设置一致**。"
    "这不是缺陷的证据——真烘焙件重开后也是这两个值（P13 `J_baked.blend` 冷跳逐位等于重算）。"
    "要定性必须补行为探针：冷跳一个中间帧，与从 frame_start 顺序重算的同一帧比距离。"
)


class CacheStateError(ValueError):
    """观测记录不可解释（缺字段、类型不对）——不猜，按 UNREADABLE 处理。"""


def parse_behavior(behavior) -> dict | None:
    """校验行为证据。`None` 表示「没测」；给了但格式不对就抛（fail closed）。"""
    if behavior is None:
        return None
    if not isinstance(behavior, dict):
        raise CacheStateError("behavior 必须是 dict 或省略")
    frame = behavior.get("cold_jump_frame")
    dist = behavior.get("cold_jump_vs_recompute_m")
    tol = behavior.get("tolerance_m", DEFAULT_TOLERANCE_M)
    if not isinstance(frame, int) or isinstance(frame, bool):
        raise CacheStateError("behavior.cold_jump_frame 必须是 int")
    for key, value in (("cold_jump_vs_recompute_m", dist), ("tolerance_m", tol)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CacheStateError("behavior.%s 必须是数" % key)
        if value < 0:
            raise CacheStateError("behavior.%s 不能为负" % key)
    return {"cold_jump_frame": frame, "cold_jump_vs_recompute_m": float(dist),
            "tolerance_m": float(tol),
            "within_tolerance": float(dist) <= float(tol)}


def classify(*, has_physics: bool, is_baked: bool | None, is_outdated: bool | None,
             behavior: dict | None = None) -> str:
    """按状态给出判定词。标志位不合时**只判未验证**，定性要 `behavior`。"""
    if not isinstance(has_physics, bool):
        raise CacheStateError("has_physics 必须是 bool")
    if not has_physics:
        return OK_NO_PHYSICS
    if not isinstance(is_baked, bool):
        raise CacheStateError("有 rigidbody_world 时必须给 is_baked(bool)")
    if not is_baked:
        return OK_UNBAKED
    if not isinstance(is_outdated, bool):
        raise CacheStateError("is_baked=True 时必须给 is_outdated(bool)")
    parsed = parse_behavior(behavior)
    if parsed is not None:
        # 行为证据优先于标志位：量到的比声明的可信。
        return OK_BAKED_VERIFIED if parsed["within_tolerance"] else DEFECT_BAKED_OUTDATED
    return OK_BAKED_CONSISTENT if not is_outdated else SUSPECT_BAKED_OUTDATED


PLAN_NONE = "none"
PLAN_SEQUENTIAL_DELIVERY = "sequential_delivery"
PLAN_PROBE_BEHAVIOR = "probe_behavior"
PLAN_REBAKE = "rebake"
PLAN_INSPECT = "inspect"
PLAN_ACTIONS = (PLAN_NONE, PLAN_SEQUENTIAL_DELIVERY, PLAN_PROBE_BEHAVIOR, PLAN_REBAKE,
                PLAN_INSPECT)

#: 被实测证伪、**不得**作为 `plan()` 输出的修法。留在这里是为了不再走第二遍。
REJECTED_ACTIONS = {
    "rebake_by_stepping":
        "解烘焙后从 frame_start 顺序步进到 frame_end 再存盘（P12，2026-11-16）：内存 point cache "
        "不写进 .blend，重开后 is_outdated 由 false 翻回 true，冷跳仍是第三条轨迹（对 P0[109] "
        "D_max 1.922861 m，与只解烘焙不步进的 H_nobake 完全相同）。只有 .blend 里的 info 字符串落盘。",
    "unbake":
        "旧名，语义不清：它其实是**降级交付**（清理缓存 + 遍历契约），不是「修好」。已改名 "
        "sequential_delivery。",
}

_SEQUENTIAL_NOTE = (
    "降级交付：产物不烘焙（is_baked=false），消费方**必须从 scene.frame_start 顺序求值**"
    "才能拿到与重算一致的那条动画；跳到中间帧再渲染会得到第三条轨迹（P11/P12 实测）。"
    "对「只渲染中段」「并行抽帧」构成限制。"
)

_PROBE_NOTE = (
    "未验证：`is_baked=true && is_outdated=true` 只说明「打开时无法证明缓存与当前设置一致」，"
    "真烘焙件重开后也是这两个值（P13 `J_baked.blend` 冷跳逐位等于重算，`B_from_blend1.blend` "
    "冷跳等于旧回放、差 0.9087 m）。先冷跳一个中间帧并与从 frame_start 顺序重算的同一帧比距离，"
    "把结果填进 `behavior` 再判一次（工具：`m02_s8_p13.py -- probe` + `m02_frame_cmp.py`）。"
)

_REBAKE_NOTE = (
    "已测到分叉。重烘焙：`bpy.ops.ptcache.bake_all(bake=True)`——P13 实测 exit 0、32.2 s、"
    "326 帧、不要求磁盘缓存（`use_disk_cache=false` 成功）、冷跳 f109/f240 与整段 240 帧均与重算"
    "逐位相同。**10 §6 的 bake_all 禁令有常驻豁免，四条条件**：只在副本上、每场景单次、"
    "崩溃只记退出码不重试、成功也必须过行为探针才算数。"
)


def plan(record: dict) -> dict:
    """判据 → 下一步动作。只给动作名，不执行（执行需要 bpy，见 `rebake_fix.md`）。

    - `OK_*`       → `{"action": "none"}`
    - `SUSPECT_*`  → `{"action": "probe_behavior"}`：**先测再判**。标志位不合只是「未验证」。
    - `DEFECT_*`   → `{"action": "rebake"}`：行为探针已测到分叉，重烘焙（需 §6 逐场景豁免）。
    - `UNREADABLE` → `{"action": "inspect"}`：先能读到缓存状态再谈修法。

    `sequential_delivery`（解烘焙 + 遍历契约）仍是可选的低成本降级路，但它**不是**由判据自动
    给出的动作：它是交付形态的选择，由 A/B 契约决定。「跑一遍再存盘」（`rebake_by_stepping`）
    已被 P12 证伪，见 `REJECTED_ACTIONS`。
    """
    judged = evaluate(record)
    action = {"OK_UNBAKED": PLAN_NONE, "OK_BAKED_CONSISTENT": PLAN_NONE,
              "OK_BAKED_VERIFIED": PLAN_NONE, "OK_NO_PHYSICS": PLAN_NONE,
              SUSPECT_BAKED_OUTDATED: PLAN_PROBE_BEHAVIOR,
              DEFECT_BAKED_OUTDATED: PLAN_REBAKE,
              UNREADABLE_VERDICT: PLAN_INSPECT}[judged["verdict"]]
    note = {PLAN_PROBE_BEHAVIOR: _PROBE_NOTE, PLAN_REBAKE: _REBAKE_NOTE}.get(action, "")
    return {**judged, "action": action, "note": note}


#: sidecar 随产物一起交付的字段（交付契约 B：消费者要能自己看出这是哪一类）。
SIDECAR_KEYS = ("is_baked", "is_outdated", "info", "bodies", "use_disk_cache")


def sidecar(record: dict) -> dict:
    """把一条观测记录压成随件 sidecar（`*.cache_state.json` 的内容），带上判定与退出码。

    缺字段不编造：`None` 就是 `None`，让消费者看见「没测到」而不是「测到 0」。
    """
    judged = evaluate(record)
    out = {key: record.get(key) for key in SIDECAR_KEYS}
    out.update({"verdict": judged["verdict"], "exit_code": judged["exit_code"],
                "spec": "cache_state/1",
                "behavior": record.get("behavior"),
                "note": judged.get("reason", "")})
    return out


def exit_code(verdict: str) -> int:
    if verdict not in _EXIT:
        raise CacheStateError("未知判定词：%r" % (verdict,))
    return _EXIT[verdict]


def evaluate(record: dict) -> dict:
    """单条观测 → `{verdict, exit_code, reason?}`。缺字段一律 UNREADABLE，不放行。"""
    if not isinstance(record, dict):
        raise CacheStateError("record 必须是 dict")
    if not record.get("exists", False):
        return {"verdict": UNREADABLE_VERDICT, "exit_code": UNREADABLE,
                "reason": "文件不存在或读不到"}
    try:
        verdict = classify(
            has_physics=record.get("has_physics", record.get("rigidbody_world") is not None),
            is_baked=record.get("is_baked"),
            is_outdated=record.get("is_outdated"),
            behavior=record.get("behavior"),
        )
    except CacheStateError as exc:
        return {"verdict": UNREADABLE_VERDICT, "exit_code": UNREADABLE, "reason": str(exc)}
    out = {"verdict": verdict, "exit_code": exit_code(verdict)}
    if verdict == DEFECT_BAKED_OUTDATED:
        out["reason"] = DEFECT_REASON
        parsed = parse_behavior(record.get("behavior"))
        if parsed is not None:
            out["behavior"] = parsed
    elif verdict == SUSPECT_BAKED_OUTDATED:
        out["reason"] = SUSPECT_REASON
    return out


#: 批量时「最坏」不是数值最大：**已证实的缺陷比「判不了」更坏**。
#: 顺序 = OK(0) < 判不了(4) < 缺陷(3)。单份的判定词与退出码永远照实写在 report 里。
_SEVERITY = {OK: 0, UNREADABLE: 1, DEFECT: 2}


def evaluate_many(records: dict) -> tuple[int, dict]:
    """批量判定，返回 `(最坏退出码, {path: 判定记录})`。空输入按 0 处理。

    最坏按严重度取：任一份已证实缺陷 ⇒ 3；否则任一份判不了 ⇒ 4；否则 0。
    """
    report = {}
    worst_code = OK
    worst_rank = 0
    for path, rec in records.items():
        merged = dict(rec or {})
        merged.setdefault("exists", True)
        judged = evaluate(merged)
        report[path] = {**merged, **judged}
        rank = _SEVERITY[judged["exit_code"]]
        if rank > worst_rank:
            worst_rank, worst_code = rank, judged["exit_code"]
    return worst_code, report


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: python -m mmdpipe.cache_state records.json", file=sys.stderr)
        return 2
    with open(argv[0], encoding="utf-8") as fh:
        records = json.load(fh)
    code, report = evaluate_many(records)
    print(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
