# M00 · handoff（给总控 / D0 / A1–A4）

## 1. 你们怎么用（不需要读代码）

```powershell
# 建板（一次）
python -m coordination.scheduler init --board coordination/board.db
# 每次派工：先看计划，再让对应席位去做（本层不会自己开 AI）
python -m coordination.dispatcher --board coordination/board.db --write --out coordination/dispatch.json
# 查状态 / 事件
python -m coordination.scheduler status --board coordination/board.db
python -m coordination.scheduler events --board coordination/board.db
```

`dispatch.json` 的 `assignments[]` 每行 `{lane, agent, action, task_id?}`；`action ∈ claim / busy / idle / paused`。
`state` 为 `DISPATCH` 或 `IDLE`；`backpressure=true` 时所有 lane 都是 `paused`。

## 2. 状态迁移只走这些动作

| 想做的事 | 调用 | 说明 |
|---|---|---|
| 认领 | `claim(lane, agent)` | 拿不到返回 `None`（IDLE 是正常结果，不是异常） |
| 开工/心跳 | `start(task)` / `heartbeat(task)` | 租约默认 900 s |
| 交证据 | `submit(task, evidence)` | 证据不合规抛 `EvidenceError`；重复 hash 返回 `DUPLICATE`；队列满返回 `BACKPRESSURE` |
| 取验证令牌 | `verify_begin()` | 同时只允许一个任务进 `verifying` |
| 裁决 | `decide(task, ACCEPT_MERGE/RETURN_FIX/BLOCK/NEEDS_HUMAN)` | 必须持有验证令牌；同一 hash 不会开第二轮 |
| 合并 | `merge_begin()` → `merge_done(task, merge_commit, artifacts)` | 合并令牌 = `resources.merge` 单 holder |
| 崩溃回收 | `reap()` | 过期 `claimed/running` → `ready`；第 4 次 claim 转 `failed` |

**没有** `set_status(...)` 这类入口。Agent 直写 `completed/merged/verified` 会被 `guard_agent_write` 拒绝并写 `events.type='W3'`。

## 3. 证据哈希怎么算（提交前必做）

```python
from coordination import evidence
h = evidence.digest({...})   # "evidence/1:<sha256>" 或抛 EvidenceError
```

进 hash：`task_id / attempt / status / files[] / tests[] / artifacts[] / known_risks[] / interface`。
不进 hash：`summary / message / 备注 / 时间戳 / 绝对路径 / 主机名 / PID`（所以"换个说法"不会产生新证据）。

路径归一：`files[].path` 相对**自己 worktree 根**，`artifacts[].path` 相对**主工作树** `E:\dsh pr\woker2`，都用 `/`。
NaN/±Inf 直接拒绝（`MISSING_EVIDENCE`）；`-0.0` 记 `0.0`。

## 4. 已验证 / 未验证

- 已验证：27 条测试（13 §10 十二条、H1–H6、4 条补充）全绿；两进程并发 claim 只有一个成功是在**真进程**上跑的。
- 未验证：真实 M01–M08 接入后的端到端流转（本层只跑合成任务）；真实 `git merge`（`merge_done` 只记账）。
- 明确没做：runner（全自动启动）、Agent 自动唤醒、D0 的自动裁决。

## 5. 给 M07 的接口（我的下一块）

M07 面板的"报告区"只读 `pipeline_state.json`（见 `addon/mmd_pipeline/status.py`），与调度器无关；
调度器是团队协作层，不是插件运行时。两者不要互相调用。

---

## 6. attempt 2 增补（务必先读）

### 6.1 板子在哪：只有一个

```powershell
python -c "import sys;sys.path.insert(0,'.');from coordination import paths;print(paths.board_path())"
# 四棵树都会打印同一个：E:\dsh pr\woker2\out\subai\coordination\board.db
```

定位靠 `git rev-parse --git-common-dir` 反推主工作树根；`MMDPIPE_BOARD` / `MMDPIPE_DISPATCH` 可覆盖。
`board.db`、`dispatch.json` **不进版本控制**（D-012）。

### 6.2 建任务时给 `base_commit`，否则闸门不会触发

```powershell
python -m coordination.scheduler add-task --task M07 --module M07 --lane A4 --status ready --base 78d9c23
```

`submit` 时用任务行的 `base_commit` 跑 `git diff --name-only base..HEAD`，
`files[]` 少一个文件就 `MISSING_EVIDENCE` 并列出 `missing[]`。这是 D-022 的机械检查，
不是建议——漏填增量会被挡在验证队列之外。

### 6.3 已知边界（没变的地方）

- 闸门只查"文件是否被列出"，不查每个 sha256 是否真的等于盘上文件（那一步是 D0 手工核对）；
- 合并仍不执行真实 `git merge`；
- 没有 runner，`dispatch.json` 仍需人转交。
