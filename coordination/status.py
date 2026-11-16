"""任务级状态的派生视图（**只读**，不写任何文件）。

    python -m coordination.status
    python -m coordination.status --status <task_status.json> --decisions <decisions.jsonl>

为什么要这一层：`coordination/task_status.json` 是「现在是什么状态」的唯一权威表，
`coordination/decisions.jsonl` 是历史与证据。两张表**必须对得上**——对不上说明要么
D0 裁决完忘了改表，要么表里凭空多了任务。这条对账不能靠人眼，所以放在这里。

退出码：
    0  正常（打印表 + 待 Human 批项）
    2  用法错误（argparse 自己的退出码）
    3  表与历史冲突（任务集对不上 / status 不在枚举里 / 结构不对）
    4  读不到（文件不存在、不是合法 JSON、不是对象）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

STATUSES = ("PASS", "PARTIAL", "BLOCKED", "NOT_STARTED")
# 任务编号长这样：M00…M08。裁决历史里还有 A3 / LANE / LEASE 这类「不是任务编号」
# 的条目（席位、通道、租约类裁决），它们不参与任务集对账，只在末尾报个数。
TASK_ID_RE = re.compile(r"^M\d{2}$")
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_STATUS = os.path.join(HERE, "task_status.json")
DEFAULT_DECISIONS = os.path.join(HERE, "decisions.jsonl")


class Conflict(ValueError):
    """表与历史对不上（退出码 3）。"""


class Unreadable(ValueError):
    """文件读不到或不是合法 JSON（退出码 4）。"""


def load_status(path: str) -> dict:
    """读权威表；结构不合法抛 Conflict，读不到抛 Unreadable。"""
    if not os.path.exists(path):
        raise Unreadable("找不到状态表：%s" % path)
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:   # 容忍 Windows 工具链写的 BOM
            raw = json.load(fh)
    except (ValueError, OSError) as exc:
        raise Unreadable("状态表读不成 JSON：%s（%s）" % (path, exc))
    if not isinstance(raw, dict):
        raise Conflict("状态表顶层必须是对象，收到 %s" % type(raw).__name__)
    tasks = raw.get("tasks")
    if not isinstance(tasks, dict) or not tasks:
        raise Conflict("状态表缺 tasks 段，或 tasks 不是非空对象")
    for name, row in tasks.items():
        if not isinstance(row, dict):
            raise Conflict("tasks[%s] 必须是对象" % name)
        status = row.get("status")
        if status not in STATUSES:
            raise Conflict("tasks[%s].status=%r 不在枚举 %s 里" % (name, status, "/".join(STATUSES)))
        if not isinstance(row.get("next", ""), str):
            raise Conflict("tasks[%s].next 必须是字符串" % name)
    return raw


def load_decisions(path: str) -> list:
    """读历史；单行坏 JSON 抛 Unreadable（宁可停下，也不要静默跳过一条裁决）。"""
    if not os.path.exists(path):
        raise Unreadable("找不到裁决历史：%s" % path)
    rows = []
    with open(path, "r", encoding="utf-8-sig") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise Unreadable("裁决历史第 %d 行不是 JSON：%s" % (lineno, exc))
            if not isinstance(row, dict):
                raise Unreadable("裁决历史第 %d 行不是对象" % lineno)
            rows.append(row)
    if not rows:
        raise Conflict("裁决历史是空的，状态表无从对账")
    return rows


def reconcile(status_doc: dict, decisions: list) -> dict:
    """对账：任务集必须双向一致；返回每个任务的最后裁决。

    一条必要的例外：`NOT_STARTED` 的任务**可以**没有任何裁决（M08 就是），
    否则「还没开工」这件事本身会被判成冲突。除此之外，
    「表里有状态但没有对应裁决」= D0 裁决完忘了改表 / 表里凭空多任务；
    「历史里有裁决但表里没登记」= 表漏了一行，两向都要报。
    """
    tasks = status_doc["tasks"]
    in_history = {}
    non_task_ids = set()
    for row in decisions:
        task = row.get("task_id")
        if isinstance(task, str) and TASK_ID_RE.match(task):
            in_history.setdefault(task, []).append(row)
        elif isinstance(task, str) and task:
            non_task_ids.add(task)

    missing_history = sorted(t for t in tasks
                             if t not in in_history and tasks[t]["status"] != "NOT_STARTED")
    only_history = sorted(set(in_history) - set(tasks))
    if missing_history:
        raise Conflict("状态表里有、裁决历史里没有的任务（且状态不是 NOT_STARTED）：%s"
                       % ", ".join(missing_history))
    if only_history:
        raise Conflict("裁决历史里有、状态表里没登记的任务：%s" % ", ".join(only_history))

    last = {task: rows[-1] for task, rows in in_history.items()}
    return {"last": last, "history": in_history, "non_task_ids": non_task_ids}


def pending_human(decisions: list, history: dict) -> list:
    """待 Human 批项：带 human_approval_required 且其后没有针对同一任务的新裁决。"""
    pending = []
    for idx, row in enumerate(decisions):
        if not row.get("human_approval_required"):
            continue
        task = row.get("task_id")
        later = [r for r in decisions[idx + 1:]
                 if (r.get("task_id") or None) == (task or None)]
        if later:
            continue
        pending.append(row)
    return pending


def render(status_doc: dict, reconciled: dict, pending: list) -> list:
    tasks = status_doc["tasks"]
    last = reconciled["last"]
    name_w = max([len(t) for t in tasks] + [4])
    status_w = max([len(r["status"]) for r in tasks.values()] + [6])
    lines = []
    lines.append("%-*s  %-*s  %-24s  %s" % (name_w, "task", status_w, "status",
                                            "最后裁决", "next"))
    lines.append("%s  %s  %s  %s" % ("-" * name_w, "-" * status_w, "-" * 24, "-" * 4))
    for task in sorted(tasks):
        row = tasks[task]
        decision = last.get(task) or {}
        lines.append("%-*s  %-*s  %-24s  %s" % (
            name_w, task, status_w, row["status"],
            decision.get("decision_id", "（无）"), row.get("next", "")))
    counts = {}
    for row in tasks.values():
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    lines.append("")
    lines.append("小计：" + " / ".join("%s %d" % (s, counts.get(s, 0)) for s in STATUSES))
    if reconciled.get("non_task_ids"):
        lines.append("另有 %d 条裁决的 task_id 不是 Mxx 形式（不参与对账）：%s"
                     % (len(reconciled["non_task_ids"]),
                        ", ".join(sorted(reconciled["non_task_ids"]))))
    lines.append("")
    if pending:
        lines.append("待 Human 批项（%d）：" % len(pending))
        for row in pending:
            lines.append("  %s  %s  %s" % (row.get("decision_id", "?"), row.get("task_id") or "(项目级)",
                                           _clip(row.get("next_action") or row.get("reason_code") or "")))
    else:
        lines.append("待 Human 批项：无")
    return lines


def _clip(text: str, width: int = 120) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[:width - 1] + "…"


def build(parser, argv=None) -> int:
    args = parser.parse_args(argv)
    try:
        status_doc = load_status(args.status)
        decisions = load_decisions(args.decisions)
        reconciled = reconcile(status_doc, decisions)
    except Unreadable as exc:
        print("STATUS 读不到：%s" % exc)
        return 4
    except Conflict as exc:
        print("STATUS 表与历史冲突：%s" % exc)
        return 3

    pending = pending_human(decisions, reconciled["history"])
    for line in render(status_doc, reconciled, pending):
        print(line)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="coordination.status",
                                 description="任务级状态派生视图（只读，不写文件）")
    ap.add_argument("--status", default=DEFAULT_STATUS, help="权威状态表（缺省 coordination/task_status.json）")
    ap.add_argument("--decisions", default=DEFAULT_DECISIONS, help="裁决历史（缺省 coordination/decisions.jsonl）")
    return build(ap, argv)


if __name__ == "__main__":
    sys.exit(main())
