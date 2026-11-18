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


def _file_sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def load_task_graph(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    deps = doc.get("dependencies") or {}
    resources = doc.get("resources") or {}
    if not isinstance(deps, dict) or not isinstance(resources, dict):
        raise ValueError("task_graph.json 的 dependencies/resources 必须是对象")
    for task_id, rows in deps.items():
        if not isinstance(rows, list):
            raise ValueError("task_graph.dependencies[%s] 必须是数组" % task_id)
        for row in rows:
            if not isinstance(row, dict) or not row.get("task"):
                raise ValueError("依赖行必须含 task：%r" % (row,))
    return {"dependencies": deps, "resources": resources}


def _ensure_bootstrap_table(b) -> None:
    b.db.execute("""CREATE TABLE IF NOT EXISTS sync_bootstrap(
        id INTEGER PRIMARY KEY CHECK(id=1),
        status_sha256 TEXT NOT NULL,
        decisions_sha256 TEXT NOT NULL,
        synced_at TEXT NOT NULL
    )""")


def bootstrap_done(b) -> bool:
    _ensure_bootstrap_table(b)
    return b.db.execute("SELECT 1 FROM sync_bootstrap WHERE id=1").fetchone() is not None


def record_bootstrap(b, status_path: str, decisions_path: str) -> None:
    _ensure_bootstrap_table(b)
    with b.tx() as c:
        c.execute("INSERT OR REPLACE INTO sync_bootstrap(id, status_sha256, decisions_sha256, synced_at) "
                  "VALUES(1,?,?,?)",
                  (_file_sha256(status_path), _file_sha256(decisions_path), _now()))


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
    """bootstrap 只补缺失记录；同 ID 不同历史记录不覆盖，只留冲突事件。"""
    artifact_id = "%s:%s" % (task_id, path)
    row = b.db.execute("SELECT path, sha256 FROM artifacts WHERE artifact_id=?",
                       (artifact_id,)).fetchone()
    if row is not None:
        if row["path"] == path and row["sha256"] == sha:
            return
        record_event(b, "sync.artifact_conflict", task_id,
                     {"artifact_id": artifact_id, "kept_path": row["path"],
                      "kept_sha256": row["sha256"], "ignored_sha256": sha,
                      "why": "bootstrap 不覆盖既有历史记录"})
        return
    with b.tx() as c:
        b._put_artifact(c, artifact_id, task_id, path, sha, "1", "recorded")


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
         dry_run: bool = False, mode: str = "check", graph_path: str | None = None,
         allow_resync: bool = False) -> dict:
    """同步状态视图到 board。

    `check`/`verify` 只读；`bootstrap` 唯一一次完成灌库、迁移、资源映射和依赖图。
    之后只能 check/verify；再次发生 bootstrap 必须 `allow_resync`（灾难恢复）。
    """
    if mode not in ("bootstrap", "verify", "check"):
        raise ValueError("mode 只能是 bootstrap/verify/check")
    if dry_run:
        mode = "verify"

    doc = status_mod.load_status(status_path)
    decisions = status_mod.load_decisions(decisions_path)
    root = os.path.dirname(os.path.dirname(os.path.abspath(status_path)))
    graph_file = graph_path or os.path.join(root, "coordination", "task_graph.json")
    graph = load_task_graph(graph_file)

    board_file = board_path or paths_mod.board_path()
    mutate = mode == "bootstrap"
    b = board_mod.Board(board_file, readonly=not mutate)
    added_cols = []
    unlocked = []
    conflicts = []
    if mutate:
        if bootstrap_done(b) and not allow_resync:
            b.close()
            raise board_mod.BoardError(
                "BOOTSTRAP_ALREADY_DONE：board 已 bootstrap；只允许 check/verify，"
                "只有 Human 灾后恢复才可 --allow-resync", "SNAPSHOT_INVALID")
        b.init()
        added_cols = _migrate(b)

    rows_out = []
    events = {"merge_commit": 0, "pass_without_merge": 0, "deps": 0, "deps_unknown": 0,
              "created": 0, "updated": 0, "missing_state_decision": 0, "artifact_conflict": 0}
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
        resource = graph["resources"].get(task_id, "none")
        exists = b.db.execute("SELECT task_id, status, resource FROM tasks WHERE task_id=?",
                              (task_id,)).fetchone()
        if mutate:
            if exists:
                with b.tx() as c:
                    c.execute(
                        "UPDATE tasks SET module=?, lane=?, status=?, legacy_status=?, "
                        "state_reason=?, resource=?, "
                        "base_commit=COALESCE(NULLIF(?,''), base_commit), updated_at=? "
                        "WHERE task_id=?",
                        (task_id, lane, target, legacy, state_reason, resource,
                         base_commit, _now(), task_id))
                events["updated"] += 1
            else:
                b.add_task(task_id, task_id, lane, status=target, resource=resource,
                           base_commit=base_commit)
                with b.tx() as c:
                    c.execute("UPDATE tasks SET legacy_status=?, state_reason=? WHERE task_id=?",
                              (legacy, state_reason, task_id))
                events["created"] += 1
        else:
            events["updated" if exists else "created"] += 1
            if exists is None:
                conflicts.append({"code": "tasks", "task_id": task_id, "board": "missing"})
            elif (exists["resource"] or "none") != resource:
                conflicts.append({"code": "resource", "task_id": task_id,
                                  "board": exists["resource"] or "none", "graph": resource})

        rows_out.append({"task_id": task_id, "legacy": legacy,
                         "board": target if mutate else (exists["status"] if exists else "missing"),
                         "sync_target": target,
                         "resource": (resource if mutate or not exists else exists["resource"]),
                         "graph_resource": resource,
                         "last_state_decision": state_rows[-1]["decision_id"] if state_rows else None,
                         "last_state_kind": state_rows[-1]["decision"] if state_rows else None})
        if not state_rows and legacy != "NOT_STARTED":
            events["missing_state_decision"] += 1
            if mutate:
                record_event(b, "sync.state_decision_missing", task_id,
                             {"legacy": legacy, "why": "非 NOT_STARTED 任务没有可识别的状态变更裁决"})

        arts = task_artifacts(state_rows, root)
        if arts:
            events["deps"] += 1
            if mutate:
                for art in arts:
                    _record_artifact(b, task_id, art["path"], art["sha256"])
        else:
            events["deps_unknown"] += 1
            if mutate:
                record_event(b, "sync.deps_unknown", task_id,
                             {"why": "裁决证据里没有可确定的 artifact 路径（不猜）"})

        if base_commit and mutate:
            record_event(b, "sync.merge_commit", task_id, {"commit": base_commit})
        if legacy == "PASS" and not base_commit and mutate:
            record_event(b, "sync.pass_without_merge_commit", task_id, {"state_reason": state_reason})

    if mutate:
        for task_id, deps in sorted(graph["dependencies"].items()):
            if task_id not in doc["tasks"]:
                continue
            for dep in deps:
                with b.tx() as c:
                    c.execute("""INSERT OR REPLACE INTO deps(task_id, depends_on, artifact,
                                                             version, required_sha)
                                 VALUES(?,?,?,?,?)""",
                              (task_id, dep["task"], dep.get("artifact", ""),
                               dep.get("version", ""), dep.get("required_sha", "")))
        unlocked = b.recompute_deps()
        record_bootstrap(b, status_path, decisions_path)
        record_event(b, "sync.bootstrap_completed", None,
                     {"status_sha256": _file_sha256(status_path),
                      "decisions_sha256": _file_sha256(decisions_path)})
    else:
        # check/verify 必须对真实图对账，不能只打印“若灌库会得到什么”。
        # 运行态 ready/running 与 legacy PARTIAL 可以合理不同，不在此强判状态相等。
        for task_id in sorted(doc["tasks"]):
            expected = sorted(
                (dep["task"], dep.get("artifact") or "", dep.get("version") or "",
                 dep.get("required_sha") or "")
                for dep in graph["dependencies"].get(task_id, []))
            actual = sorted(
                (row["depends_on"], row["artifact"] or "", row["version"] or "",
                 row["required_sha"] or "")
                for row in b.db.execute(
                    "SELECT depends_on, artifact, version, required_sha FROM deps WHERE task_id=?",
                    (task_id,)))
            if actual != expected:
                missing = [list(row) for row in expected if row not in actual]
                extra = [list(row) for row in actual if row not in expected]
                conflicts.append({"code": "deps", "task_id": task_id,
                                  "missing": missing, "extra": extra})

    counts = {
        "tasks": b.db.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"],
        "completed": b.db.execute("SELECT COUNT(*) c FROM tasks WHERE status='completed'").fetchone()["c"],
        "blocked": b.db.execute("SELECT COUNT(*) c FROM tasks WHERE status='blocked'").fetchone()["c"],
        "ready": b.db.execute("SELECT COUNT(*) c FROM tasks WHERE status='ready'").fetchone()["c"],
        "artifacts": b.db.execute("SELECT COUNT(*) c FROM artifacts").fetchone()["c"],
        "events": b.db.execute("SELECT COUNT(*) c FROM events").fetchone()["c"],
    }
    b.close()
    state = "PHASE_B_OK" if mutate else (
        "PHASE_B_CHECK_CONFLICT" if conflicts else "PHASE_B_CHECK_OK")
    return {"state": state,
            "mode": mode, "board_path": os.path.abspath(board_file),
            "graph": os.path.abspath(graph_file),
            "migrated_columns": added_cols, "dry_run": not mutate,
            "unlocked": unlocked, "conflicts": conflicts,
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
    ap.add_argument("--graph", default=None,
                    help="任务图配置（默认 coordination/task_graph.json）")
    ap.add_argument("--mode", choices=("bootstrap", "verify", "check"), default="check",
                    help="check/verify 只读；bootstrap 是唯一灌库入口")
    ap.add_argument("--allow-resync", action="store_true",
                    help="Human 灾后恢复：允许再次 bootstrap（普通调用不许）")
    ap.add_argument("--dry-run", action="store_true", help="兼容旧调用，等价 --mode verify")
    args = ap.parse_args(argv)
    try:
        payload = sync(args.status, args.decisions, args.board or paths_mod.board_path(),
                       repo=args.repo, dry_run=args.dry_run, mode=args.mode,
                       graph_path=args.graph, allow_resync=args.allow_resync)
    except (board_mod.BoardError, ValueError, status_mod.Unreadable) as exc:
        print(json.dumps({"state": "REJECTED", "reason_code": getattr(exc, "reason_code", "SYNC_INVALID"),
                          "why": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 3
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 3 if payload.get("state") == "PHASE_B_CHECK_CONFLICT" else 0


if __name__ == "__main__":
    raise SystemExit(main())
