"""pipeline_state 的读取、兼容判定与迁移。

为什么需要它：`pipeline_state.json` 是这整条流水线的唯一真相，字段一直在加
（v1.1.x 没有 env / artifacts / fingerprint；v1.3.0 加了 layout / run_id / final）。
旧 state 被新代码读到，最坏的结果不是报错，而是**静默用错语义**：
比如把旧记录误当成"这次续跑的状态"，于是跳过该做的阶段。

所以规则写在这里，只有三种结论：

    schema <  2        旧语义，说不清字段含义 → 拒绝（调用方归档/改名，不猜）
    schema == 2        可读 → 迁移到当前（补 layout=legacy / run_id / paths，纯内存）
    schema == 3        当前
    schema >  3        比本插件新 → 拒绝（新字段什么意思不知道）

纯 Python，不 import bpy，可单测。
"""
from __future__ import annotations

import json
import os

from . import layout as layout_mod

SCHEMA = 3
MIN_READABLE = 2


class StateIncompatible(Exception):
    """state 不能按当前语义读。`newer=True` 表示是插件太旧，不是文件太旧。"""

    def __init__(self, path: str, reason: str, hint: str = "", newer: bool = False):
        super().__init__("%s：%s" % (path, reason))
        self.path = path
        self.reason = reason
        self.hint = hint
        self.newer = newer


def read(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def schema_of(raw: dict) -> int:
    """缺 schema 视为 0（v1.1.x 的 state 没有这个字段）。"""
    try:
        return int(raw.get("schema") or 0)
    except (TypeError, ValueError):
        return 0


def migrate(raw: dict) -> tuple:
    """把可读的旧 state 升到当前 schema。返回 (new_state, notes)；不改传入对象。"""
    state = json.loads(json.dumps(raw))          # 深拷贝，调用方的对象保持原样
    notes = []
    current = schema_of(state)
    if current == SCHEMA:
        return state, notes
    if current < MIN_READABLE:
        raise StateIncompatible(
            "<memory>", "schema=%s 早于可读下限 %d" % (current, MIN_READABLE),
            "schema 1 是 v1.1.x 的记录（有 stages/artifacts/fingerprint，但没有 env），"
            "字段集合与当前不同，不能拿来续跑")
    if current > SCHEMA:
        raise StateIncompatible(
            "<memory>", "schema=%s 比本插件的新（当前 %d）" % (current, SCHEMA),
            "升级插件，或换一个 --out 目录", newer=True)

    if current == 2:
        # 2 → 3：只补字段，语义不变（v2 的记录本来就是"全写在根目录"）
        state.setdefault("layout", "legacy")
        state.setdefault("run_id", layout_mod.run_id(state.get("started_at", "")))
        state.setdefault("paths", {
            "root": None, "work": None, "final": "",
            "note": "由 schema 2 迁移而来：原始输出目录未记录",
        })
        state["schema"] = SCHEMA
        notes.append("state 由 schema 2 迁移到 %d（补 layout=legacy / run_id / paths）" % SCHEMA)
    return state, notes


def load_compatible(path: str) -> tuple:
    """读一个 state 并按当前语义返回 (state, notes)。不可读时抛 StateIncompatible。"""
    if not os.path.exists(path):
        raise StateIncompatible(path, "文件不存在")
    try:
        raw = read(path)
    except (OSError, ValueError) as exc:
        raise StateIncompatible(path, "不是合法 JSON：%s" % exc)
    try:
        return migrate(raw)
    except StateIncompatible as exc:
        exc.path = path
        exc.args = ("%s：%s" % (path, exc.reason),)
        raise


def summarize(state: dict) -> str:
    """给日志/CLI 用的一行摘要。"""
    stages = state.get("stages") or {}
    blocked = state.get("blocked_by") or []
    return "schema=%s ok=%s 阶段=%d 卡在=%s 布局=%s run=%s" % (
        state.get("schema"), state.get("ok"), len(stages),
        ",".join(blocked) if blocked else "-",
        state.get("layout", "?"), state.get("run_id", "?"))


def main(argv=None) -> int:
    """`python -m mmdpipe.statefile 路径` —— 看一份旧 state 能不能用。"""
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("用法：python -m mmdpipe.statefile <pipeline_state.json> [更多…]")
        return 1
    rc = 0
    for path in argv:
        try:
            state, notes = load_compatible(path)
        except StateIncompatible as exc:
            # 只用 ASCII 记号：GBK 控制台打不出 ✓/✗（实测 UnicodeEncodeError）
            print("[FAIL] %s" % exc)
            if exc.hint:
                print("  -> %s" % exc.hint)
            rc = 2
            continue
        print("[OK] %s" % summarize(state))
        for n in notes:
            print("  . %s" % n)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
