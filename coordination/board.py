"""任务板（SQLite）：唯一事实源，所有状态迁移都在事务里完成。

依据 `13_自动调度与分流器规范.md` §3 状态机、§4 三类令牌、§5 验证上限、§6 表结构。

三条硬规则，写死在实现里：
1. **状态只能经动作迁移**（claim / start / submit / decide / merge / reap）。
   没有 `set_status('completed')` 这种口子；Agent 直写终态会被拒并记 W3（13 §6.1）。
2. **同一时刻只有一个令牌处于 active**：submission / verify / merge 各一个。
3. **计数落库**：验证轮数、打回次数、claim 次数都在行里，不靠对话记忆（13 §5）。
"""
from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from . import evidence as evidence_mod
from . import gates as gates_mod
from . import gate as gate_mod
from . import paths as paths_mod

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY,
  module TEXT NOT NULL,
  lane TEXT NOT NULL,
  status TEXT NOT NULL,
  owner TEXT,
  claim_count INTEGER DEFAULT 0,
  attempt INTEGER DEFAULT 0,
  verification_rounds INTEGER DEFAULT 0,
  return_count INTEGER DEFAULT 0,
  lease_until TEXT,
  base_commit TEXT,
  branch TEXT,
  resource TEXT DEFAULT 'none',
  acceptance_ref TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deps (
  task_id TEXT,
  depends_on TEXT,
  artifact TEXT,
  version TEXT,
  required_sha TEXT,
  PRIMARY KEY(task_id, depends_on, artifact)
);

CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id TEXT PRIMARY KEY,
  task_id TEXT,
  path TEXT,
  sha256 TEXT,
  version TEXT,
  acceptance TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS submission_queue (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  evidence_hash TEXT NOT NULL,
  state TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(task_id, evidence_hash)
);

CREATE TABLE IF NOT EXISTS verifications (
  verification_id TEXT PRIMARY KEY,
  task_id TEXT,
  round INTEGER,
  evidence_hash TEXT,
  decision TEXT,
  reason_code TEXT,
  decided_at TEXT,
  UNIQUE(task_id, round),
  UNIQUE(task_id, evidence_hash)
);

CREATE TABLE IF NOT EXISTS merge_queue (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT UNIQUE,
  state TEXT NOT NULL,
  merge_commit TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS resources (
  resource TEXT PRIMARY KEY,
  holder TEXT,
  lease_until TEXT,
  task_id TEXT
);

CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  type TEXT NOT NULL,
  task_id TEXT,
  payload_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_lane_status ON tasks(lane, status);
CREATE INDEX IF NOT EXISTS idx_submission_state ON submission_queue(state);
CREATE INDEX IF NOT EXISTS idx_merge_state ON merge_queue(state);
"""

# 允许 Agent 走到、且只能经动作迁移的状态；终态只能由 scheduler 在合并/验收后写。
AGENT_FORBIDDEN_STATUS = ("completed", "merged", "verified")
QUEUE_LIMIT = 2          # 13 §4.1：queued_submission 最多 2 条，形成背压
MAX_CLAIMS = 3           # 13 §5：claim 上限 3 次
MAX_ROUNDS = 2           # 13 §5：验证轮数上限 2


class BoardError(Exception):
    """状态机拒绝：调用方不得绕过。`reason_code` 直接进回执。"""

    def __init__(self, message, reason_code="INVALID_STATE"):
        super().__init__(message)
        self.reason_code = reason_code


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


class Board:
    def __init__(self, path: str | None = None, clock=None, readonly: bool = False):
        """打开任务板。

        `readonly=True` 给 dispatcher/status 这类视图用：绝不创建目录、绝不建库、
        绝不改 schema。缺库时 sqlite 直接报不可读，而不是悄悄造一个空世界。
        """
        self.path = os.path.abspath(path or paths_mod.board_path())
        self.readonly = bool(readonly)
        if not self.readonly:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        if self.readonly:
            uri = "file:%s?mode=ro" % self.path.replace("\\", "/")
            self.db = sqlite3.connect(uri, uri=True, timeout=5.0,
                                      isolation_level=None, check_same_thread=False)
        else:
            self.db = sqlite3.connect(self.path, timeout=5.0, isolation_level=None,
                                      check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        if not self.readonly:
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=5000")

    # ---------- 基础 ----------

    def close(self):
        self.db.close()

    def now(self) -> datetime:
        return self._clock()

    @contextlib.contextmanager
    def tx(self):
        """单事务：BEGIN IMMEDIATE 保证"读+条件写"不被别人插进来。"""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        else:
            self.db.execute("COMMIT")

    def init(self):
        if self.readonly:
            raise BoardError("只读连接不能 init/migrate", "BOARD_READONLY")
        self.db.executescript(SCHEMA)
        with self.tx() as c:
            for resource in ("blender", "gpu", "merge"):
                c.execute("INSERT OR IGNORE INTO resources(resource) VALUES(?)", (resource,))

    def event(self, c, kind, task_id, payload=None):
        c.execute("INSERT INTO events(ts, type, task_id, payload_json) VALUES(?,?,?,?)",
                  (_iso(self.now()), kind, task_id,
                   json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)))

    def events(self) -> list:
        return [dict(r) for r in self.db.execute(
            "SELECT seq, ts, type, task_id, payload_json FROM events ORDER BY seq")]

    # ---------- 运行身份 ----------

    def new_run_id(self, task_id) -> str:
        """生成候选运行号但不写库；preflight 通过后再由 issue_run_id 登记。"""
        import uuid
        now = self.now()
        return "%s_%s_%s" % (
            now.strftime("%Y%m%dT%H%M%S"), task_id.lower(), uuid.uuid4().hex[:8])

    def issue_run_id(self, task_id, run_id=None) -> str:
        """登记一次真实执行的唯一运行号，并把身份写进 append-only events。"""
        run_id = run_id or self.new_run_id(task_id)
        with self.tx() as c:
            self.event(c, "RUN_ISSUED", task_id, {"run_id": run_id})
        return run_id

    # ---------- 建图（测试与 dispatcher 用） ----------

    def add_task(self, task_id, module, lane, status="blocked", resource="none",
                 base_commit="", branch=""):
        with self.tx() as c:
            c.execute("""INSERT INTO tasks(task_id, module, lane, status, resource,
                                           base_commit, branch, updated_at)
                         VALUES(?,?,?,?,?,?,?,?)""",
                      (task_id, module, lane, status, resource, base_commit, branch,
                       _iso(self.now())))
        return self.task(task_id)

    def add_dep(self, task_id, depends_on, artifact, version="", required_sha=""):
        with self.tx() as c:
            c.execute("""INSERT OR REPLACE INTO deps(task_id, depends_on, artifact, version, required_sha)
                         VALUES(?,?,?,?,?)""", (task_id, depends_on, artifact, version, required_sha))

    def _put_artifact(self, c, artifact_id, task_id, path, sha256,
                      version="", acceptance="accepted") -> bool:
        """登记不可变 artifact。同 ID 同字节幂等；同 ID 不同字节拒绝。"""
        row = c.execute("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
        if row is not None:
            same = (row["task_id"] == task_id and row["path"] == path
                    and row["sha256"] == sha256 and row["version"] == version
                    and row["acceptance"] == acceptance)
            if same:
                return False
            raise BoardError(
                "artifact_id %s 已登记为 %s@%s，拒绝替换成 %s@%s"
                % (artifact_id, row["path"], (row["sha256"] or "")[:16],
                   path, (sha256 or "")[:16]),
                "SNAPSHOT_INVALID")
        c.execute("""INSERT INTO artifacts(artifact_id, task_id, path, sha256,
                                           version, acceptance, created_at)
                     VALUES(?,?,?,?,?,?,?)""",
                  (artifact_id, task_id, path, sha256, version, acceptance, _iso(self.now())))
        return True

    def add_artifact(self, artifact_id, task_id, path, sha256, version="", acceptance="accepted"):
        """登记一份已验收产物，并把产出它的任务标 completed（等价于一次已完成的合并）。"""
        with self.tx() as c:
            self._put_artifact(c, artifact_id, task_id, path, sha256, version, acceptance)
            c.execute("UPDATE tasks SET status='completed', updated_at=? WHERE task_id=?",
                      (_iso(self.now()), task_id))

    def task(self, task_id) -> dict:
        row = self.db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        return dict(row) if row else {}

    # ---------- 查询 ----------

    def active_task_of(self, agent) -> dict:
        row = self.db.execute(
            """SELECT * FROM tasks WHERE owner=? AND status IN ('claimed','running','queued_submission')
               ORDER BY updated_at LIMIT 1""", (agent,)).fetchone()
        return dict(row) if row else {}

    def queued_count(self) -> int:
        return self.db.execute(
            "SELECT COUNT(*) FROM submission_queue WHERE state='queued'").fetchone()[0]

    def pending_count(self) -> int:
        """在飞提交数（active + queued）。背压按这个算：active 也是一份"待裁决"的工作。

        13 §4.1 说的是"最多 2 条 queued"，但真正的意图是**不让四个人同时堆未裁决的提交**；
        只数 queued 会放过 1 active + 1 queued + 1 新的 = 3 份在飞。所以统一按 pending 计。
        """
        return self.db.execute(
            "SELECT COUNT(*) FROM submission_queue WHERE state IN ('queued','active')").fetchone()[0]

    def active_submission(self) -> dict:
        row = self.db.execute(
            "SELECT * FROM submission_queue WHERE state='active' ORDER BY seq LIMIT 1").fetchone()
        return dict(row) if row else {}

    def _resource_free(self, c, resource, now) -> bool:
        if resource in (None, "", "none"):
            return True
        row = c.execute("SELECT holder, lease_until FROM resources WHERE resource=?", (resource,)).fetchone()
        if row is None:
            return True
        if not row["holder"]:
            return True
        return row["lease_until"] is not None and row["lease_until"] < _iso(now)

    def _hold_resource(self, c, resource, agent, task_id, until):
        if resource in (None, "", "none"):
            return
        c.execute("UPDATE resources SET holder=?, lease_until=?, task_id=? WHERE resource=?",
                  (agent, until, task_id, resource))

    def _release_resource(self, c, task_id):
        c.execute("UPDATE resources SET holder=NULL, lease_until=NULL, task_id=NULL WHERE task_id=?",
                  (task_id,))

    def _deps_ok(self, c, task_id) -> bool:
        rows = c.execute("SELECT * FROM deps WHERE task_id=?", (task_id,)).fetchall()
        for dep in rows:
            done = c.execute("SELECT status FROM tasks WHERE task_id=?",
                             (dep["depends_on"],)).fetchone()
            if done is None or done["status"] != "completed":
                return False
            # artifact 为空表示只依赖上游任务完成；给了路径就必须找到对应产物。
            if not dep["artifact"]:
                continue
            got = c.execute(
                """SELECT a.sha256 FROM artifacts a JOIN tasks t ON t.task_id=a.task_id
                   WHERE a.task_id=? AND a.path=? AND t.status='completed'""",
                (dep["depends_on"], dep["artifact"])).fetchone()
            if got is None:
                return False
            if dep["required_sha"] and got["sha256"] != dep["required_sha"]:
                return False
        return True

    def unlocks(self, task_id) -> int:
        return self.db.execute(
            "SELECT COUNT(DISTINCT t.task_id) FROM deps d JOIN tasks t ON t.task_id=d.task_id "
            "WHERE d.depends_on=? AND t.status='blocked'", (task_id,)).fetchone()[0]

    def _pick_ready(self, c, lane, now, modules=None) -> dict:
        # returned 是「修完后可再次认领」，不是终态；否则一次 RETURN_FIX 会让任务永远卡住。
        rows = c.execute(
            "SELECT * FROM tasks WHERE lane=? AND status IN ('ready','returned')", (lane,)).fetchall()
        cand = []
        for row in rows:
            if modules is not None and row["module"] not in modules:
                continue
            if not self._deps_ok(c, row["task_id"]):
                continue
            if not self._resource_free(c, row["resource"], now):
                continue
            cand.append(dict(row))
        if not cand:
            return {}
        cand.sort(key=lambda r: (-self.unlocks(r["task_id"]), r["task_id"]))
        return cand[0]

    # ---------- 动作：认领 ----------

    def claim(self, lane, agent, lease_seconds=900, modules=None):
        """原子认领一个 ready 任务。拿不到返回 None（不是异常：IDLE 是正常结果）。"""
        now = self.now()
        with self.tx() as c:
            if self.active_task_of(agent):
                self.event(c, "CLAIM_REFUSED", None, {"agent": agent, "why": "agent_busy"})
                return None
            if self.pending_count() >= QUEUE_LIMIT:
                self.event(c, "CLAIM_REFUSED", None, {"agent": agent, "why": "backpressure"})
                return None
            pick = self._pick_ready(c, lane, now, modules)
            if not pick:
                return None
            until = _iso(now + timedelta(seconds=lease_seconds))
            cur = c.execute(
                """UPDATE tasks SET status='claimed', owner=?, claim_count=claim_count+1,
                                    attempt=attempt+1, lease_until=?, updated_at=?
                   WHERE task_id=? AND status IN ('ready','returned')""",
                (agent, until, _iso(now), pick["task_id"]))
            if cur.rowcount != 1:
                return None
            self._hold_resource(c, pick["resource"], agent, pick["task_id"], until)
            self.event(c, "CLAIM", pick["task_id"], {"agent": agent, "attempt": pick["attempt"] + 1})
        return self.task(pick["task_id"])

    def start(self, task_id, lease_seconds=900):
        now = self.now()
        with self.tx() as c:
            cur = c.execute(
                "UPDATE tasks SET status='running', lease_until=?, updated_at=? "
                "WHERE task_id=? AND status IN ('claimed','returned','running')",
                (_iso(now + timedelta(seconds=lease_seconds)), _iso(now), task_id))
            if cur.rowcount != 1:
                raise BoardError("任务 %s 不能开始（当前 %s）"
                                 % (task_id, self.task(task_id).get("status")))
            self.event(c, "START", task_id)
        return self.task(task_id)

    def heartbeat(self, task_id, lease_seconds=900):
        now = self.now()
        until = _iso(now + timedelta(seconds=lease_seconds))
        with self.tx() as c:
            cur = c.execute(
                "UPDATE tasks SET lease_until=?, updated_at=? WHERE task_id=? AND status IN ('claimed','running')",
                (until, _iso(now), task_id))
            if cur.rowcount != 1:
                raise BoardError("任务 %s 不在租约内" % task_id)
            # 任务与资源是同一份租约的两张视图；只续任务会让长跑中的资源被再次派工。
            c.execute("UPDATE resources SET lease_until=? WHERE task_id=?", (until, task_id))

    def fail_run(self, task_id, run_id, rc, why=""):
        """一次生产命令失败：留痕、释放资源并 fail-closed 到 blocked。"""
        now = self.now()
        with self.tx() as c:
            task = c.execute("SELECT status FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if task is None or task["status"] not in ("claimed", "running"):
                raise BoardError("任务 %s 当前不在执行态，不能登记运行失败" % task_id,
                                 "OWNERSHIP_VIOLATION")
            c.execute("UPDATE tasks SET status='blocked', owner=NULL, lease_until=NULL, updated_at=? "
                      "WHERE task_id=?", (_iso(now), task_id))
            self._release_resource(c, task_id)
            self.event(c, "RUN_FAILED", task_id,
                       {"run_id": run_id, "rc": int(rc), "why": why or "command_failed"})
        return self.task(task_id)

    # ---------- 动作：提交 ----------

    def submit(self, task_id, payload, base=None, head="HEAD", repo=None, gate=None):
        """收一份证据。返回 {state, token, evidence_hash, reason}。

        * 证据不合规（含 NaN）→ EvidenceError（不落库）
        * `base` 给定时（或任务行里记着 base_commit）→ 先过格式闸门：
          `files[]` 必须覆盖 `git diff base..head` 的每个文件，缺即 MISSING_EVIDENCE
          （D-20261116-022：增量冒充覆盖面的入口在这里堵死）
        * 队列已满 2 → BACKPRESSURE，任务保持 running
        * 同一 task 同一 hash → DUPLICATE，不排队
        """
        normalized = evidence_mod.validate(payload)
        digest = evidence_mod.digest(normalized)

        # 先跑便宜检查，再做可能很贵的闸门/覆盖检查。事务内仍会原子复核一次。
        cheap_task = self.task(task_id)
        if not cheap_task:
            raise BoardError("没有任务 %s" % task_id)
        if cheap_task["status"] not in ("running", "claimed"):
            raise BoardError("任务 %s 当前是 %s，不能提交" % (task_id, cheap_task["status"]))
        if self.pending_count() >= QUEUE_LIMIT:
            return {"state": "BACKPRESSURE", "task_id": task_id, "evidence_hash": digest}
        cheap_dup = self.db.execute(
            "SELECT 1 FROM submission_queue WHERE task_id=? AND evidence_hash=?",
            (task_id, digest)).fetchone()
        if cheap_dup:
            return {"state": "DUPLICATE", "task_id": task_id, "evidence_hash": digest,
                    "reason": "NO_NEW_EVIDENCE"}

        try:
            gate_result = gates_mod.enforce(payload, gate, worktree=repo or os.getcwd())
        except gates_mod.GateRejected as exc:
            raise BoardError("闸门没过：%s" % exc.detail, exc.reason_code)
        base = base or self.task(task_id).get("base_commit") or ""
        coverage = None
        if base:
            coverage = gate_mod.check_coverage(normalized["files"], base, head=head, repo=repo)
        now = self.now()
        with self.tx() as c:
            task = self.task(task_id)
            if not task or task["status"] not in ("running", "claimed"):
                raise BoardError("任务 %s 状态在提交过程中变化，已拒绝" % task_id, "OWNERSHIP_VIOLATION")
            if self.pending_count() >= QUEUE_LIMIT:
                self.event(c, "SUBMIT_REFUSED", task_id, {"why": "backpressure"})
                return {"state": "BACKPRESSURE", "task_id": task_id, "evidence_hash": digest}
            exists = c.execute(
                "SELECT seq, state FROM submission_queue WHERE task_id=? AND evidence_hash=?",
                (task_id, digest)).fetchone()
            if exists:
                self.event(c, "SUBMIT_REFUSED", task_id,
                           {"why": "duplicate_evidence", "evidence_hash": digest})
                return {"state": "DUPLICATE", "task_id": task_id, "evidence_hash": digest,
                        "reason": "NO_NEW_EVIDENCE"}
            c.execute("""INSERT INTO submission_queue(task_id, attempt, evidence_hash, state, created_at)
                         VALUES(?,?,?,?,?)""",
                      (task_id, task["attempt"], digest, "queued", _iso(now)))
            status = self._promote_submission(c, now)
            if status == "queued":
                # 已有一份 active：本任务停在 queued_submission，等令牌轮到自己（13 §4.1）
                c.execute("UPDATE tasks SET status='queued_submission', updated_at=? WHERE task_id=?",
                          (_iso(now), task_id))
            if gate_result.get("legacy"):
                self.event(c, "gate.legacy_skipped", task_id, {"why": gate_result["detail"]})
            else:
                self.event(c, "gate.passed", task_id,
                           {"reason_code": gate_result["reason_code"],
                            "checks": gate_result.get("checks", [])})
            self.event(c, "SUBMIT", task_id, {"state": status, "evidence_hash": digest,
                                              "deleted_not_in_files":
                                                  (coverage or {}).get("deleted", [])})
        return {"state": status, "task_id": task_id, "evidence_hash": digest}

    def _promote_submission(self, c, now) -> str:
        """没有 active 就把最小的 queued 提升为 active，任务进 submitted。"""
        if self.active_submission():
            return "queued"
        row = c.execute("SELECT * FROM submission_queue WHERE state='queued' ORDER BY seq LIMIT 1").fetchone()
        if row is None:
            return "queued"
        c.execute("UPDATE submission_queue SET state='active' WHERE seq=?", (row["seq"],))
        c.execute("UPDATE tasks SET status='submitted', updated_at=? WHERE task_id=?",
                  (_iso(now), row["task_id"]))
        self.event(c, "VERIFY_READY", row["task_id"], {"evidence_hash": row["evidence_hash"]})
        return "submitted"

    # ---------- 动作：验证 ----------

    def verify_begin(self):
        """取验证令牌。已有任务在 verifying 时返回 None（D0 一次只看一个）。"""
        now = self.now()
        with self.tx() as c:
            busy = c.execute("SELECT task_id FROM tasks WHERE status='verifying' LIMIT 1").fetchone()
            if busy:
                self.event(c, "VERIFY_BUSY", busy["task_id"], {"why": "token_held"})
                return None
            sub = self.active_submission()
            if not sub:
                return None
            task = self.task(sub["task_id"])
            if task.get("verification_rounds", 0) >= MAX_ROUNDS:
                return {"state": "NO_NEW_EVIDENCE", "task_id": sub["task_id"],
                        "reason": "验证轮数已用尽（2），不再进入 verifying"}
            c.execute("UPDATE tasks SET status='verifying', updated_at=? WHERE task_id=?",
                      (_iso(now), sub["task_id"]))
            self.event(c, "VERIFY_BEGIN", sub["task_id"], {"evidence_hash": sub["evidence_hash"]})
        return {"state": "verifying", "task_id": sub["task_id"],
                "evidence_hash": sub["evidence_hash"], "attempt": sub["attempt"]}

    def decide(self, task_id, decision, reason_code=""):
        """D0 的一条裁决。decision ∈ ACCEPT_MERGE / RETURN_FIX / BLOCK / NEEDS_HUMAN。"""
        if decision not in ("ACCEPT_MERGE", "RETURN_FIX", "BLOCK", "NEEDS_HUMAN"):
            raise BoardError("未知裁决 %r" % (decision,), "INVALID_DECISION")
        now = self.now()
        with self.tx() as c:
            sub = self.active_submission()
            task = self.task(task_id)
            if not sub or sub["task_id"] != task_id:
                raise BoardError("任务 %s 不持有验证令牌" % task_id, "NO_VERIFY_TOKEN")
            if task["status"] != "verifying":
                raise BoardError("任务 %s 当前是 %s，不在 verifying" % (task_id, task["status"]),
                                 "NO_VERIFY_TOKEN")
            # 同一 hash 已裁决过 → 不开第二轮（13 §5.2）
            seen = c.execute("SELECT round FROM verifications WHERE task_id=? AND evidence_hash=?",
                             (task_id, sub["evidence_hash"])).fetchone()
            if seen:
                self.event(c, "NO_NEW_EVIDENCE", task_id, {"evidence_hash": sub["evidence_hash"]})
                return {"state": "NO_NEW_EVIDENCE", "task_id": task_id,
                        "reason": "同一 evidence_hash 已裁决过（第 %d 轮）" % seen["round"]}
            rounds = task["verification_rounds"] + 1
            if rounds > MAX_ROUNDS:
                self.event(c, "NO_NEW_EVIDENCE", task_id, {"why": "rounds_exhausted"})
                return {"state": "NO_NEW_EVIDENCE", "task_id": task_id,
                        "reason": "验证轮数已用尽（%d）" % MAX_ROUNDS}
            c.execute("""INSERT INTO verifications(verification_id, task_id, round, evidence_hash,
                                                   decision, reason_code, decided_at)
                         VALUES(?,?,?,?,?,?,?)""",
                      ("V-%s-%d" % (task_id, rounds), task_id, rounds, sub["evidence_hash"],
                       decision, reason_code, _iso(now)))
            c.execute("UPDATE tasks SET verification_rounds=?, updated_at=? WHERE task_id=?",
                      (rounds, _iso(now), task_id))
            c.execute("UPDATE submission_queue SET state='done' WHERE seq=?", (sub["seq"],))
            new_status = self._apply_decision(c, task, decision, rounds, now)
            self._promote_submission(c, now)
            self.event(c, "DECISION", task_id,
                       {"decision": decision, "round": rounds, "status": new_status,
                        "reason_code": reason_code})
        return {"state": new_status, "task_id": task_id, "round": rounds, "decision": decision}

    def _apply_decision(self, c, task, decision, rounds, now) -> str:
        if decision == "ACCEPT_MERGE":
            c.execute("UPDATE tasks SET status='verified', updated_at=? WHERE task_id=?",
                      (_iso(now), task["task_id"]))
            c.execute("INSERT OR IGNORE INTO merge_queue(task_id, state, created_at) VALUES(?,?,?)",
                      (task["task_id"], "queued", _iso(now)))
            return "verified"
        if decision == "RETURN_FIX":
            returns = task["return_count"] + 1
            status = "returned" if returns < 2 else "blocked"
            c.execute("UPDATE tasks SET status=?, return_count=?, owner=NULL, lease_until=NULL, "
                      "updated_at=? WHERE task_id=?", (status, returns, _iso(now), task["task_id"]))
            self._release_resource(c, task["task_id"])
            return status
        if decision == "BLOCK":
            c.execute("UPDATE tasks SET status='blocked', updated_at=? WHERE task_id=?",
                      (_iso(now), task["task_id"]))
            self._release_resource(c, task["task_id"])
            return "blocked"
        c.execute("UPDATE tasks SET status='needs_human', updated_at=? WHERE task_id=?",
                  (_iso(now), task["task_id"]))
        return "needs_human"

    # ---------- 动作：合并 ----------

    def merge_begin(self):
        """取合并令牌，返回 merge_queue 里最小的 queued 任务。"""
        now = self.now()
        with self.tx() as c:
            held = c.execute("SELECT task_id FROM resources WHERE resource='merge' AND holder IS NOT NULL").fetchone()
            if held:
                self.event(c, "MERGE_BUSY", held["task_id"], {"why": "token_held"})
                return None
            row = c.execute("SELECT * FROM merge_queue WHERE state='queued' ORDER BY seq LIMIT 1").fetchone()
            if row is None:
                return None
            c.execute("UPDATE merge_queue SET state='active' WHERE seq=?", (row["seq"],))
            c.execute("UPDATE resources SET holder='scheduler', lease_until=?, task_id=? "
                      "WHERE resource='merge'", (_iso(now + timedelta(minutes=10)), row["task_id"]))
            self.event(c, "MERGE_BEGIN", row["task_id"])
        return self.task(row["task_id"])

    def merge_done(self, task_id, merge_commit, artifacts=()):
        now = self.now()
        with self.tx() as c:
            row = c.execute("SELECT * FROM merge_queue WHERE task_id=? AND state='active'",
                            (task_id,)).fetchone()
            if row is None:
                raise BoardError("任务 %s 不持有合并令牌" % task_id, "NO_MERGE_TOKEN")
            for art in artifacts:
                self._put_artifact(
                    c, art.get("artifact_id") or "%s:%s" % (task_id, art["path"]),
                    task_id, art["path"], art["sha256"], art.get("version", ""),
                    art.get("acceptance", "accepted"))
            c.execute("UPDATE merge_queue SET state='done', merge_commit=? WHERE task_id=?",
                      (merge_commit, task_id))
            c.execute("UPDATE resources SET holder=NULL, lease_until=NULL, task_id=NULL WHERE resource='merge'")
            c.execute("UPDATE tasks SET status='completed', acceptance_ref=?, updated_at=? WHERE task_id=?",
                      (merge_commit, _iso(now), task_id))
            unlocked = self._recompute_deps(c, now)
            self.event(c, "MERGE", task_id, {"merge_commit": merge_commit, "unlocked": unlocked})
        return {"state": "completed", "task_id": task_id, "merge_commit": merge_commit,
                "unlocked": unlocked}

    def _recompute_deps(self, c, now) -> list:
        """依赖产物齐了才 blocked → ready（13 §7.4 第 5 步）。

        没有依赖记录的 blocked 任务保持 blocked：那通常表示 PARTIAL/Human/手工阻断，
        「没登记依赖」不等于「没有阻塞原因」。
        """
        unlocked = []
        rows = c.execute("SELECT DISTINCT task_id FROM deps").fetchall()
        for row in rows:
            task_id = row["task_id"]
            cur = c.execute("SELECT status FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if cur is None or cur["status"] != "blocked":
                continue
            if self._deps_ok(c, task_id):
                c.execute("UPDATE tasks SET status='ready', updated_at=? WHERE task_id=?",
                          (_iso(now), task_id))
                self.event(c, "UNBLOCKED", task_id, {})
                unlocked.append(task_id)
        return unlocked

    def recompute_deps(self):
        with self.tx() as c:
            return self._recompute_deps(c, self.now())

    # ---------- 崩溃恢复 ----------

    def reap(self):
        """租约过期的 claimed/running 回收为 ready；claim 超限转 failed（13 §9）。"""
        now = self.now()
        expired = []
        with self.tx() as c:
            for row in c.execute(
                    "SELECT * FROM tasks WHERE status IN ('claimed','running') AND lease_until IS NOT NULL").fetchall():
                if row["lease_until"] >= _iso(now):
                    continue
                self._release_resource(c, row["task_id"])
                if row["claim_count"] >= MAX_CLAIMS:
                    c.execute("UPDATE tasks SET status='failed', owner=NULL, lease_until=NULL, "
                              "updated_at=? WHERE task_id=?", (_iso(now), row["task_id"]))
                    self.event(c, "FAILED", row["task_id"], {"why": "claim_limit"})
                else:
                    c.execute("UPDATE tasks SET status='ready', owner=NULL, lease_until=NULL, "
                              "updated_at=? WHERE task_id=?", (_iso(now), row["task_id"]))
                    self.event(c, "LEASE_EXPIRED", row["task_id"],
                               {"claim_count": row["claim_count"]})
                expired.append(row["task_id"])
        return expired

    # ---------- 违规拦截 ----------

    def guard_agent_write(self, task_id, status):
        """Agent 想直接写终态：拒绝并记 W3（13 §6.1、§10 第 11 条）。"""
        if status in AGENT_FORBIDDEN_STATUS:
            with self.tx() as c:
                self.event(c, "W3", task_id, {"attempted_status": status, "by": "agent"})
            raise BoardError("Agent 不得直接写 %s（只能由 scheduler 在验收/合并后写）" % status, "W3")
        raise BoardError("状态只能经 claim/start/submit/decide/merge 迁移", "DIRECT_WRITE")
