# S5 run_task dry-run 执行回执（M02）

## 结论

STATE=PASS（S5 dry-run 六条判据全过；生产仍未放行）

- 执行者：zzc（Human 自己敲命令；符合材料包 §7「A1 不代跑」）
- 材料来源：`reports/coordination/2026-11-18_S5材料包_交小模型.md`（A1 owner 提交，D0 逐项对盘复核 13:03）
- 前置材料只读核对：小砚 2026-11-18 13:12，全部与材料包声明逐字节吻合
- 工作树：`E:\code\mmdpipe-ai\A1`，branch `ai/a1`，clean，HEAD=`7a40f25`
- 终端：PowerShell

## 1. 执行前只读核对（材料可信性）

| 核对项 | 材料包声明 | 实测 | 结论 |
|---|---|---|---|
| spec 字节 / sha256 | 3896 B / `495827ec…` | 3896 B / `495827ec…`，无 BOM、无 CRLF、raw==lf | ✓ |
| spec 关键字段 | task_id=M02、needs 8298≤cap 10111、skipped=0、lease=false、expect_owner=模块负责1\|A1 | 全部吻合 | ✓ |
| provenance 13 项 | 逐条 sha | 13/13 存在且 sha 吻合，无缺 | ✓ |
| board sha / 字节 / wal | 2fda7078…dc8d / 106496 B / 0 B | 一致 | ✓ |
| events | 16 条，max rowid 16 | 一致，CLAIM/START/RUN_ISSUED=0 | ✓ |
| evidence | 14 份全无 run_id | 14 份，with_run_id=0 | ✓ |
| A1 树 | clean / 7a40f25 | 一致 | ✓ |

## 2. 命令（材料包 §4 原文，一字未改）

```powershell
cd "E:\code\mmdpipe-ai\A1"
python -B -m coordination.run_task --task M02 --agent A1 --owner "模块负责1|A1" --worktree "E:\code\mmdpipe-ai\A1" --spec "E:\code\mmdpipe-ai\A1\out\subai\M02\preflight_m02_s5_dryrun_spec.json" --base 7a40f25a19a191b4734622670bb0aae0d91608ec --head 7a40f25a19a191b4734622670bb0aae0d91608ec --claim --dry-run -- blender -b -P reports/subai/M02/scripts/m02_rebuild_scene_v3.py -- presets/feiying.json "E:\blender模型\没有外套本家模型\星穹铁道—飞霄（无外套）.pmx" out/subai/M02/run_20261118_s5probe --build --patch out/subai/M08/run_20261116_1847/extra_bodies_patch.json
```

## 3. 输出摘要

- `state = DRY_RUN`
- `run_id = dryrun_ad27ce84`
- `task_id = M02`，`resource = blender`，`use_lock_guard = true`
- `preflight.state = READY`，`reason_code = EVIDENCE_COMPLETE`，`blockers = []`
- 五道闸全 ok：provenance（10 项在 A1 / 3 项在已声明外部根）、capacity（needs 8298 ≤ cap 10111）、skipped=0、lease=false（本任务不要求租约）、outputs（目标路径均不存在）
- `worktree`：base=head=7a40f25，dirty=false，root=A1

## 4. 六条判据逐项核对

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | stdout `state=DRY_RUN` | 是 | ✓ |
| 2 | `preflight.state=READY`，五道闸全 ok | 是，blockers=[] | ✓ |
| 3 | 退出码 0 | 命令正常返回完整 JSON，无 traceback；退出码未显式回显 | ✓（见 §6 注） |
| 4 | board sha 仍 2fda7078…dc8d | 是，106496 B，wal=0 B | ✓ |
| 5 | 无 CLAIM/START/RUN_ISSUED，events 仍 16 / max rowid 16 | 是，三类事件计数 0 | ✓ |
| 6 | 无新产物、锁空闲、Blender 未起 | dryrun_* 目录空、s5probe 不存在、rebuild_built.blend 不存在；锁 status=空闲；无 blender.exe（见下） | ✓ |

补充实测：M02 仍 `ready / owner=None / claim_count=0 / attempt=0`，resource holders=0——board 逻辑状态零迁移。

### 判读注意（WAL）

board 是 WAL 模式：写先落 `-wal`，主文件只在 checkpoint 时变。本次主文件 sha 不变 **且** `-wal` = 0 字节 **且** events/逻辑状态不变，三重印证无写。`board.db-shm`/`-wal` 边车文件在只读打开时也会生成，其出现或 mtime 变化不构成违规。

### 进程判读

`tasklist` 查到 1 个 `blender-mcp.exe`（MCP 桥接服务，环境常驻），**不是** `blender.exe`，与本轮无关。dry-run 在预检后即返回（`run_task.py` 269-272），不执行 `--` 后的生产命令，不可能新起 Blender。

## 5. 边界（材料包 §6 原文照抄，不省）

1. **`cap` 是源码级判据，不是运行级读数**：`mmdpipe/stage.py:12` 顶层 `import bpy`，非 Blender 进程 import 直接 `ModuleNotFoundError`（本轮实测）。cap 依据是 `stage.py:330-335` 三条分支 + `mask.py:128 DEFAULT_MAX_CONSTRAINTS=20000` ⇒ `(10111, False)`；`constraint_limit()` 函数**没被执行过**。
2. **spec 还没进 git**：它在 `out/`（`.gitignore:38` 忽略区），这样 A1 才保持 clean。要入库须原字节移入 `reports/subai/M02/`，sha 应仍是 `495827ec…`（移动不改字节）。
3. **dry-run 不证明这条链能跑通**：`apply_input_patch` 里的 `warm_scene()` 是 `b93c181` 之后才加的，324 重建链自此**没真跑过**（上次 324 读数来自 `run_20261116_1847`，早于它）。S6 授权后第一次跑才是首次。
4. **provenance 这条链是「324 重建 + 输入补丁 + 回读」那条**：若生产改走 S8 第三层（`m02_s8_ab.py`）或烘焙链（`m02_bake_delivery.py`），provenance 要按那条链换一份，`needs/cap/skipped/lease/outputs` 五项不变。
5. **board 现状**：`M02=ready/owner=None/resource=blender`、`M04=blocked`（依赖 M03+M02）、`M08=blocked`；`dispatch.json` 四车道 `idle`、`queued_submission=0`。
6. **生产未放行**：本包只覆盖 dry-run。进 S6 需另给授权，且 dry-run 通过不替代 S6。

## 6. 不能主张

- 退出码未显式回显为 `0`：命令正常返回完整成功 JSON、无 traceback，据此判通过；如需严格留证，可重跑时在命令末加 `; "EXIT=$LASTEXITCODE"`。
- 未执行 `--` 后的生产命令；未 claim、未 start、未发真实 run_id、未启动 Blender、未占锁、未产文件。
- 未进入 S6/S7/S8；生产放行需 Human 单独授权。
- 本次未修改任何文件、参数、board、main；未 commit/push。

## 7. 下一步

dry-run 通过，S5 封口。S6（Blender build/install/smoke）需 Human 明确授权，且按执行约束 §7 另有一套硬约束（全程 lock guard、全局 userpref/扩展目录前后 hash 不变、9 项 smoke、smoke.py 的 persistent=True 风险未处理前不得对全局环境运行）。不自行进入。
