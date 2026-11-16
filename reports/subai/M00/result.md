# M00 · 自动调度与分流器 · result

> 席位 A4（模块负责4）· 2026-11-16 · 依据 `13_自动调度与分流器规范.md` + `coordination/evidence_hash_v1.md`
> 状态：**PASS**（本模块自带测试全绿；集成到真实 M01–M08 是下一步，不在本次验收范围）

## 1. 交付物

| 路径（A4 worktree，分支 `ai/a4`） | 作用 |
|---|---|
| `coordination/board.py` | 任务板：13 §6 全部 8 张表 + 事务化状态迁移 + 三类令牌 + 计数落库 |
| `coordination/scheduler.py` | 调度器 CLI：init / add-task / claim / start / heartbeat / submit / verify-begin / decide / merge-begin / merge-done / reap / status / events |
| `coordination/dispatcher.py` | 分流器：四条 lane + 资源检查 + 背压 → `dispatch.json`，**不启动任何 AI** |
| `coordination/evidence.py` | evidence/1 规范化与哈希：路径归一、排序去重、NaN/Inf 拒绝、-0.0 归一 |
| `coordination/board.db` | 合成任务板（4 个任务：M01/M02/M03/M07），可直接 `scheduler status` 查看 |
| `coordination/dispatch.json` | 上面那份板子的派工计划（A1→M01、A2→M03，A3/A4 idle） |
| `tests/test_coordination.py` | 27 条测试：13 §10 的 12 条 + H1–H6 + 4 条补充 |

不改 `mmdpipe/` 下任何模块代码，不改 `addon/`。M00 只新增 `coordination/` 与一个测试文件。

## 2. 13 §10 十二条测试 → 对应实现

| # | 断言 | 测试 | 实现点 |
|---|---|---|---|
| 1 | 两进程同时 claim，只有一个成功 | `test_01_two_processes_claim_once`（真起两个 `python -m coordination.scheduler claim` 进程） | `Board.claim` 在 `BEGIN IMMEDIATE` 里做"读+条件写"，`UPDATE ... WHERE status='ready'` 只可能成功一次 |
| 2 | 一个 Agent 不能同时持有两个 running | `test_02_agent_cannot_hold_two` | claim 前查 `active_task_of(agent)` |
| 3 | 依赖产物缺失 → 保持 blocked | `test_03_missing_artifact_keeps_blocked` | `_deps_ok` 要求 `artifacts.sha256 == deps.required_sha` 且上游 `completed` |
| 4 | 两个完成 → 只一条 submitted | `test_04_two_finish_only_one_submitted` | `_promote_submission` 只在无 active 时提升一条；其余置 `queued_submission` |
| 5 | 队列满 → 暂停派工 | `test_05_queue_full_pauses_dispatch` | `pending_count() >= 2` 时 submit 返回 BACKPRESSURE，dispatcher 全部 `paused` |
| 6 | 同一证据 hash 二次提交被拒 | `test_06_duplicate_evidence_rejected` | `UNIQUE(task_id, evidence_hash)` + 显式 `DUPLICATE / NO_NEW_EVIDENCE` |
| 7 | 两次验证失败后第三次不进 verifying | `test_07_third_round_never_verifies` | `verification_rounds` 与 `verifications` 计数落库；`MAX_ROUNDS=2` |
| 8 | 两个 verified 只有一个 merge token | `test_08_one_merge_token` | `resources.merge` 单 holder |
| 9 | Blender 被占 → 第二个物理任务保持 ready | `test_09_blender_busy_keeps_ready` | `_resource_free` + `_hold_resource` |
| 10 | 租约过期 → 回收，不永久 running | `test_10_lease_expiry_not_stuck`（注入时钟） | `Board.reap()` |
| 11 | Agent 直写 completed → 拒绝并记 W3 | `test_11_agent_cannot_write_completed` | `guard_agent_write` 只写事件不写状态；没有其它改状态入口 |
| 12 | 重跑 scheduler 状态与事件不重复 | `test_12_rerun_is_idempotent` | dispatcher/`recompute_deps` 只在实际迁移时写事件 |

## 3. evidence_hash（H1–H6）

| 编号 | 断言 | 测试 |
|---|---|---|
| H1 | 两进程、两工作树 → 同 hash | `test_H1_two_processes_two_trees`（子进程在 `%TEMP%` 的另一个目录里算） |
| H2 | 只改说明/提交信息 → hash 不变 | `test_H2_description_does_not_change_hash` |
| H3 | 任一 `files/artifacts` sha256 变 → hash 变 | `test_H3_any_sha_change_changes_hash`（3 个反例，4 个互异值） |
| H4 | `./mmdpipe\pmx.py` 与 `mmdpipe/pmx.py` 同 hash | `test_H4_path_normalization` |
| H5 | `tests.passed` 12→13 → hash 变 | `test_H5_test_counts_change_hash` |
| H6 | 含 NaN → 拒绝，不产生 hash | `test_H6_nan_rejected`（NaN 与 +Inf 两个方向） |

补充 4 条：`spec`/`status` 校验、`-0.0` 归一、`known_risks` 空白折叠去重、派工不启动 Agent。

## 4. 实跑记录（A4 worktree）

```
python -m unittest tests.test_coordination      → Ran 27 tests, OK
python -m unittest discover -s tests            → Ran 132 tests, OK (skipped=15)
python -m coordination.scheduler init/add-task/status
python -m coordination.dispatcher --write      → dispatch.json（A1→M01、A2→M03、A3/A4 idle）
```

`skipped=15` 是 `reports/` 依赖的既有跳过项（M03 的回归样本只在主工作树），不是本次新增。

## 5. 已知限制（不是 PASS 的部分）

1. **没有 runner**：`dispatcher` 只产出 `dispatch.json`，不会打开任何 AI 会话（13 §8）。要全自动必须另写 runner，且只能启动 A1–A4 白名单。
2. **合并没接 git**：`merge_done` 登记产物与 commit 字符串，不执行真实 `git merge`。合并此刻仍由总控手工做（令牌只是记账）。
3. **W3 只是记事件**：Agent 直写被拒后留 `events.type='W3'`，没有"停用 Agent"之类的自动惩罚。
4. **时区**：租约时间统一 UTC 秒级；测试里用注入时钟验证过期，没跨机器对时。
5. **背压口径**：`pending = active + queued`，比 13 §4.1 字面（只数 queued）更严；理由写在 `Board.pending_count` 注释里——只数 queued 会放过 3 份在飞提交。

---

# attempt 2（D-20261116-012 退回项的整改 + D-20261116-022 追加验收）

## 6. 退回项逐条整改

| D-012 要求 | 整改 | 证据 |
|---|---|---|
| ① canonical 证据对象落盘并重算 hash | 新增 `reports/subai/M00/evidence_m00_attempt2.json`，**规范化后**的 canonical 字节（无缩进、无尾换行、UTF-8 无 BOM），其文件 sha256 恰等于 SUBMISSION 里的 `evidence/1:<hex>` | `Get-FileHash` 可复核；写入用 `evidence.canonical_bytes(evidence.normalize(obj))`，不是手抄 |
| ② `board.db` 与 `dispatch.json` 移出版本控制 | `git rm --cached coordination/board.db coordination/dispatch.json`；`.gitignore` 增四条（`*.db` / `-wal` / `-shm` / `dispatch.json`） | `git ls-files coordination` 只剩 `.py` 与 `evidence_hash_v1.md` |
| ② board.db 做成四棵树共享的单实例 + 测试 | 新增 `coordination/paths.py`：从 `git rev-parse --git-common-dir` 反推主工作树根 → `out/subai/coordination/board.db`；可用 `MMDPIPE_BOARD` 覆盖 | `TestSharedBoardPath` 2 条：两个不同起点算出同一路径；两个子进程各自打印也相同 |

**为什么要从 git 反推而不是写死路径**：写死 `E:\dsh pr\woker2` 会在换机器、换盘符时静默退回本地 db，形成第二份事实源——那正是这件事要避免的。worktree 的 common dir 永远指向主仓 `.git`，所以四棵树天然算出同一个值；算不出来（不在 git 里）才退回 `<cwd>/coordination`。

## 7. 追加验收：格式闸门（D-022）

新增 `coordination/gate.py`：

- `changed_files(base, head)` = `git diff --name-only base..head`，POSIX 分隔符、去重升序；
- `check_coverage(files, base)`：`files[]` 缺任何一个改动文件 → `CoverageError`（`reason_code=MISSING_EVIDENCE`，带 `missing[]` 清单）；
- **`Board.submit` 默认执行**：任务行有 `base_commit`（或 `--base` 显式给）就过闸门，缺即拒收、不落库；
- git 失败（base 不存在等）**不当作通过**，抛 `EvidenceError`——静默放行比报错危险。

测试（`TestCoverageGate` 7 条，真临时 git 仓库）：
`changed_files` 取自 git、缺文件被拒、全覆盖通过、Windows 反斜杠路径仍覆盖、坏 base 抛证据错误而非放行、`Board.submit` 端到端拦住「只填增量」的提交（`submission_queue` 保持 0 行）、**删除文件单独列出而不要求伪造 sha256**。

**一处与规范字面的偏差，我明说**：`git diff` 里被**删除**的文件也会出现，但删除后没有内容可算 sha256，而 `files[]` 每项都要求 64 位 sha256。硬塞只能造假哈希，比不列更坏。所以闸门按 `--diff-filter=ACMR` 要求覆盖，删除文件由 `deleted_files()` 单独列出、并在 `SUBMIT` 事件里写 `deleted_not_in_files` 留痕。要严格按字面执行，需要 evidence 规范补一个删除标记（升 `evidence/2`）——这件事请 D0 定，我不擅自改规范。

**为什么闸门放在 `submit` 而不是建议里**：M04 那次是"这一笔改了什么"冒充"这条分支上有哪些文件"，人记不住就会再犯；把它写成 `submit` 的默认行为，漏一个文件就进不了验证队列。

## 8. attempt 2 实跑

```
python -m unittest tests.test_coordination   → Ran 36 tests, OK      （+9：闸门 7 + 共享路径 2）
python -m unittest discover -s tests         → Ran 141 tests, OK (skipped=15)
python -m coordination.scheduler init        → 共享板 out/subai/coordination/board.db
python -m coordination.dispatcher --write    → dispatch.json 写到同一目录
```

