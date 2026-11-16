# 2026-11-16 任务报告（D0 决断层）

> 本报告收口 2026-11-16 这一天的工作。所有结论都能顺下列路径回到盘上的字节与账本条目：
> 仓库 `E:\dsh pr\woker2`（main）｜账本 `coordination/decisions.jsonl`（229 条追加式裁决）｜
> 状态权威 `coordination/task_status.json`｜引用规则 `coordination/claim_shape_rules.md`。
> 命令一律给可复跑形式，不给结论式描述。

---

## 0. 一句话

今天把「交付件」这个词从**「一个打开就能播的 .blend」**改成了**「可确定性重建的场景 + 烘焙规程 + 冻结 manifest + 一条写清的使用条件」**，
并且这个改动是**被读数逼出来的**：`T3` 第②条（交付件已烘焙 + 行为探针）在本引擎里**永久不可达**，M08 以 `T2` 交付。

同期建立的东西：**判词分档**、**可比性闸门**、**冻结账本审计**、**锁的代持**、**引用形状规则十三条**。

---

## 1. 终局盘面

| 项 | 值 | 复核命令 |
|---|---|---|
| main HEAD | `e913b4f`（最终值见 §12 收尾补记） | `git log --oneline -1` |
| 裁决条数 | 229 | `python -m coordination.taxonomy --check` |
| 测试 | **898**（默认 / utf-8 / gbk 三环境，exit 0，skipped 1） | `python -m unittest discover -s tests -t tests -p 'test_*.py'` |
| 状态对账 | `state=OK / conflicts=[] / pending_human=[]` | `python -m coordination.status --check` |
| 词表对账 | `state=OK / bad_supersedes=[]` | `python -m coordination.taxonomy --check` |
| 冻结账本 | M08 6 份 manifest / 18 项；M04 批次 35 项；M05 批次 14 项 | `python -m coordination.artifact_audit --root <树>` |

模块档位：**M00 / M01 / M03 / M06 / M07 = PASS**；**M02 / M04 / M05 / M08 = PARTIAL**（M08 天花板 `T2`）。

---

## 2. 交付面口径的最终形态（今天最重要的产出）

### 2.1 结论

| 问题 | 之前 | 现在（有读数为据） | 出处 |
|---|---|---|---|
| 交付件自带烘焙缓存吗 | 以为「烘过就有」 | **没有** | `D-218`、§6.1 |
| 重开件读一帧能拿到我们的姿态吗 | 以为能 | **不能**，差 1.86–1.99 m | `D-223`、§6.2 |
| 场景能重建吗 | 未测 | **能**（两遍独立会话逐位相同） | `D-222`、§6.3 |
| 因此交付件是什么 | 打开即回放 | **场景 + 烘焙规程 + 冻结 manifest +「开件后需顺序重算一次」** | `D-214`/`D-219`/`D-223` |

### 2.2 `known_risks`（`coordination/task_status.json` → `tasks.M08.known_risks`，三样不许拆）

```
①缓存不随文件走：`use_disk_cache` 在 5.2 赋值即 `EXCEPTION_ACCESS_VIOLATION`（D-218），
  `out/subai/M08` 全树无 `blendcache*`，重开件 `is_outdated=true`；
②开件后第一次求值 ≠ 顺序重算：同一份件、323 刚体、f417、tol 1e-6 的实测四簇
  `1.856515`（陈旧 is_baked）/`1.863228`（首次求值）/`1.994664`/`1.994782`
  （先清 is_baked 再首次求值，差反而更大）⇒ 与标志位无关，是引擎首次求值行为；
③因此「需重算一次才得到与读数一致的姿态」是使用条件、不是小提示，且适用于任何重开的文件。
```

### 2.3 待 Human 的一条（唯一）

**`T3` ② 要不要改定义。**

- **（一）认 `T2` 为天花板**（默认，已写进状态表）：交付按「场景 + 烘焙规程 + 冻结 manifest」+ 使用条件。
- **（二）改 `T3` ②**：把「缓存能随文件走」换成「开件后顺序重算能复现同一姿态」（3 帧、tol `1e-6`、重放差作为已知限制记录）。这样 `T3` 重新可达，但它是「可确定性重建的交付」。

若要「能直接播的动画」，那是另一条渲染/导出路线（烘成帧序列或导出缓存），不在今天的车道里。

---

## 3. 时间线（commit 锚点）

| 时段 | 发生了什么 | 关键 commit |
|---|---|---|
| 11:42 起 | 基座与协调层搭起（board / dispatcher / gate / evidence_hash / taxonomy） | `7f764ea`、`78d9c23`、`305d67f` |
| 13:00–15:00 | 身份两层、`content_digest_v1` 三次加固、M04 预注册 v2→v4 | `014dc51`、`dce10cd`、`e44ec9a`、`5e29d20` |
| 15:00–17:00 | 掩码通道 WIRED、约束账目、Human 六条回答落账（D-168..174） | `e685ee2`、`1142994` |
| 17:00–18:30 | 324 缺口、apply_action 入链、七臂读数、版本化与冻结 | `689d6a3`、`f51f837`、`8faec43` |
| 18:30–19:00 | 烘焙派单与三条出路、`lock guard` 落地、四臂 324 批次 | `ac1bab1`、`f1e6047`、`a3c4d67` |
| 19:00–19:20 | 烘窗口真机跑通 → **发现缓存不出门**（`T3` ② 不成立） | `4ebd581`、`ce9d57e`、`c1e5193` |
| 19:20–19:40 | 首读偏差坐实、可比性闸门落地、M04 第二轮开判 | `215c31e`、`239ec8e`、`4326996` |
| 19:40–20:00 | 读数分层、账本审计、`ok` 不可达的裁定、收尾 | `0aa970d`、`3f8ed7c`、`de9ad4a`、`6c575c6` |

---

## 4. 改动清单（可追溯）

### 4.1 协调层新增（全部是我今天的产出，路径即 `coordination/` 下）

| 文件 | 作用 | 首见 commit |
|---|---|---|
| `taxonomy.py` | 决策词表唯一执行点：`validate` / `check_history` / `append`（原子写）+ `supersede_map` 七条 fail-closed | `78d9c23` 起，今天多次加固 |
| `status.py` | 任务级状态权威 + 对账 C1–C8（任务集双向、legacy 一致、待批与 human_gate 一致…） | 同上 |
| `lock.py` | Blender 独占锁；今天新增 **`guard`** 子命令与 `--owner-module/--owner-tree` | `f1e6047` |
| `human_gate.py` / `gate.py` / `gates.py` / `preflight.py` / `dispatcher.py` / `scheduler.py` / `acceptance.py` / `provenance.py` / `evidence.py` / `evidence_store.py` / `board.py` / `sync_board.py` | 受控 Human gate、开工前置、派单、验收、产地与证据 | 今天陆续 |
| **`comparability.py`** | **新增**：可比性六条 / 同域差 / 极值三件套 / 窗口规则 / 切点敏感度 | `239ec8e` + `7574384` |
| **`artifact_audit.py`** | **新增**：冻结账本审计（逐项重算 + 双向枚举 + git 视角） | `3f8ed7c` + `7574384` |
| **`claim_shape_rules.md`** | **新增**：引用形状规则十三条，每条标出逼出它的事故 | `6eec0f7` 起 |
| `ARCHITECTURE_V2.md`、`evidence_hash_v1.md`、`evidence_store_policy.md`、`mask_channel_spec.md`、`m08_acceptance.md`、`board_path.md`、`decision_taxonomy.json`、`decisions.jsonl`、`task_status.json` | 规范与账本 | 今天陆续 |

### 4.2 协调层今天的具体改动（含原因）

| 改动 | 原因 | commit |
|---|---|---|
| `lock.py` 新增 `guard`：取锁→跑→必放；取不到锁**命令根本不执行**；跑期间后台心跳；锁丢失退 5 | 一天内两个人（`3号` 18:18、`2号` 19:00）都「拿到 `LOCK_HELD` 没看退出码就起 Blender」（7 个与 2 个进程）。**同一类错一天两次，问题不在注意** | `f1e6047` |
| `lock.py` `--owner-module/--owner-tree` 两段写法，`--owner` 与它互斥 | `模块负责2\|A2` 的竖线在后台作业启动器里被当管道吞掉，owner 变半截，**报的却是「owner 格式错」** | `4ebd581` |
| `lock.py` `_split_dashdash`（在第一个 `--` 处切 argv） | 我自己第一版用 `argparse.REMAINDER`，`guard --owner X -- cmd` 把 `--owner` 吞进命令 ⇒ **把用法错伪装成参数错** | `f1e6047` |
| `taxonomy.py` `supersede_map` 七条 fail-closed | 我 18:44 手写 JSON 追加了 D-199..203（`decision=RULING` + 5 个自造 reason_code），绕过校验。`2号`/`3号`/`4号` 十分钟内各自撞出四个 fail-open（H1 重复声明可用行序操纵、H2 声明可写目标之前、H3 合规则被误记进越界桶、H4 自我更正） | `a3c4d67` |
| `status.py` `pending_human()` 的显式关闭规则 | `append()` 把词表外 kind 自动转 `NEEDS_HUMAN` ⇒ 造出**假的待批项**（`D-215` 实质是规格裁定，不需要人批）；只有后续裁决在正文点名它才算关闭 | `3a17f2c` |
| `task_status.json` 新增 `M04/M05/M08.artifacts` | 「盘上每个在账上、账上每个在盘上」此前只是说法；现在有工具与逐项读数 | `7574384` |

### 4.3 `mmdpipe/` 改动（由席位提交，我合并；**我不写模块代码**）

| 文件 | 改动 | 原因 | 提交 |
|---|---|---|---|
| `mmdpipe/stage.py` | 烘焙判据分两层（进程内 6 条 + 重开 3→4 条）；`bake_failure_shape()` 五态判词；**禁止对 `use_disk_cache` 赋值**（AST 断言）；`stage.py:1279` 改走 `fcurves_of` 并记 `fcurves_via`；`mask_wired` 按 18 键清单生成 + `mask_wired_omitted` | 「`applied=true` 不足判交付件已烘」；`use_disk_cache` 那行一旦被「好心修好」，崩的是整条构建；`mask_wired` 手抄 11 键 vs 清单 18 键 ⇒ **「放掉 2196 条」在冻结件里没有出处** | `84c06d6`、`294b0e9`、`54061f3` |
| `mmdpipe/apply_action.py` | `fcurves_of()`（读侧，`:300`）+ `fcurve_container()` / `ensure_fcurve()`（写侧）+ `FcurveShapeError`；`assert_lock_owner` 在 `import bpy` 之前 | Blender 5.2 把动作随 `.blend` 存盘再读回来就是**分层/槽位动作**，`action.fcurves` 直接崩 ⇒ **「幂等/可重跑」此前只在同一会话内成立过** | `aec65a0`、`26f5877`、`b300c5c`、`16eadcc` |
| `mmdpipe/chain_nla.py` | `_shift_b_action` 改走 `ensure_fcurve`，返回 `(键数, 走哪条路)`；`concat_via_nla` 落 `fcurves_via` | 写路径同样崩在「拼」。**注意：这是防御性修复，「打开存盘件再拼」的入口目前不存在**（`concat_via_nla` 每次 `_fresh_scene()` 重导） | `26f5877` |
| `mmdpipe/mask.py`、`mmdpipe/cache_state.py`、`mmdpipe/physics_gate.py`、`mmdpipe/measure.py` 等 18 个文件 | 掩码通道、缓存状态、物理闸门、测量 | 席位各自车道 | 今天陆续 |
| `addon/mmd_pipeline/*`（4 个） | 面板与 operator 接线、`run_tool.py`、`status.py` | M00/M07 | 今天陆续 |
| `presets/physics_gate/*.json`（2 个） | 物理闸门预设 | 同上 | 今天陆续 |

### 4.4 测试（34 个文件受动，今天新增 13 个）

新增：`tests/test_artifact_audit.py`、`tests/test_comparability.py`、`tests/test_chain_nla_fcurves.py`、`tests/test_stage_bake.py`、`tests/test_stage_motion_fcurves.py`、`tests/test_m04_baseline_payload.py`、`tests/test_m04_preflight_spec.py`、`tests/test_m04_run_cd.py`、`tests/test_m04_run_cd_launcher.py`、`tests/test_m04_segment_table.py`、`tests/test_m04_snapshot_scope.py`、`tests_bpy/` 下 10 个。

其中**属于我的**（协调层）：`test_coordination_architecture.py`（`LockGuardTest` 9 条、`TaxonomyTest` +6）、`test_comparability.py`（39 条）、`test_artifact_audit.py`（18 条）。

### 4.5 今晚（18:45 之后）的自有改动，共 129 个条目

复跑：`git diff --name-status ae9ef4f HEAD`

按目录：`reports/` 100+、`tests/` 16、`coordination/` 7、`mmdpipe/` 3。
我这边的 7 个：`coordination/{artifact_audit.py(新), claim_shape_rules.md(新), comparability.py(新), decisions.jsonl, task_status.json, lock.py, taxonomy.py}`。

产出的可交付物：

- `reports/subai/coordination/artifact_audit_20261116.json`（四棵树账本审计结果）
- `reports/subai/coordination/round_summary_20261116.md`（轮次小结）
- `reports/subai/coordination/task_report_20261116.md`（本文件）

---

## 5. 裁决台账（229 条，按主题分组）

全部经 `coordination.taxonomy.append()`。复跑：`python -m coordination.taxonomy --check`。

| 主题 | 编号区间 | 要点 |
|---|---|---|
| 身份与摘要 | `D-189`–`D-191` | 实例 sha（绑读数）× 内容摘要（可复现）两层；`strict`/`partial` 两模式；摘要必须带覆盖范围 |
| 掩码与约束账目 | `D-206`–`D-212` | `12338 = 4009 + 31 + 8298`、`2227 = 2196 + 31`；`disable_collisions=True` 计数 == `needed` 且烘前烘后相等 |
| 锁与并发 | `D-194`–`D-195`、`D-213` | `assert-owner`（进程内）+ `guard`（进程外）；锁丢失退 5 |
| 烘焙与 `T3` | `D-207`–`D-219`、`D-223`、`D-228` | 烘焙必须在动作之后；缓存不出门；首读偏差；`ok` 不可达拆两档 |
| 测量可比性 | `D-196`、`D-211`、`D-221`、`D-224` | 可比性六条；同域差；事后窗口不许作判据 |
| 交付边界 | `D-202`、`D-209`、`D-210`、`D-222` | 实例 sha 不可复原 ⇒ 永久 `T2`；臂件不烘；写侧入口未建；四条 `UNMEASURED` |
| 读数分层 | `D-225`、`D-226` | 数据层 × 求值层；`first_eval_after_open` ≠ `warmed_up` |
| 账本与工具 | `D-227`–`D-228` | 账本双向枚举；判词分档才有区分力 |

---

## 6. 失败与错误日志原文（逐条：时间 / 形状 / 原文 / 根因 / 修法 / 落点）

> 这一节是 Human 明确要求的「原文」。凡日志都注明来源文件，可直接打开核对。

### 6.1 引擎级崩溃：`use_disk_cache` 赋值即崩（**`T3` ② 不可达的第一块基石**）

**原文**（`reports/subai/M02/scripts/diag_diskcache.py` 的实测输出，记录在 `reports/subai/M02/bake_and_cache_findings.md` §三）：

```
DIAG open
DIAG PointCache props: rna_type, frame_start, frame_end, frame_step, index, is_baked, is_baking,
                       use_disk_cache, is_outdated, is_frame_skip, name, filepath, info,
                       use_external, use_library_path, point_caches
DIAG cache before use_disk_cache=False baked=False outdated=True
DIAG set use_disk_cache
Error   : EXCEPTION_ACCESS_VIOLATION          ← 崩在赋值这一行
```

进程退出码 `-1073741819`（=`0xC0000005`），`elapsed=0.1 min`（远早于烘焙开始）。**两次复现**，其中一次就是这个只做三件事的诊断脚本。

- **根因**：Blender 5.2.2 上给 `PointCache.use_disk_cache` 赋值即触发引擎崩溃；且 5.2 的 `PointCache` **没有 `directory` 字段**（叫 `filepath`），旧 API 写法连赋值都过不去 ⇒ 这条路上**没有可用的落盘入口**。
- **判词**：**这是读数，不是失败。** `(a)` 路永久关闭（`D-218`），不再排窗口。
- **落点**：`coordination/task_status.json` → `tasks.M08.known_risks` ①；`mmdpipe/stage.py` 里加了 AST 断言禁止对 `use_disk_cache` 赋值（`84c06d6`）。

### 6.2 首读偏差：同一份件、四簇读数

**原文**（`reports/subai/M02/bake_and_cache_findings.md` §四，数据来自 `out/subai/M08/run_20261116_1900/`）：

| 变体 | 首读之前发生了什么 | `over_tol` | `max_delta` |
|---|---|---|---|
| 开件后立刻冷跳，`is_baked=true`（陈旧标志） | 零求值 | 275/323 | `1.856515` |
| 开件后第一次求值（未清标志） | 零求值 | 275/323 | `1.863228` |
| 先求值一次 → `free_bake_all()` → 冷跳 | 有一次求值 | 275/323 | `1.994664` |
| **先 `free_bake_all()` 再做开件后第一次求值**（副本） | 清标志、零求值 | 275/323 | **`1.994782`** |
| 先走过 1..833，再冷跳 | 全程走过 | 0/323 | `0.0` |

缓存状态原文（`out/subai/M08/run_20261116_1900/cache_probe.json`）：

```
cache_before: {"frame_end": 833, "frame_start": 1,
               "info": "833 frames in memory (7.3 MiB), cache is outdated!",
               "is_baked": true, "is_outdated": true, "use_disk_cache": false}
cached_pose_sha: 795ec30bcd7f7e2133221a09f8e6c1638589235cdcdaa077b2e83eb6d58d8615
compare: {"bodies": 323, "max_delta": 1.85651505, "over_tol": 275, "tol": 1e-06}
```

- **根因**：**开件后第一次求值本身不是顺序重算的结果**，与 `is_baked` 标志位无关（清掉标志后差反而更大）。
- **修法**：判据分档（`replay_unmeasurable_engine`，`54061f3`）；任何求值层读数必须先顺序热身并记 `warmup_frames` / `first_eval_after_open`。
- **落点**：`D-223`、`D-228`；`coordination/claim_shape_rules.md` 第九条。

### 6.3 分层动作上没有 `action.fcurves`

**原文**（`out/subai/M05/probe_fcurve_write_shape.json`）：

```
"fcurves_readable": null,
"fcurves_error":    "AttributeError: 'Action' object has no attribute 'fcurves'",
"bags":             [{"at": [0, 0, 0], "fcurves": 725, "slot": "B_aligned_bone"}],
"ensure_fcurve_on_copy": {"how": "channelbags[0](find); upstream_raised:RuntimeError", ...},
"blend_untouched":  true
```

上游接口的实测（同一份 JSON）：

```
"upstream": {"exists_on_class": false, "exists_on_instance": true,
             "doc": "Action.fcurve_ensure_for_datablock(datablock, data_path, index=0, group_name=\"\") ...
                     This action must already be assigned to the data-block. This function will also create
                     the layer, keyframe strip, and action slot if necessary, and take care of assigning the action slot too"}
```

- **根因**：动作随 `.blend` 存盘再读回来是分层/槽位动作；`action.fcurves` **抛属性错**（不是返回空集合 —— 这条实测关掉了我担心的「写进死容器而 `keys_touched` 是正数」的静默失效路径）；上游接口**只在实例上有、类上没有**，且有前置条件「动作必须已挂到该 data-block」。
- **修法**：`fcurves_of()`（读）+ `fcurve_container()` / `ensure_fcurve()`（写，四档，挑不准就抛 `FcurveShapeError` 不猜）；**先判前置条件再调上游**，不拿异常当流程控制。
- **落点**：`mmdpipe/apply_action.py`、`mmdpipe/chain_nla.py`；`D-220`、`D-222`。

### 6.4 我自己写错判据被护栏咬住（`bake=None` 也算「带了 bake」）

**原文**（`1号` 报告）：

```
FAIL: test_stage_bake.TestCallSite.test_existing_callers_do_not_pass_bake
```

- **根因**：`4号` 的护栏扫 `stage_build(` 之后 200 字符窗口、断言不出现 `bake=`；`1号` 为「报告里看得见这次没烘」写成 `stage_build(preset, root, arm, bake=None)` —— **显式 `None` 也算带了 bake**。
- **修法**：去掉参数、理由留注释，语义不变（`D-207` 不变）。
- **落点**：`b9fa…`（`1号` `ba7fa05`）。

### 6.5 收尾时 main 红一条：快照副本被 `.gitignore` 吞掉

**原文**（我在 main 上跑 `python -m unittest discover -s tests -t tests -p 'test_*.py'`）：

```
FAIL: test_snapshot_copies_are_listed_and_present
      (test_m04_snapshot_scope.RealSnapshotTest.test_snapshot_copies_are_listed_and_present)
  File "E:\dsh pr\woker2\tests\test_m04_snapshot_scope.py", line 59, in test_snapshot_copies_are_listed_and_present
    self.assertTrue(os.path.exists(os.path.join(SNAP, name)), name)
AssertionError: False is not true : compare.log

Ran 881 tests in 30.333s
FAILED (failures=1)
```

`git check-ignore` 原文：

```
.gitignore:39:*.log	reports/subai/M04/cd_round2/compare.log
```

- **根因**：`2号` 的二轮快照副本含 `compare.log` / `compare_selftest.log`，被 `.gitignore:39 *.log` 吞掉 ⇒ **他的工作树永远有、干净 checkout 永远没有**，所以这只在他那边绿、在我这边红。
- **加重情节**：**同一个坑今晚第二次** —— 18:37 他自己记过「作废件日志被 `*.log` 吃掉，改名 `.log.txt` 才落得进 git」。那次是作废件，这次是快照副本。
- **修法**（已派单）：改名 `.log.txt` 或从清单删除并写明理由；**测试改为问 git**（`git ls-files --error-unmatch`），让它红在作者那边。
- **落点**：`coordination/claim_shape_rules.md` 第十三条（快照账本必须在干净 checkout 上可复现）。

### 6.6 我的审计工具把「量不了」报成「不一致」（46 条假阳）

**原文**（我第一次审 `2号` 的 `cd_round2/manifest.json`）：

```
cd_round2/manifest.json    ok=False drift=46
```

- **根因**：①他的批次 manifest 条目是 `{"name": "C_W1.jsonl", …}` 只写文件名，产物在 `out/` 批次目录、不在 manifest 旁边，我解析不出路径就记成「不一致」；②我拿 manifest 所在目录做双向枚举，而条目全在别处，造出一堆假 `only_on_disk`。
- **修法**：解析不了的记 `unresolved` / 状态 `UNMEASURED`（**不算 drift**）；条目指向别处时 `two_way_checked=false` 跳过双向枚举；加 `--base`。改完再审：**35 项 drift=0**。
- **性质**：**「量不了」写成「不一致」，正是我今晚判别人四次的那条错，只是换了个对象。** 规则对工具和对人也有效。
- **落点**：`coordination/artifact_audit.py`（18 条测试）；规则第十一条。

### 6.7 环境与工具类失败（我自己的操作日志）

| 原文 | 根因 | 修法 |
|---|---|---|
| `ModuleNotFoundError: No module named 'pytest'` | 本仓测试 runner 不是 pytest | 改用 `python -m unittest discover -s tests -t tests -p 'test_*.py'` |
| `ImportError: Start directory is not importable: 'E:\\dsh pr\\woker2\\tests'` | 少了 `-t tests`，`tests/` 无 `__init__.py` | 同上 |
| `ModuleNotFoundError: No module named 'bpy'` | 直接 import `mmdpipe/stage.py` 需 bpy | 离屏验证走测试套件，不直接 import |
| `OSError: [WinError 123] 文件名、目录名或卷标语法不正确`（刷满屏 readline 堆栈） | 我把 `python - @'…'@` 写成了「`-` 读 stdin + 参数」，PowerShell 无 heredoc | 改用写临时 `.py` 文件 |
| `SyntaxError: invalid character '€' (U+20AC)` | 我用 `Set-Content -Encoding utf8` 改测试文件，把 UTF-8 中文写成乱码 | 改写整文件（`write` 工具），此后一律用 `edit` |
| `Error: old_string matched 3 times` | 编辑时 old_string 太短（一个 `---`） | 给更长的锚 |
| `AssertionError: Lists differ: [328, 354, 407] != [328, 354, 408]` | 我算 `ratio_cuts` 期望值时按 `531*0.2=106.2` 手算成 408 | 按实现关系 `302 + round(531*0.2) - 1 = 407` 改测试 |
| `TypeError: domain_extrema() missing 1 required positional argument: 'hi'`<br>`KeyError: 'problems'`<br>`AssertionError: True is not false` | 我自己测试里的三处笔误（签名、断言取错分支、造的数据没让极值帧真的移动） | 逐个改 | 
| `Not committed — main_unread_required`（两次）<br>`Error: unknown Project ref '1d8797df…'`（一次） | ①Main 有未读就写；②`projectRef` 少了 `project:` 前缀 | 先 `team_thread read` 清未读；补前缀 |
| `error: Your local changes to the following files would be overwritten by merge: reports/subai/coordination/m08_artifact_audit.json` | 我在删旧审计产物时没先提交，就 merge 别人的分支 | 先 `commit` 删除再 merge |

### 6.8 同一族错五次：把局部当整体（今天的头号错形，跨四个席位 + 我自己）

这一节单列，因为它是今天**唯一一个重复了五次**的错形，而且每次的读数都"看起来有出处"。共同结构只有一句：**在一个窗口里算出来的量，被当成了另一个窗口的性质。**

| # | 谁 | 原文读数 | 真值 / 为什么不能这么比 | 落点 |
|---|---|---|---|---|
| 1 | `2号` | `C@W1` 与 `C@W2` 的最大值相减，得 **`0.049031 m`** | 那个 max 落在 `302..354` 保持段（**跨域**）；两侧同属 `f1..240` 时才是 **`0.046198 m`**。跨域相减在这个口径下**不可类型化** ⇒ 裁定只认同域，跨域数作废 | `D-196` 之后我的更正；`coordination/comparability.py` `domain_extrema()` 单帧域参数 |
| 2 | `4号` | 引用两处穿透深度，说 **`−1.556` 比 `−1.324` 更浅**（按绝对值读） | 深度是**带符号**的：`−1.556` 比 `−1.324` **更深**。方向读反会把这个结论推向反面 | Main stream 当场更正 |
| 3 | `3号` | 把 `f353` 的偏差写成 **`355..832` 段**的性质 | ①`f353` **不在** `355..832` 里；②那一段的真极值是 **`−65.647 @ f646`**；③`f353` 是 **50 帧的瞬态**，不是 531 帧的属性 | 规则「极值必须带 值 + 帧号 + 邻域计数 + `TRANSIENT`/`PLATEAU`」；`extremum_report()` 拒绝域外帧号 |
| 4 | 我 | 用 `0.049031` 受理 `2号` 的结论，并想把它写进交付口径 | 同域真值 `0.046198`，两者差 2.8 mm —— **受理数值结论前没核可比性** | 当场更正并进账本 + 纪律条「受理数值结论先核可比性与正控，再看数字」 |
| 5 | 我的工具 | `artifact_audit` 第一版报 `2号` 批次**46 条 drift** | 46 条全是**解析不出来**的（条目只写裸 `name`、产物在 `out/` 批次目录），不是不一致。详见 §6.6 | `artifact_audit.py` v2：`unresolved` / `UNMEASURED` / `two_way_checked=false` / `--base` |

**从这一族里长出来的三条判据（现在都在仓里，不只在对话里）：**

1. **极值不是分布量**：引用极值必须给 `值 + 帧号 + 邻域计数 + 窗口规则`；`TRANSIENT` 不许当整段属性。
2. **同一组数能不能比是一组条件，不是一个印象**：`COMPARABILITY_FIELDS` 六条并列（帧域 / 基线 / 对宇宙 / 尺度 / 段标签 / 窗口规则）。
3. **窗口规则必须"先于数据可判"**：事后反解出来的比例（如 `9.70%` / `9.79%` / `10%`）一律标 `post_hoc`，只能解释、不能当判据。

第 4 条和第 5 条的性质相同，只是对象不同：**判别人的那条规则，对我自己的工具和对自己的受理动作同样有效。**

### 6.9 收尾时 main 第二次红：仓库级编码护栏咬住新代码

**原文**（A2 修完快照测试后，我在 main 上跑三环境）：

```
FAIL: test_repo_is_clean (test_subprocess_encoding.TestGuard.test_repo_is_clean)
  File "E:\dsh pr\woker2\tests\test_subprocess_encoding.py", line 203, in test_repo_is_clean
    self.assertEqual(violations, [],
                     "这些 subprocess 调用按文本取输出却没有 encoding=：%s（%s）"
                     % (violations, line))
AssertionError: Lists differ: [('reports/subai/M04/scripts/m04_snapshot_scope.py', 78)] != []
```

- **根因**：`2号` 新写的 `git ls-files --error-unmatch` 调用 `subprocess.run(..., text=True)` 少了 `encoding=`，触发仓库级编码护栏（今天上午由 PS 5.1 / GBK 控制台事故立起来的）。
- **修法**：我按护栏口径补 `encoding="utf-8", errors="replace"` 一行。
- **记账**：**我动了 `2号` 的一个文件** —— 为了让 main 变绿属集成职责，但必须记账并通知本人（已在 Main stream 点名，他下次动该文件前先同步）。这是今天唯一一次我改别人车道的文件。
- **备注**：护栏本身是对的 —— 它咬的是「按文本取输出却没声明编码」，而那个坑今天上午刚让一份 GBK 控制台输出崩在打印上（`D-193` 的编码护栏收进 `reports/**/scripts`，98 个脚本 0 违规）。

### 6.10 规则第十三条当晚自我验证：三个席位各自查自己，全红

同一条断言（**账本要对着 git 的视角验**）在立起来之后一小时内，被三个席位拿去验自己，三处都红了：

| 席位 | 红在哪 | 原文要点 | 修法 |
|---|---|---|---|
| `2号` | 快照副本 `compare.log` / `compare_selftest.log` | `AssertionError: False is not true : compare.log`；`git check-ignore` 给出 `.gitignore:39:*.log` | 清单每份副本带 `in_git`（`false` 必须给 `why_not`）；核验改 `git ls-files` 三态（git 不可用 = `UNMEASURED`）+ 4 条负控 |
| `3号` | 报告引用的 **6 个控制/探针脚本**原先都在 `out/subai/M05/` | `out/` 被 `.gitignore:38` 吞掉 ⇒ **干净 checkout 上这些脚本根本不存在**，而报告写着「红 3 条 / 绿 6 条」 | 六个脚本移进 `reports/subai/M05/scripts/`（`dba3219`） |
| `4号` | M07 探针与扩展复测脚本同样在 `out/` 下 | 「报告在，方法不在」 | 探针入库（`3164572`），并新增闸门 `tests/test_reports_scripts_tracked.py` |

**价值不在抓到三个坑，在于它是当晚立的、当晚就用它抓到了自己人。** 事故链：`2号` 18:37 记「日志被 `*.log` 吃掉，改名才落得进 git」→ 我只当一句话 → 他 19:55 又踩同一条 → 我立成断言 → 三个席位各自红。**一句话记在对话里和一条断言的区别，今晚付了两次代价。**

- `3号` 的 `ModuleNotFoundError`：**根层数算错**（`out/subai/M05` 到根是 3 层，他写了 4 层）。修法升级为「**先验根、再 import，并把算错的根打印出来**」；负控把脚本拷到临时目录跑，报 `ROOT 算错了：C:\Users\zzc\AppData\Local 里没有 coordination/ 与 mmdpipe/`，**不是** `ImportError`。
- `2号` 的静默降级：脚本态 `sys.path[0]` 是脚本目录 ⇒ `import coordination` 失败；他原来 `try/except` 兜底成「本地实现」继续跑，**读的人看不出它其实没接上**（第一次接线就因此静默失败、报告照旧、没有一处红）。
- `2号` 的第一遍 `f1` 判别：收尾撞 `0xC0000005`，**产物已落盘**；后两遍 `rc=0` 同值。
- Blender `--background` 退出清理阶段的 `EXCEPTION_ACCESS_VIOLATION`/`0xC0000005`（`D-148`）：**退出码两个方向都不可信** —— 脚本抛异常可以是 0，正常跑完可以是非 0 ⇒ 唯一可信的是**产物完整性**（帧数齐 + 字段在）。

---

## 7. 我自己今天错的地方（不留死角）

| # | 错的形状 | 后果 | 更正 |
|---|---|---|---|
| 1 | 手写 JSON 追加 5 条裁决（`decision=RULING` + 5 个自造 reason_code），绕过 `append()` | 词表外 kind 入账 | `D-204` 用 `supersedes` 逐条更正；`taxonomy.check_history` 补这条路 |
| 2 | 又一次用 `RULING`，`append()` 自动转成 `NEEDS_HUMAN` ⇒ **造出假待批项**，还去打扰了 Human | 账面上一条不该有的待批 | `D-216` 设计-path 更正 + 正文点名关闭 + 回归测试 |
| 3 | 我说 `.blend` 字节「一定不同」 | 理由错 | 改「复现性不稳定」 |
| 4 | 我说「无动作场景探针会假绿」 | 理由错（刚体受重力仍在动） | 结论不变，理由改为「缓存捕获的是重力沉降不是舞蹈」 |
| 5 | `D-212` 给的判据 `type=='RIGID_BODY_CONSTRAINT'` 期望 12307 | 5.2 枚举里没这一项，数出来恒 0；且漏了 31 条残差 | 采纳「`disable_collisions=True` 计数 == `needed` 且烘前烘后相等」 |
| 6 | 受理 `D-196` 时只核算术、没核可比性与正控 | 结论被 `2号` 自己推翻 | 纪律加一条：**受理数值结论先核可比性与正控，再看数字** |
| 7 | `D-217` 把「缓存没出门」判成「缓存会算错」 | 两种形状指向两个修法 | `D-219` 更正；`4号` 抓的 |
| 8 | `D-219` 把 1.86 m 归因「无效缓存」 | 实测清掉 `is_baked` 后差**更大**（1.99 m） | `D-223` 第三次改同一行，真因是**开件首次求值** |
| 9 | 我说「恒红闸门没有区分力」 | 只说对一半 | `D-228` 更正：**区分力来自判词分档，不是来自「有时能绿」** |
| 10 | `artifact_audit` 第一版把「量不了」写成「不一致」（46 条假阳） | 差点冤枉 `2号` 的 35 项产物 | §6.6 |
| 11 | 我一度想拿「9.79%」当口径 | 那是从数据反解的**事后窗口** | `D-224`：标 `post_hoc`，只作解释 |
| 12 | 我 `edit` 时把 `claim_shape_rules.md` 末尾「附」小节标题吃掉 | 文档结构坏 | 下一条 commit 补回 |

今天 229 条裁决里约 **11 条是自我更正或撤回**。比例不难看，难看的是没有的那些天。

---

## 8. 今天立的引用形状规则（`coordination/claim_shape_rules.md`，十三条）

每条都标了逼出它的那次事故 —— **删掉事故那一列，规则就会被当成官僚手续绕过**。

1. 可比性六条并列（帧域/基线/对宇宙/尺度/段标签/窗口规则），缺一条不许比
2. 极值不是分布量（要值 + 帧号 + 邻域计数 + 窗口规则）
3. 窗口规则必须「先于数据可判」（`preregistered` / `segment_ratio` 可作判据；`post_hoc` 只作解释）
4. 「对切点稳健」由函数算（`cut_sensitivity`，且**两段都算**）
5. 等级列：同表并列 = 给严重性赋值（现行 / 潜在 / 潜在且入口不存在）
6. 路径标签比「已验/未验」有用（记录走了哪一档、跳过了哪一档）
7. `UNMEASURED` 不是 `FAIL`
8. 「标志位」不是「行为」；判决只在交付出去那份字节上读重放差
9. **读数分数据层与求值层**
10. 「用记录」还是「用拒绝」：看**拒了还能不能补**
11. `UNMEASURED` 不许写成 `FAIL` —— **对工具也一样**
12. 脚本调 `coordination`：**先验根、再 import**（根算错仍只抛 `ImportError`，形状与模块不存在一样）
13. 快照账本必须在**干净 checkout** 上可复现（对着 git 视角验，不对工作树验）

---

## 9. 账本与冻结物（可逐项复核）

复跑：`python -m coordination.artifact_audit --root <树> [--base <目录>]`

| 树 | manifest | 项 | 结果 |
|---|---|---|---|
| `1号` / M08 | 6 份（`frozen/`、`digestwarm_frozen/`、`firsteval_frozen/`、`run_2026…/frozen/`、`recompute_frozen/`、`recompute_frozen_v2/`） | 18 | 全对：无缺件、无哈希漂移、无未登记文件 |
| `2号` / M04 批次 | 1 份 | 35 | 全对（`--base` 指向 `out/` 批次目录；`two_way_checked=false` 已如实记） |
| `3号` / M05 批次 `20261116_324` | 1 份（今晚补） | 14 | 全对；只读 5/14（只有 `.blend` 是 `0o444`，9 份记录可写） |
| `4号` / M07 | 0 份 | — | 件在 `run/` 下无冻结 manifest；他自查 `git ls-files` 18/18 齐 |

汇总：`reports/subai/coordination/artifact_audit_20261116.json`

---

## 10. 明天（按优先级）

1. **`4号`**：按 `D-228` 拆判词已落（`54061f3`）；补 `replay_probe.frames ⊆ [frame_start, frame_end]`（越界 ⇒ `replay_unmeasured`；口径归 `2号`）。
2. **`2号`**：`compare.log` 快照修复 + 测试改问 git（`git ls-files --error-unmatch`）；`302..354` 全套标 `post_hoc`；结论句只引 `f1..240` 同域那组。
3. **`1号`**：S8 第三层；`diff_body` 只加记录字段（**不加断言**）；`warm_scene()` 已在冒烟里量到「冷读 ≠ 热身读 0.871 m、两次热身逐位相同」。
4. **`3号`**：建 NLA 入口前必须先预热求值（否则对齐量偏 1.8 m 且全绿）；四条 `UNMEASURED` 不变。
5. **Human**：`T3` ② 定义（默认按（一））。

---

## 11. 收尾状态

- main HEAD、最终测试数、三项对账的最终读数，见报告末尾**收尾补记**（在本文件最后一次提交时写入）。
- 四席工作树：`1号`/`3号`/`4号` 干净；`2号` 有 3 个未提交文件（正是 §6.5 的修复）。
- 锁：空闲，0 个 Blender 进程。

### 复跑清单（从零验证今天的结论）

```powershell
cd 'E:\dsh pr\woker2'
git log --oneline -1                                   # HEAD
python -m unittest discover -s tests -t tests -p 'test_*.py'   # 902 tests
python -m coordination.status --check                  # state=OK / pending_human=[]
python -m coordination.taxonomy --check                # state=OK / records=230
python -m coordination.artifact_audit --root 'E:\code\mmdpipe-ai\A1\out\subai\M08'
python -m coordination.artifact_audit --manifest 'E:\code\mmdpipe-ai\A3\out\subai\M05\arms\20261116_324\manifest.json'
git diff --name-status ae9ef4f HEAD                     # 今晚全部改动
```

---

## 12. 收尾补记（本文件最后一次提交时写入）

### 12.1 终局读数（全部当场跑出来的，不是抄的）

| 项 | 读数 | 命令 |
|---|---|---|
| main HEAD | **`6d657bd`**（`Merge branch 'ai/a2'`） | `git log --oneline -1` |
| 测试 | **902 passed / exit 0**，默认、utf-8、gbk **三环境各跑一遍**（skipped 1，Blender 不可用那条） | `python -m unittest discover -s tests -t tests -p 'test_*.py'` |
| 裁决 | **230 条**，`state=OK / bad_supersedes=[] / unknown_decision_kinds=[]` | `python -m coordination.taxonomy --check` |
| 状态对账 | `state=OK / conflicts=[] / pending_human=[] / task_count=9` | `python -m coordination.status --check` |
| 四支分支 | `ai/a1` `ai/a2` `ai/a3` `ai/a4` **ahead 全部 = 0**（一支不落、全部并入 main） | `git rev-list --count main..ai/aN` |
| 今日提交 | **421** 笔（含 18:00 之后 57 笔合并提交） | `git rev-list --count --since='2026-11-16 00:00' main` |
| 最终合并 | `39dc480`→`5a9bd72`→`aff6119`→`1ac05f5`→`b1753ed`→`4a4242c`→`5a9bd72`… →**`e913b4f`**→`a0bf2fd`→**`6d657bd`** | `git log --merges --oneline --since='2026-11-16 18:00'` |

### 12.2 收尾最后 40 分钟新增的三条读数（都是当晚量出来的，不是推理）

**① `blender -b` 里 `SystemExit` 没有被吞 —— `rc=0` 是另一回事。** `3号` 先报「Blender 吞了 `SystemExit`」并据此把 `return 2` 改成 `raise RuntimeError`；`4号` 用同一条七形状实验推翻了这个理由：

| 形状 | rc |
|---|---|
| `--python-expr "raise SystemExit(3)"` | 3 |
| `--python-expr "import sys; sys.exit(7)"` | 7 |
| `--python <file>`，`sys.exit(main())`，里面 `raise SystemExit(4)` | 4 |
| `--python <file>`，`SystemExit(5)` 抛在两层函数里 | 5 |
| `--python <file>`，`main()` **`return 2`**，末尾只写 `main()` | **0** ← 真正的原因 |

四个码各不相同 ⇒ `SystemExit` 逐字带出。`0` 那一行是 **`--python` 文件的返回值没有任何人接**，`return` 是本地行为。**两种形状修法不同：抛异常 vs `sys.exit(main())`。** `3号` 读到后当场认错并改（`0888ba7`），这正是今天第 N 次「结论对、理由错」的更正 —— 理由会被别人引用，结论不会。

**② 由此定下码段分带（归我裁，因为是协调层与模块层共用退出码空间）。** `coordination.lock` 占 2 用法 / 3 冲突 / 4 不可判定 / 5 guard 期间锁丢失，而 `guard` 透传命令 rc ⇒ 脚本侧若也用 2/3，「脚本拒绝覆盖」与「锁被别人占着」会是同一个数。裁定：**Blender 侧探针自己的语义码从 10 起**（10 拒绝覆盖 / 11 输入或身份对不上 / 12 断言不成立），`--python-exit-code 3` 只作意外异常兜底。`2号` 当场落成 AST 扫描测试（`122947c`，存量 7 支钉成棘轮清单 + 两条负控），`3号` 的守卫前置到 `main()` 最前面。

**③ 验收断言从一条扩成三条。** `3号` 提「`git status --porcelain` 必须为空」→ `4号` 补「对 git 视角验会漏掉不在 git 里的东西，`out/` 里的读数 git 帮不上」→ 合并成：

> `git status --porcelain` 为空 **且** 目标 `sha256` 前后同值 **且** 目标确实存在（打印 `size`/`mtime`）。
> 第三条是必需的：目标不存在时「sha 同值」是空集，会把「守卫没触发、什么都没干」读成通过。

### 12.3 规则第十三条当场扩写（`coordination/claim_shape_rules.md`）

三个席位在同一小时里各自提了一条措辞，我合并后落盘：

- **范围**从「快照账本」扩成「**凡报告要别人复跑的东西 —— 脚本、日志、账本、生成链一律 —— 都对 git 视角验，不对工作树验**」；事故表补 `3号` 六个控制脚本、`4号` 探针两例（今晚共四例，三个席位 + 一人两次）。
- **新增附块一**：镜像≠同步（清单要写明镜像的是当时那份）；能重建≠该重建（默认输出是交付证据时必须拒绝覆盖，且**每一处副作用都要跟着 `--out` 走** —— `3号` 一次「只验证一下」就把已提交的 `gate_m05_attempt11.json` 改了一个路径）；对 git 视角验会漏掉不在 git 里的东西（`out/` 只能靠脚本自己守）。
- **新增附块二**：退出码不证明发生了什么（七形状表）+ 码段分带约定。

### 12.4 账本操作上的一处如实记录（我自己踩的）

`D-230` 的 `decision_id` 被我写成了自动编号 **`D-20261116-NEW-200930`** —— 因为这次调用 `taxonomy.append()` 时**没传 `decision_id`**，`validate()` 里 `setdefault` 就自动发了一个。后果两条：

1. **号段不连续**：`D-229` 之后不是 `D-230`，读的人会以为少了一条；
2. **`new_decision_id()` 只精确到秒**（`%H%M%S`）⇒ **同一秒内追加两条会撞号**，而 `supersede_map` 用 id 建索引 ⇒ 撞号会让「谁更正了谁」变成一对多。

按今晚第十条（`用记录` vs `用拒绝`：看拒了还能不能补）这条属**能补**的一类：不改历史行，明天给 `append()` 加一条「自动 id 必须查重/撞号即自增」的守卫 + 一条测试。**我没有改写历史行**（append-only 是这条账本的立身之本）。

### 12.5 本轮封版

- 从本文件提交的那一刻起，**我不再合任何分支**；四支 ahead 全 0 是封版读数，之后席位若有新提交，明天开工时重新 `fetch` + 重跑三环境再合。
- 锁空闲、0 个 Blender 进程、无未提交文件（除本报告与 `D-230`／`task_status` 的收尾改动，随本文件一起提交）。
- 唯一挂在 Human 身上的一条没变：**`T3` ② 要不要改定义**（默认按（一），认 `T2` 为天花板，已写进 `task_status`）。

