# S4 后续：4 条 dispatcher 老测试夹具修复 回执

> 用户授权：「在副本上修，看完结果后我再考虑合并到 main」。
> 本轮只在 integration 副本树改测试夹具，main / board / 参数 / 生产代码一律未碰，未 commit。

## 结论

STATE=PASS（4 条失败用例修复；三环境全量 960 全过）

## 1. 问题回顾（为什么之前 4 败）

4 条老测试调用 `dispatcher.plan()` 时不传 `worktrees` 与 `repo`，于是：

- `plan()` 缺省从 `coordination/worktrees.json` 读真实席位映射（A1–A4 指向 `E:/code/mmdpipe-ai/A*`）；
- 这四棵树停在 `f34b67f`，不是 main(`ad79ebe`) 的祖先；
- S3 worktree 资格预检按设计 fail-closed，判 `needs_human`，与测试期望的 `claim`/`DISPATCH` 冲突。

冻结报告 §1.3/§2.2 已预言此状态。这是**测试夹具没跟上 S3 契约**，不是 dispatcher 缺陷。

## 2. 修法（只动夹具，不动业务）

给 3 个测试文件各加一个本地 helper `make_qualified_repo(root, name)`（与 S3 `test_dispatcher_worktrees.make_repo` 同构：临时干净 git 仓库，内容随 name 变以避免 hash 碰撞），在相关 `plan()` 调用处注入：

```python
wt = make_qualified_repo(..., "wt_xxx")
plan = dispatcher_mod.plan(self.board, repo=wt,
                           worktrees={"P0": wt, "A1": wt, "A2": wt, "A3": wt, "A4": wt})
```

task 未设 `base_commit` 时 `plan()` 取 `repo` 的 HEAD 作 base，`is-ancestor(HEAD, HEAD)` 恒真 → 预检合格 → 走回测试原本要验证的分支。

**未改**：业务断言（`claim`/`DISPATCH`/`needs_approval`/资源预留）、测试数、`dispatcher.py`、`worktrees.json`、任何数值参数/阈值/expectation/truth_tier/taxonomy、真实 board、main。

## 3. 改动文件（精确）

| 文件 | 改动 | 行数 |
|---|---|---|
| `tests/test_coordination.py` | 加 helper；`TestGuards.test_dispatch_does_not_start_agents` 注入夹具 | +22/-1 |
| `tests/test_coordination_architecture.py` | 加 `import subprocess` + helper；`DispatcherP0Test.setUp` 建仓库、`plan()` 注入夹具（覆盖 6 条 P0 测试） | +24/-1 |
| `tests/test_run_task.py` | 加 `import subprocess` + helper；`test_plan_reserves_blender_for_first_claim` 注入夹具 | +23/-1 |

合计 +66/-3。`DispatcherP0Test` 的 6 条测试统一拿到合格夹具；其中 `needs_approval` 类断言在 P0 批准分支就返回，不受 worktree 夹具影响，实测仍通过。

## 4. 测试证据

### 4.1 修复前后对照

- 修复前：单独跑 4 条 → `Ran 4 / FAILED (failures=4)`，均 `needs_human != claim/DISPATCH`。
- 修复后：单独跑 4 条 → `Ran 4 / OK`。

### 4.2 三环境全量（修复后）

| 环境 | discovery | 结果 | exit |
|---|---:|---|---:|
| 默认 | 960 | OK (skipped=1) | 0 |
| UTF-8 | 960 | OK (skipped=1) | 0 |
| GBK | 960 | OK (skipped=1) | 0 |

960 = 原 952 + S4 新增 8，测试数未变。

### 4.3 已知风险（既有，未改）

GBK 日志仍有 6 处 `_readerthread UnicodeDecodeError`，线索在 `tests/test_lock.py`，冻结报告 §3 已登记。未改编码、未加 `errors=replace`、未改环境掩盖。

## 5. 状态取证

- integration HEAD `ad79ebe`，main HEAD `ad79ebe` clean（ahead 451）——未变
- 真实 board SHA `2fda7078…92dc8d`——前后未变
- `git diff --check`：exit 0
- 未 commit、未 merge、未快进 main、未启动 Blender、未 claim 真实任务

## 6. 待你决定（本回执不自动执行）

当前 integration 副本树未提交改动分两组：

**A 组 — S4 本体（上一轮已完成）**
- `coordination/board_backup.py`（新）
- `tests/test_board_backup.py`（新）
- `reports/coordination/2026-11-18_S4_board备份恢复.md`（新）

**B 组 — 本轮夹具修复**
- `tests/test_coordination.py`（改）
- `tests/test_coordination_architecture.py`（改）
- `tests/test_run_task.py`（改）

**不在本任务内、不要一起提交的既有改动**：
- `reports/coordination/2026-11-18_现状与参数冻结报告.md`（modified）
- `2026-11-18_交接文档写作与基线对齐约束.md`、`2026-11-18_小模型交接执行约束.md`（untracked）

下一步由你定：是否把 A+B 一起提交并（审核后）ff-only 合 main；或先只合 A、B 留观。我未执行任何提交。
