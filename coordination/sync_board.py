"""阶段 B：把 SQLite board 灌成与 `task_status.json` 一致（`python -m coordination.sync_board`）。

设计要点（`14_D0架构优化执行令.md` §3 阶段 B）：

1. 9 个任务来自 `coordination/task_status.json`；board 是**唯一状态事实源**，本命令负责灌库。
2. 状态映射固定（§2.3），不许自创：PASS→completed、PARTIAL/BLOCKED/NOT_STARTED→blocked。
3. `legacy_status` / `state_reason` 两列用兼容迁移加（缺列才 ALTER），原 `reason` 完整保留。
4. `RULING / CORRECTION / SPEC_CHANGE / DEFECT_CLASS` **不是**状态变更裁决（§3 B.5）。
5. PASS 任务：最后一条 ACCEPT 裁决的证据里能找到真提交才算 merge；找不到写
   `state_reason=PASS_WITHOUT_MERGE_COMMIT` 并记事件，**不伪造 commit**。
6. 幂等：第二次运行不新增重复事件（事件按 (type, task_id, payload) 去重）。

注意：**不要用 `Board.add_artifact()`**——它顺手把任务写成 `completed`，会把 blocked 任务洗白。
产物登记走本文件的 `_record_artifact()`（只写 artifacts 表）。
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess

from . import board as board_mod
from . import paths as paths_mod
from . import status as status_mod

# 状态变更类裁决：只有这些能把任务推进/退回，其余一律不参与状态迁移。
STATE_DECISIONS = frozenset({
    "ACCEPT_MERGE", "ACCEPT", "ACCEPT_EVIDENCE", "ACCEPT_RECORD", "ACCEPT_INTERFACE",
    "ACCEPT_PARTIAL", "ACCEPT_CORRECTION", "CONDITIONAL_ACCEPT",
    "ACCEPT_CODE_RETURN_EVIDENCE", "ACCEPT_CONTENT_RETURN_RECORD",
    "RETURN_FIX", "RETRACTION", "CANCEL", "REASSIGN", "BLOCK",
})
# 明确「不是」状态变更的（写在这里是为了让下一个人不必重新推断）：
NON_STATE_DECISIONS = frozenset({
    "RULING", "CORRECTION", "SPEC_CHANGE", "DEFECT_CLASS", "DEFECT", "FINDING_ACCEPTED",
    "DISPATCH", "INSTRUCTION", "APPROVE", "APPROVE_PLAN", "PENDING_HUMAN", "NEEDS_HUMAN",
})

STATUS_MAP = {
    "PASS": "completed",
    "PARTIAL": "blocked",
    "BLOCKED": "blocked",
    "NOT_STARTED": "blocked",
}

MODULE_LANE = {"M00": "P0", "M01": "A1", "M02": "A1", "M03": "A2", "M04": "A2",
               "M05": "A3", "M06": "A3", "M07": "A4", "M08": "A4"}

HEX_RE = re.compile(r"\b([0-9a-f]{7,40})\b")
PATH_RE = re.compile(r"\b((?:reports|out)/[A-Za-z0-9_./\u4e00-\u9fff-]+)")


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _columns(b) -> set:
    return {row["name"] for row in b.db.execute("PRAGMA table_info(tasks)")}


def _migrate(b) -> list:
    """兼容迁移：只加缺的列，不动已有的。"""
    cols = _columns(b)
    added = []
    for name, decl in (("legacy_status", "TEXT"), ("state_reason", "TEXT")):
        if name not in cols:
            with b.tx() as c:
                c.execute("ALTER TABLE tasks ADD COLUMN %s %s" % (name, decl))
            added.append(name)
    return added


def state_change_decisions(decisions: list, task_id: str) -> list:
    return [r for r in decisions
            if r.get("task_id") == task_id and r.get("decision") in STATE_DECISIONS]


def find_merge_commit(rows: list, repo: str | None) -> str:
    """在状态变更裁决的证据里找**真提交**；找不到返回空串，不猜。"""
    for row in reversed(rows):
        blob = json.dumps(row, ensure_ascii=False)
        for token in HEX_RE.findall(blob):
            try:
                rc = subprocess.run(["git", "-C", repo or ".", "cat-file", "-e", token + "^{commit}"],
                                    capture_output=True)
            except OSError:
                return ""
            if rc.returncode == 0:
                return token
    return ""


def existing_event(b, kind: str, task_id: str, payload: dict) -> bool:
    want = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for row in b.db.execute("SELECT type, task_id, payload_json FROM events"):
        if row["type"] == kind and row["task_id"] == task_id and (row["payload_json"] or "") == want:
            return True
    return False


def record_event(b, kind: str, task_id: str, payload: dict) -> bool:
    """幂等写事件：已经一模一样的事件就不重复写。"""
    if existing_event(b, kind, task_id, payload):
        return False
    with b.tx() as c:
        b.event(c, kind, task_id, payload)
    return True


def _record_artifact(b, task_id: str, path: str, sha: str) -> None:
    with b.tx() as c:
        c.execute("""INSERT OR REPLACE INTO artifacts(artifact_id, task_id, path, sha256,
                                                      version, acceptance, created_at)
                     VALUES(?,?,?,?,?,?,?)""",
                  ("%s:%s" % (task_id, path), task_id, path, sha, "1", "recorded", _now()))


def task_artifacts(rows: list, root: str) -> list:
    seen = []
    for row in rows:
        blob = json.dumps(row, ensure_ascii=False)
        for rel in PATH_RE.findall(blob):
            rel = rel.rstrip(".,;)）")
            if rel not in seen:
                seen.append(rel)
    out = []
    for rel in seen[:50]:
        p = os.path.join(root, rel.replace("/", os.sep))
        if os.path.isfile(p):
            data = open(p, "rb").read()
            out.append({"path": rel, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    return out


def sync(status_path: str, decisions_path: str, board_path: str, repo: str | None = None,
         dry_run: bool = False) -> dict:
    doc = status_mod.load_status(status_path)
    decisions = status_mod.load_decisions(decisions_path)
    root = os.path.dirname(os.path.dirname(os.path.abspath(status_path)))
    b = board_mod.Board(board_path)
    b.init()
    added_cols = _migrate(b)

    rows_out = []
    events = {"merge_commit": 0, "pass_without_merge": 0, "deps": 0, "deps_unknown": 0,
              "created": 0, "updated": 0, "missing_state_decision": 0}
    for task_id, entry in sorted(doc["tasks"].items()):
        legacy = entry["status"]
        target = STATUS_MAP[legacy]
        state_rows = state_change_decisions(decisions, task_id)
        base_commit = ""
        state_reason = entry.get("reason") or ""
        if legacy == "PASS":
            base_commit = find_merge_commit(state_rows, repo)
            if base_commit:
                events["merge_commit"] += 1
            else:
                state_reason = "PASS_WITHOUT_MERGE_COMMIT"
                events["pass_without_merge"] += 1

        lane = MODULE_LANE.get(task_id, "A1")
        exists = b.db.execute("SELECT task_id FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not dry_run:
            if exists:
                with b.tx() as c:
                    c.execute(
                        "UPDATE tasks SET module=?, lane=?, status=?, legacy_status=?, "
                        "state_reason=?, base_commit=COALESCE(NULLIF(?,''), base_commit), "
                        "updated_at=? WHERE task_id=?",
                        (task_id, lane, target, legacy, state_reason, base_commit, _now(), task_id))
                events["updated"] += 1
            else:
                b.add_task(task_id, task_id, lane, status=target,
                           resource="blender" if lane in ("A4", "P0") else "none",
                           base_commit=base_commit)
                with b.tx() as c:
                    c.execute("UPDATE tasks SET legacy_status=?, state_reason=? WHERE task_id=?",
                              (legacy, state_reason, task_id))
                events["created"] += 1
        else:
            events["updated" if exists else "created"] += 1

        rows_out.append({"task_id": task_id, "legacy": legacy, "board": target,
                         "last_state_decision": state_rows[-1]["decision_id"] if state_rows else None,
                         "last_state_kind": state_rows[-1]["decision"] if state_rows else None})
        if not state_rows and legacy != "NOT_STARTED":
            events["missing_state_decision"] += 1
            if not dry_run:
                record_event(b, "sync.state_decision_missing", task_id,
                             {"legacy": legacy, "why": "非 NOT_STARTED 任务没有可识别的状态变更裁决"})

        arts = task_artifacts(state_rows, root)
        if arts:
            events["deps"] += 1
            if not dry_run:
                for art in arts:
                    _record_artifact(b, task_id, art["path"], art["sha256"])
        else:
            events["deps_unknown"] += 1
            if not dry_run:
                record_event(b, "sync.deps_unknown", task_id,
                             {"why": "裁决证据里没有可确定的 artifact 路径（不猜）"})

        if base_commit and not dry_run:
            record_event(b, "sync.merge_commit", task_id, {"commit": base_commit})
        if legacy == "PASS" and not base_commit and not dry_run:
            record_event(b, "sync.pass_without_merge_commit", task_id, {"state_reason": state_reason})

    counts = {
        "tasks": b.db.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"],
        "completed": b.db.execute("SELECT COUNT(*) c FROM tasks WHERE status='completed'").fetchone()["c"],
        "blocked": b.db.execute("SELECT COUNT(*) c FROM tasks WHERE status='blocked'").fetchone()["c"],
        "artifacts": b.db.execute("SELECT COUNT(*) c FROM artifacts").fetchone()["c"],
        "events": b.db.execute("SELECT COUNT(*) c FROM events").fetchone()["c"],
    }
    b.close()
    return {"state": "PHASE_B_OK", "board_path": os.path.abspath(board_path),
            "migrated_columns": added_cols, "dry_run": dry_run,
            "counts": counts, "events": events, "tasks": rows_out}


def main(argv=None) -> int:
    from .cli import ensure_utf8_stdio
    ensure_utf8_stdio()
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(prog="coordination.sync_board")
    ap.add_argument("--status", default=os.path.join(here, "task_status.json"))
    ap.add_argument("--decisions", default=os.path.join(here, "decisions.jsonl"))
    ap.add_argument("--board", default=None)
    ap.add_argument("--repo", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    payload = sync(args.status, args.decisions, args.board or paths_mod.board_path(),
                   repo=args.repo, dry_run=args.dry_run)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
