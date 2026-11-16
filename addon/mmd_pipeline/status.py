"""产物布局与运行状态的只读解析（纯 Python，不 import bpy）。

为什么单独一层：面板与 operator 原先直接假定产物在 `<out>/frames`、
完成状态在 `<out>/pipeline_state.json`。isolated 布局（1.3.0 起的默认值）
把帧序列放到 `<out>/work/<run_id>/frames`，于是进度条永远 0——
而这个错误在"能打包、能跑"的路径上完全看不出来。

契约（与 mmdpipe.layout 对齐，这里不复制规则，只读 state 里记录的路径）：
    pipeline_state.json 永远在 `<out>` 根目录（它是"最近一次运行"，不跟 run_id 走）
    state["paths"]["work"]  中间产物目录，帧序列在它的 frames/ 下
    state["paths"]["final"] 成片目录，只有全流程通过才落地
legacy 布局与旧 state（schema 2 迁移后 paths 全 None）退回 `<out>` 根目录。

降级原则：state 缺失 / 半写完 / 字段被删，都不抛异常，只给出"读不到"的结果，
由调用方决定怎么显示——面板里一个 Traceback 比一个"读不到"坏得多。
"""
from __future__ import annotations

import json
import os

STATE_NAME = "pipeline_state.json"
FRAMES_SUBDIR = "frames"


def read_state(root: str) -> dict:
    """读 `<root>/pipeline_state.json`。任何失败都返回空 dict，不抛异常。"""
    path = os.path.join(root, STATE_NAME)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _work_dir(root: str, state: dict) -> str:
    """中间产物目录。state 里没有可信记录时退回 `<out>` 根目录（legacy 行为）。"""
    paths = state.get("paths") if isinstance(state.get("paths"), dict) else {}
    work = paths.get("work")
    layout = state.get("layout") or ("isolated" if paths else "legacy")
    if layout == "isolated" and work:
        return work
    return root


def resolve(root: str, state: dict | None = None) -> dict:
    """算出这次运行各产物在哪。state 可传入（避免重复读盘），缺省现读。"""
    root = os.path.abspath(root)
    if state is None:
        state = read_state(root)
    paths = state.get("paths") if isinstance(state.get("paths"), dict) else {}
    work = _work_dir(root, state)
    final = paths.get("final") or ""
    layout = state.get("layout") or ("isolated" if paths.get("work") else "legacy")
    return {
        "root": root,
        "layout": layout,
        "run_id": state.get("run_id") or "",
        "work": work,
        "final": final,
        "frames": os.path.join(work, FRAMES_SUBDIR),
        "mp4": os.path.join(final or work, "result.mp4"),
        "state": os.path.join(root, STATE_NAME),
        "log": os.path.join(root, "run.log"),
    }


def count_frames(frames_dir: str) -> int:
    """数 PNG 帧。目录不存在 / 不可读一律 0。"""
    try:
        return sum(1 for f in os.listdir(frames_dir) if f.lower().endswith(".png"))
    except OSError:
        return 0


def progress_pct(rendered: int, expected: int, cap: int = 99) -> int:
    """渲染进度。封顶留在 cap：完成由进程退出码判定，不由帧数猜。"""
    total = max(1, int(expected or 0))
    return max(0, min(cap, int(rendered * 100 / total)))


def current_stage(state: dict) -> str:
    """最后一个记录过的阶段名；没有就空串。"""
    stages = state.get("stages") or {}
    if not isinstance(stages, dict):
        return ""
    names = list(stages)
    return names[-1] if names else ""


def failure_reason(state: dict, limit: int = 2) -> str:
    """从 state 里提炼可操作失败原因：优先 blocked_by 阶段的 block 级 issue。

    返回形如 `S3_chain: E-15 拼接帧数不守恒：…`；多条用 ` / ` 连接；读不出就空串。
    """
    stages = state.get("stages") or {}
    if not isinstance(stages, dict):
        return ""
    blocked = state.get("blocked_by") or []
    order = [s for s in blocked if s in stages] or list(stages)
    out = []
    for name in order:
        stage = stages.get(name) or {}
        for issue in stage.get("issues") or []:
            if issue.get("severity") != "block":
                continue
            out.append("%s: %s %s" % (name, issue.get("code", "?"), issue.get("hint", "")))
            break
        if len(out) >= limit:
            break
    return " / ".join(out)


def report_lines(root: str, info: dict | None = None) -> list:
    """报告区要显示的行（纯字符串，面板只负责画）。

    读不到就明说读不到，绝不抛异常——面板里一个 Traceback 比一句"读不到"坏得多。
    """
    if not root:
        return ["还没选输出目录"]
    info = info or summary(root)
    lines = ["状态 %s · 布局 %s · 帧 %d" % ("完成" if info["ok"] else "未完成",
                                           info["layout"], info["frames"])]
    if info["stage"]:
        lines.append("阶段 %s" % info["stage"])
    if info["reason"]:
        lines.append("卡在 %s" % info["reason"])
    elif info["blocked_by"]:
        lines.append("卡在 %s" % ", ".join(info["blocked_by"]))
    return lines


def summary(root: str, state: dict | None = None) -> dict:
    """给报告区用的一屏摘要：状态、阶段、路径、失败原因、帧数。"""
    if state is None:
        state = read_state(root)
    paths = resolve(root, state)
    rendered = count_frames(paths["frames"])
    return {
        "ok": bool(state.get("ok")),
        "layout": paths["layout"],
        "run_id": paths["run_id"],
        "stage": current_stage(state),
        "blocked_by": list(state.get("blocked_by") or []),
        "reason": failure_reason(state),
        "frames": rendered,
        "frames_dir": paths["frames"],
        "final": paths["final"],
        "state": paths["state"],
        "log": paths["log"],
        "mp4": paths["mp4"],
    }


def main(argv=None) -> int:
    """`python status.py <out目录>` —— 不开 Blender 也能核对面板读到的路径。"""
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("用法：python status.py <输出目录>")
        return 1
    info = summary(argv[0])
    for key in ("ok", "layout", "run_id", "stage", "blocked_by", "frames",
                "frames_dir", "final", "state", "log", "mp4", "reason"):
        print("%-12s %s" % (key, info[key]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
