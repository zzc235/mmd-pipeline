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
    "首次 frame_set 会重算。"
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
