"""任务级状态的派生视图（**只读**，不写任何文件）。

    python -m coordination.status
    python -m coordination.status --status <task_status.json> --decisions <decisions.jsonl>

为什么要这一层：`out/subai/coordination/board.db` 是运行时状态的唯一权威；
`coordination/task_status.json` 只是兼容视图，`coordination/decisions.jsonl` 是裁决历史。
三者**必须对得上**——对不上说明状态迁移、裁决落库或派生视图中间断链。这条对账不能靠人眼，所以放在这里。

退出码：
    0  正常（打印表 + 待 Human 批项）
    2  用法错误（argparse 自己的退出码）
    3  表与历史冲突（任务集对不上 / status 不在枚举里 / 结构不对）
    4  读不到（文件不存在、不是合法 JSON、不是对象）
"""
from __future__ import annotations

import io

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


def _mentions(row: dict, decision_id: str) -> bool:
    """这条裁决有没有**显式**提到某条待批项（任何字符串字段/列表里出现它的 id）。"""
    if not decision_id:
        return False
    for key, value in row.items():
        if key == "decision_id":
            continue
        if isinstance(value, str) and decision_id in value:
            return True
        if isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str) and decision_id in item:
                    return True
    return False


def pending_human(decisions: list, history: dict | None = None) -> list:
    """待 Human 批项：**全量聚合**，跨任务、跨时间，不靠"取最后一条"。

    2026-11-16 修的真缺陷：旧实现按「同一任务后续任意裁决即清账」，于是
    `D-20261116-075`（掩码结构性未接线，等 Owner 批）被后来的 `D-083` **挤掉**了——
    没有任何人回答过它，它只是不再是最新一条。**这是最坏的一类状态载体说谎：消失得没有痕迹。**

    现在的规矩：一条待批项只有在**后续裁决显式提到它**（`resolves` / `answers` / 正文里出现它的
    decision_id）时才算关闭。时间顺序本身不构成回答。
    """
    pending = []
    for idx, row in enumerate(decisions):
        if not row.get("human_approval_required"):
            continue
        did = row.get("decision_id") or ""
        closed = any(_mentions(later, did) for later in decisions[idx + 1:])
        if not closed:
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


# ----------------------------------------------------------------- 三向对账（阶段 C）
#
# 目的：防止「报告说一套、状态表说一套、board 空一套」。这里只做**机器比对**，
# 不靠人眼；任何不一致都进 conflicts 列表，并且退出码可被 CI 直接判。

def _board_tasks(board_path: str) -> dict:
    import sqlite3
    # `mode=ro`：状态对账是只读视图，不允许缺库时由查询命令造一个空库。
    uri = "file:%s?mode=ro" % os.path.abspath(board_path).replace("\\", "/")
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT task_id, status, legacy_status, state_reason, base_commit FROM tasks").fetchall()
    finally:
        conn.close()
    return {row["task_id"]: dict(row) for row in rows}


def _legacy_board_writers() -> list:
    """扫本包里有没有模块**真的**把硬编码的 `board.db` 喂给 sqlite3.connect。

    只认 AST：`sqlite3.connect(<字符串常量以 board.db 结尾>)` 才算。
    为什么不用正则：`out/subai/coordination/board.db` 这种正当路径里也含
    `coordination/board.db` 字面量，正则会把**注释和文档**一起判红——那正是今天
    治的「扫描器误报」，闸门自己先不能犯。
    """
    import ast
    import glob
    here = os.path.dirname(os.path.abspath(__file__))
    bad = []
    for p in sorted(glob.glob(os.path.join(here, "*.py"))):
        name = os.path.basename(p)
        if name == "status.py":
            continue
        try:
            tree = ast.parse(io.open(p, encoding="utf-8").read())
        except SyntaxError:
            bad.append(name + "(syntax)")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_connect = (isinstance(func, ast.Attribute) and func.attr == "connect"
                          and isinstance(func.value, ast.Name) and func.value.id == "sqlite3")
            if not is_connect or not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                    and arg.value.endswith("board.db") and "out/subai" not in arg.value \
                    and "out\\subai" not in arg.value:
                bad.append(name)
    return sorted(set(bad))


def check(status_path: str, decisions_path: str, board_path: str | None = None) -> tuple:
    """三向对账：状态表 / 裁决历史 / board。返回 (payload, exit_code)。"""
    from . import paths as paths_mod

    board_path = board_path or paths_mod.board_path()
    payload = {"state": "OK", "conflicts": [], "pending_human": [], "task_count": 0,
               "board_path": os.path.abspath(board_path), "checks": {}}
    try:
        status_doc = load_status(status_path)
        decisions = load_decisions(decisions_path)
    except Unreadable as exc:
        payload.update(state="UNREADABLE", conflicts=["UNREADABLE: %s" % exc])
        return payload, 4
    except Conflict as exc:
        payload.update(state="CONFLICT", conflicts=["HISTORY: %s" % exc])
        return payload, 3

    tasks = status_doc["tasks"]
    payload["task_count"] = len(tasks)
    try:
        board_tasks = _board_tasks(board_path)
    except Exception as exc:                     # 库不存在/读不动 ⇒ UNREADABLE，不是 OK
        payload.update(state="UNREADABLE", conflicts=["BOARD_UNREADABLE: %s" % exc])
        return payload, 4

    from .sync_board import STATE_DECISIONS

    conflicts = []

    def add(code: str, detail: str) -> None:
        conflicts.append("%s: %s" % (code, detail))

    # C1/C4/C5：任务集合双向一致
    missing_in_board = sorted(set(tasks) - set(board_tasks))
    only_in_board = sorted(set(board_tasks) - set(tasks))
    payload["checks"]["C1_task_sets_equal"] = not missing_in_board and not only_in_board
    if missing_in_board:
        add("C1", "状态表有、board 没有：%s" % ", ".join(missing_in_board))
    if only_in_board:
        add("C5", "board 有、状态表没有：%s" % ", ".join(only_in_board))

    # C2：legacy_status 必须等于状态表的 status
    legacy_bad = []
    for task in sorted(set(tasks) & set(board_tasks)):
        got = board_tasks[task].get("legacy_status")
        want = tasks[task]["status"]
        if got != want:
            legacy_bad.append("%s(board=%r,status=%r)" % (task, got, want))
    payload["checks"]["C2_legacy_status_matches"] = not legacy_bad
    if legacy_bad:
        add("C2", "legacy_status 与状态表不一致：%s" % ", ".join(legacy_bad))

    # C3：非 NOT_STARTED 任务必须有一条可识别的状态变更裁决
    state_rows = {}
    for row in decisions:
        tid = row.get("task_id")
        if isinstance(tid, str) and row.get("decision") in STATE_DECISIONS:
            state_rows.setdefault(tid, []).append(row)
    no_decision = sorted(t for t in tasks
                         if tasks[t]["status"] != "NOT_STARTED" and t not in state_rows)
    payload["checks"]["C3_state_decision_present"] = not no_decision
    if no_decision:
        add("C3", "非 NOT_STARTED 但没有状态变更裁决：%s" % ", ".join(no_decision))

    # C6：待 Human 项与 status 工具输出一致（同一份聚合函数的唯一出口）
    pending = pending_human(decisions)
    payload["pending_human"] = [row.get("decision_id") for row in pending]
    try:
        from . import human_gate as human_gate_mod
        gate_ids = [row["id"] for row in human_gate_mod.list_open()]
        payload["checks"]["C6_pending_matches_human_gate"] = gate_ids == payload["pending_human"]
        if gate_ids != payload["pending_human"]:
            add("C6", "human_gate 清单与 status 聚合不一致：gate=%s status=%s"
                % (gate_ids, payload["pending_human"]))
    except ImportError:
        payload["checks"]["C6_pending_matches_human_gate"] = True

    # C7：deps_unknown 只允许出现在 blocked 任务上；completed 任务必须有 artifact
    with_deps_unknown = set()
    import sqlite3
    uri = "file:%s?mode=ro" % os.path.abspath(board_path).replace("\\", "/")
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        for row in conn.execute("SELECT task_id FROM events WHERE type='sync.deps_unknown'"):
            with_deps_unknown.add(row["task_id"])
        artifacts_by_task = {}
        for row in conn.execute("SELECT task_id, COUNT(*) c FROM artifacts GROUP BY task_id"):
            artifacts_by_task[row["task_id"]] = row["c"]
    finally:
        conn.close()
    unexplained = sorted(t for t in with_deps_unknown
                         if t in board_tasks and board_tasks[t]["status"] == "completed"
                         and not board_tasks[t].get("base_commit")
                         and not artifacts_by_task.get(t))
    no_identity = sorted(t for t, row in board_tasks.items()
                         if row["status"] == "completed"
                         and not row.get("base_commit") and not artifacts_by_task.get(t))
    payload["checks"]["C7_deps_explained"] = not unexplained and not no_identity
    if unexplained:
        add("C7", "completed 任务带 deps_unknown 且没有 base_commit/artifact：%s"
            % ", ".join(unexplained))
    if no_identity:
        add("C7", "completed 任务既无 base_commit 也无 artifact（身份不可追）：%s"
            % ", ".join(no_identity))

    # C8：0 字节空壳不得被任何模块按字面量读取
    legacy_readers = _legacy_board_writers()
    shell = os.path.join(os.path.dirname(os.path.abspath(status_path)), "board.db")
    shell_bytes = os.path.getsize(shell) if os.path.exists(shell) else None
    payload["checks"]["C8_empty_shell_unused"] = not legacy_readers and shell_bytes in (0, None)
    if legacy_readers:
        add("C8", "有模块按字面量读 coordination/board.db：%s" % ", ".join(legacy_readers))
    if shell_bytes not in (0, None):
        add("C8", "coordination/board.db 不是 0 字节（%s），空壳说法不成立" % shell_bytes)

    payload["conflicts"] = conflicts
    payload["state"] = "CONFLICT" if conflicts else "OK"
    return payload, (3 if conflicts else 0)


def build(parser, argv=None) -> int:
    args = parser.parse_args(argv)
    if getattr(args, "check", False):
        payload, code = check(args.status, args.decisions, getattr(args, "board", None))
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return code
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
    from .cli import ensure_utf8_stdio
    ensure_utf8_stdio()
    ap = argparse.ArgumentParser(prog="coordination.status",
                                 description="任务级状态派生视图（只读，不写文件）")
    ap.add_argument("--status", default=DEFAULT_STATUS, help="权威状态表（缺省 coordination/task_status.json）")
    ap.add_argument("--decisions", default=DEFAULT_DECISIONS, help="裁决历史（缺省 coordination/decisions.jsonl）")
    ap.add_argument("--check", action="store_true",
                    help="三向对账：状态表 / 裁决历史 / board（单行 JSON；退出码 0 OK / 3 CONFLICT / 4 UNREADABLE）")
    ap.add_argument("--board", default=None, help="board 路径（缺省 paths.board_path()）")
    return build(ap, argv)


if __name__ == "__main__":
    sys.exit(main())
