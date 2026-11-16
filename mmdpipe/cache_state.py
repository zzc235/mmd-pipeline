"""刚体 point cache 一致性判据（纯 Python，不 import bpy）。

## 为什么需要它

交付的 `.blend` 可能带着**已烘焙但标记为过期**的缓存（`point_cache.is_baked = True` 且
`is_outdated = True`）。这种工程打开就能播放，但：

- **默认消费路径**（打开 + `frame_set`）= 回放缓存；
- **任何触发重算的路径**（解烘焙、改物理参数、重新导入）= 另一条轨迹。

M02 在 `B_from_blend1.blend` 上实测过：两条轨迹差**下摆骨 0.9087 m / 全刚体 1.5867 m**，
且单帧跳转与逐帧步进给出逐位相同的数字（回放指纹）。同一个文件两种动画 ⇒ 动画不可复现。

因此产物必须落在下面两种状态之一：

| `is_baked` | `is_outdated` | 判定 | 退出码 |
|---|---|---|---|
| False | 任意 | `OK_UNBAKED`：不烘焙，首次 `frame_set` 会重算 | 0 |
| True | False | `OK_BAKED_CONSISTENT`：烘焙与当前设置一致（回放 == 重算） | 0 |
| True | True | `DEFECT_BAKED_OUTDATED`：回放与重算不是同一条动画 | 3 |
| 无 `rigidbody_world` | — | `OK_NO_PHYSICS` | 0 |
| 读不到 / 字段缺失 | — | `UNREADABLE`（fail closed，不猜） | 4 |

## 用法

判据本身不碰 bpy：调用方（Blender 侧探针、`stage.py`、CI）把观测值喂进来。

    from mmdpipe import cache_state
    rec = cache_state.evaluate({"exists": True, "has_physics": True,
                               "is_baked": True, "is_outdated": True})
    rec["verdict"], rec["exit_code"]        # 'DEFECT_BAKED_OUTDATED', 3

批量与 CLI（便于把探针输出直接判）：

    python -m mmdpipe.cache_state records.json    # 退出码 = 最坏的一条

## 别信 `point_cache.info`

`info` 是**存进 `.blend` 的字符串**，帧数据不在里面。P12 实测：一份「解烘焙 → 顺序步进 1→240
→ 存盘」的工程，重开后 `info` 仍写着 `240 frames in memory (2.1 MiB).`，而 `is_outdated` 已经
翻回 `True`——数据没了。**判据只认 `is_baked` / `is_outdated` 两个布尔，`info` 当线索不当证据。**
"""
from __future__ import annotations

import json
import sys

OK = 0
DEFECT = 3
UNREADABLE = 4

OK_UNBAKED = "OK_UNBAKED"
OK_BAKED_CONSISTENT = "OK_BAKED_CONSISTENT"
OK_NO_PHYSICS = "OK_NO_PHYSICS"
DEFECT_BAKED_OUTDATED = "DEFECT_BAKED_OUTDATED"
UNREADABLE_VERDICT = "UNREADABLE"

VERDICTS = (OK_UNBAKED, OK_BAKED_CONSISTENT, OK_NO_PHYSICS, DEFECT_BAKED_OUTDATED,
            UNREADABLE_VERDICT)

_EXIT = {
    OK_UNBAKED: OK,
    OK_BAKED_CONSISTENT: OK,
    OK_NO_PHYSICS: OK,
    DEFECT_BAKED_OUTDATED: DEFECT,
    UNREADABLE_VERDICT: UNREADABLE,
}

DEFECT_REASON = (
    "回放（默认路径）与解烘焙重算会给出两条不同动画；产物要么重算后重新烘焙并保存"
    "（is_baked=true && is_outdated=false），要么不烘焙（is_baked=false）并在 handoff 写明"
    "首次 frame_set 会重算、且消费方必须从 scene.frame_start 顺序求值"
    "（跳到中间帧会得到第三条轨迹）。"
)


class CacheStateError(ValueError):
    """观测记录不可解释（缺字段、类型不对）——不猜，按 UNREADABLE 处理。"""


def classify(*, has_physics: bool, is_baked: bool | None, is_outdated: bool | None) -> str:
    """按四个状态给出判定词。参数类型不对直接抛 `CacheStateError`。"""
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
    return OK_BAKED_CONSISTENT if not is_outdated else DEFECT_BAKED_OUTDATED


PLAN_NONE = "none"
PLAN_SEQUENTIAL_DELIVERY = "sequential_delivery"
PLAN_INSPECT = "inspect"
PLAN_ACTIONS = (PLAN_NONE, PLAN_SEQUENTIAL_DELIVERY, PLAN_INSPECT)

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
    "真正的修复只有重烘焙（is_baked=true && is_outdated=false），需 `bpy.ops.ptcache.bake_all()`，"
    "而 10 §6 因 312 刚体段错误禁用它；plan() 不擅自跨这条线。"
)


def plan(record: dict) -> dict:
    """判据 → 修法。只给动作名，不执行（执行需要 bpy，见 `rebake_fix.md`）。

    - `OK_*`       → `{"action": "none"}`
    - `DEFECT_*`   → `{"action": "sequential_delivery"}`：产物保存前清空 point cache
      （`ptcache.free_bake_all()`），于是默认路径首次就是重算、回放与重算不再分叉；
      代价是**消费方必须从起始帧顺序求值**，这条契约必须随产物一起交付。
    - `UNREADABLE` → `{"action": "inspect"}`：先能读到缓存状态再谈修法。

    「跑一遍再存盘」（`rebake_by_stepping`）已被 P12 证伪，见 `REJECTED_ACTIONS`。
    """
    judged = evaluate(record)
    action = {"OK_UNBAKED": PLAN_NONE, "OK_BAKED_CONSISTENT": PLAN_NONE,
              "OK_NO_PHYSICS": PLAN_NONE,
              DEFECT_BAKED_OUTDATED: PLAN_SEQUENTIAL_DELIVERY,
              UNREADABLE_VERDICT: PLAN_INSPECT}[judged["verdict"]]
    return {**judged, "action": action,
            "note": _SEQUENTIAL_NOTE if action == PLAN_SEQUENTIAL_DELIVERY else ""}


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
        )
    except CacheStateError as exc:
        return {"verdict": UNREADABLE_VERDICT, "exit_code": UNREADABLE, "reason": str(exc)}
    out = {"verdict": verdict, "exit_code": exit_code(verdict)}
    if verdict == DEFECT_BAKED_OUTDATED:
        out["reason"] = DEFECT_REASON
    return out


def evaluate_many(records: dict) -> tuple[int, dict]:
    """批量判定，返回 `(最坏退出码, {path: 判定记录})`。空输入按 0 处理。"""
    report = {}
    worst = OK
    for path, rec in records.items():
        merged = dict(rec or {})
        merged.setdefault("exists", True)
        judged = evaluate(merged)
        report[path] = {**merged, **judged}
        worst = max(worst, judged["exit_code"])
    return worst, report


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
