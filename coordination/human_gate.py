"""阶段 H：**受控 Human gate**——待批项只能被 Human 显式回答关掉。

规矩（`14 号令 §3-H`）：
1. `list_open()` 是待批项的**唯一出口**，与 `status.pending_human()` 同源，
   两边必须逐条相同（`status --check` 的 C6 就是在核这件事）。
2. **只有显式 `resolve` 才关闭**：超时不关、后续无关裁决顺带不关、D0 不许代关。
3. `resolve` 只接受 `--by Human`；写 `by: "Human"` 且把目标 decision_id 放进 `resolves[]`，
   于是 `pending_human()` 的「后续裁决显式提到它」判据成立——这是关闭的唯一机器路径。
4. 关闭动作本身也是一条**新裁决**（append-only，不改历史行），走 `taxonomy.append()` 的原子写。

退出码：0 OK / 2 拒绝（不是 Human、目标不存在、已关闭、词表外）/ 4 读不到。
"""
from __future__ import annotations

import argparse
import datetime
import io
import json
import os
import sys

from . import status as status_mod
from . import taxonomy

HERE = os.path.dirname(os.path.abspath(__file__))
DECISIONS_PATH = os.path.join(HERE, "decisions.jsonl")

#: Human 能给出的回答（词表 `allowed_decision` 的子集）+ 缺省 reason_code
HUMAN_ANSWERS = {
    "ACCEPT_MERGE": "EVIDENCE_COMPLETE",
    "ACCEPT_INTERFACE": "EVIDENCE_COMPLETE",
    "RETURN_FIX": "MISSING_EVIDENCE",
    "BLOCK": "GATE_FAILED",
    "CANCEL": "SCOPE_CHANGE",
    "REASSIGN": "OWNERSHIP_VIOLATION",
}

HUMAN_NAMES = frozenset({"human"})


class HumanGateError(RuntimeError):
    def __init__(self, message: str, code: str = "REFUSED"):
        super().__init__(message)
        self.code = code


def _load(decisions_path: str | None = None) -> list:
    path = decisions_path or DECISIONS_PATH
    rows = []
    try:
        with io.open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError as exc:
                    raise HumanGateError("裁决历史第 %d 行不是 JSON：%s" % (lineno, exc), "UNREADABLE")
    except OSError as exc:
        raise HumanGateError("读不到裁决历史 %s：%s" % (path, exc), "UNREADABLE")
    return rows


def list_open(decisions_path: str | None = None) -> list:
    """待 Human 批项。**复用** `status.pending_human()`，不另写一套判据。"""
    rows = _load(decisions_path)
    out = []
    for row in status_mod.pending_human(rows):
        out.append({
            "id": row.get("decision_id"),
            "task_id": row.get("task_id"),
            "attempt": row.get("attempt"),
            "reason_code": row.get("reason_code"),
            "question": row.get("next_action") or row.get("message") or "",
            "opened_at": row.get("logged_at"),
        })
    return out


def _is_human(by: str) -> bool:
    return (by or "").strip().lower() in HUMAN_NAMES


def _next_decision_id(rows: list, stamp: str | None = None) -> str:
    """`D-YYYYMMDD-NNN` 续号：取该日已有最大序号 + 1。"""
    stamp = stamp or datetime.datetime.now().strftime("%Y%m%d")
    prefix = "D-%s-" % stamp
    top = 0
    for row in rows:
        did = str(row.get("decision_id") or "")
        if not did.startswith(prefix):
            continue
        tail = did[len(prefix):]
        if tail.isdigit():
            top = max(top, int(tail))
    return "%s%03d" % (prefix, top + 1)


def resolve(target_id: str, decision: str, by: str, note: str = "",
            reason_code: str | None = None, decisions_path: str | None = None,
            dry_run: bool = False, relayed_from: str = "") -> dict:
    """Human 显式回答一条待批项。返回写入的那条裁决行（`dry_run` 时只返回不写）。

    `relayed_from`：Human 在会话里**明确说了**答案，由 D0 转录落库时，把原话与时间放进来。
    转录不是代决定——两者在记录里必须分得开：`relayed_from` 为空 = Human 本人调的命令行；
    非空 = D0 转抄，原话逐字在案，谁想核对都看得见 D0 没有加料。
    """
    if not _is_human(by):
        raise HumanGateError(
            "只有 Human 能关闭待批项（收到 by=%r）。D0 与执行席都不许代关——"
            "这条闸门存在的意义就是「谁欠的答复由谁给」。" % (by,), "NOT_HUMAN")

    decision = (decision or "").strip().upper()
    if decision not in HUMAN_ANSWERS:
        raise HumanGateError("Human 的回答只能是 %s（收到 %r）"
                             % ("/".join(sorted(HUMAN_ANSWERS)), decision), "BAD_DECISION")

    rows = _load(decisions_path)
    open_rows = [dict(row, id=row.get("decision_id")) for row in status_mod.pending_human(rows)]
    target = next((row for row in open_rows if row["id"] == target_id), None)
    if target is None:
        known = {str(row.get("decision_id")) for row in rows}
        code = "ALREADY_CLOSED" if target_id in known else "NOT_FOUND"
        raise HumanGateError("待批项 %s 不在清单里（%s）——可能从未打开，或已被显式回答关闭"
                             % (target_id, code), code)

    reason = (reason_code or HUMAN_ANSWERS[decision]).strip()
    allowed_decisions, allowed_reasons = taxonomy.allowed()
    if reason not in allowed_reasons:
        raise HumanGateError("reason_code %r 不在词表里" % (reason,), "BAD_REASON")

    now = datetime.datetime.now().astimezone()
    logged_at = now.isoformat(timespec="seconds")
    record = {
        "decision_id": _next_decision_id(rows, now.strftime("%Y%m%d")),
        "task_id": target.get("task_id") or "SPEC",
        "attempt": target.get("attempt") or 1,
        "decision": decision,
        "reason_code": reason,
        "status_before": target.get("status_after") or "n/a",
        "status_after": target.get("status_after") or "n/a",
        "evidence": [
            "Human 显式回答 %s（原问题：%s）" % (target_id, (target.get("next_action") or "").strip()),
            "关闭路径 = explicit_resolve：by=%s / decision=%s / reason_code=%s / at=%s"
            % ("Human", decision, reason, logged_at),
            "不是超时关闭、不是后续无关裁决顺带关闭；本行由 coordination.human_gate 写入",
        ],
        "next_action": note.strip() or "Human 已回答，按 %s 处置" % decision,
        "resource": None,
        "human_approval_required": False,
        "resolves": [target_id],
        "by": "Human",
        "message": "Human 回答 %s：%s" % (target_id, decision),
        "logged_at": logged_at,
    }
    if relayed_from.strip():
        record["relayed_from"] = relayed_from.strip()
        record["evidence"].append(
            "D0 转录 Human 在会话里的明确指令（不是 D0 自主决定）：%s" % relayed_from.strip())
    if decision not in allowed_decisions:  # 词表自检，理论上进不来
        raise HumanGateError("decision %r 不在词表里" % (decision,), "BAD_DECISION")

    if dry_run:
        record["dry_run"] = True
        return record
    return taxonomy.append(decisions_path or DECISIONS_PATH, record)


def render(items: list) -> str:
    if not items:
        return "待 Human 批项：无"
    lines = ["待 Human 批项（%d）：" % len(items)]
    for item in items:
        question = (item["question"] or "").replace("\n", " ")
        if len(question) > 90:
            question = question[:90] + "…"
        lines.append("  %s  %-5s  %-32s %s" % (item["id"], item["task_id"] or "-",
                                              item["reason_code"] or "-", question))
    return "\n".join(lines)


def main(argv=None) -> int:
    from .cli import ensure_utf8_stdio
    ensure_utf8_stdio()
    ap = argparse.ArgumentParser(prog="coordination.human_gate",
                                 description="受控 Human gate：待批项清单 / 显式回答")
    ap.add_argument("--decisions", default=DECISIONS_PATH)
    sub = ap.add_subparsers(dest="cmd")

    p_list = sub.add_parser("list", help="列出待 Human 批项")
    p_list.add_argument("--json", action="store_true")

    p_res = sub.add_parser("resolve", help="Human 显式回答一条待批项")
    p_res.add_argument("--id", required=True, dest="target_id")
    p_res.add_argument("--decision", required=True)
    p_res.add_argument("--by", required=True, help="必须是 Human")
    p_res.add_argument("--note", default="")
    p_res.add_argument("--reason-code", default=None)
    p_res.add_argument("--dry-run", action="store_true")

    args = ap.parse_args(argv)
    try:
        if args.cmd == "resolve":
            record = resolve(args.target_id, args.decision, args.by, note=args.note,
                             reason_code=args.reason_code, decisions_path=args.decisions,
                             dry_run=args.dry_run)
            print(json.dumps(record, ensure_ascii=False, indent=2))
            print("%s %s ← %s" % ("DRY-RUN" if args.dry_run else "已写入",
                                  record["decision_id"], args.target_id), file=sys.stderr)
            return 0
        items = list_open(args.decisions)
        if getattr(args, "json", False):
            print(json.dumps(items, ensure_ascii=False, indent=2))
        else:
            print(render(items))
        return 0
    except HumanGateError as exc:
        print("REFUSED [%s] %s" % (exc.code, exc), file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
