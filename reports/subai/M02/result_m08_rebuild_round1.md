# M02 · M08 交付场景重建 · 第一轮（2026-11-16 17:52–17:56）

**状态：重建完成、闸门 WIRED、正控与负控都有读数；但「交付尺度」这一次仍然只到 312 刚体，
不是交付物的 324。** 本轮不写 T3（按总控 17:49 第 5 条：重建只是产出物就位，T3 归 2号 的 C/D 轮）。

## 0. 次序（总控 17:49 五步，一步未跳）

| 步 | 动作 | 结果 |
|---|---|---|
| 1 | `git merge --no-ff main` → A1 `4153a68` | `provenance.py` / `preflight --spec utf-8-sig` / `stage.constraint_limit()` 三者均在树 |
| — | 三环境测试 | **569 / OK (skipped=1) / exit 0** × 3（默认 / utf-8 / gbk） |
| 2 | `m02_make_m08_spec.py` 现算 cap → `coordination.preflight` | **`READY`**：`needs=8298 ≤ cap=10111`、`skipped=0`、`provenance` 4 项在 A1 树内、`lease` 持锁 |
| 3 | `coordination.lock acquire`（17:52:00，owner `模块负责1|A1`） | 全程只有我这一个 Blender 进程 |
| 4 | `m02_build_delivery.py`（`MMDPIPE_TREE=A1`）→ 回读 → 探头 | 见下 |
| 5 | `release`（17:56） | 锁回到 `空闲`；本轮不取锁 |

`cap` 不是手写的：`m02_make_m08_spec.py` 用 AST 取 `stage.constraint_limit()` 源码
（`sha256 = 8e8fb042…`），核对它引用 `mask.DEFAULT_MAX_CONSTRAINTS`（= 20000）且保留
「`max_constraints is None` ⇒ 上限 = 需求」分支，再按该分支算 `cap = 10111`（`guardrail_hit=False`）。
核对失败即退出码 2，不产 spec。

## 1. 产物（`out/subai/M08/`，文本件已复制到 `reports/subai/M02/m08_round1/`）

| 文件 | 字节 | sha256 |
|---|---:|---|
| `rebuild_import.blend`（只导入，未建物理） | 4 851 008 | `cb1b666820636135…` |
| `rebuild_built.blend`（**本轮读数对象**） | 5 929 823 | `e77851abaf43408bd0006e645cdd393d754cb78c79b59d8c65ba7e180d6c3321` |
| `build_identity_20261116_175218.json` | 1 064 | `ecbcdb5adeb72174…` |
| `readback_after_rebuild.json`（含 `mask_wired` 全记录） | 95 731 | `8ed352edfef71c19…` |
| `stage_mask_after_rebuild.json`（喂探头的 ④ 条件） | 314 | `fb022a72621e5ba1…` |
| `mask_probe_wired.json` / `mask_probe_import_only.json` | 3 888 / 2 248 | `49d132bf…` / `a4010e82…` |
| `rebuild_report.json` | 4 035 | `b56348ebf8d7413a…` |

代码身份（identity 记录内，且与本次命令行一致）：`stage.py = 502b3761c3d0efe5…`、
`mask.py = c5f475b064c7fbf1…`、wrapper `99bfc05e0f5eb61e…`、v3 `ea89a10fff871df9…`、
Blender 5.2.2 / Python 3.13.13、`stage_inside_tree=true`。

## 2. 交给 2号 的四样（总控 17:49 第 4 条）

1. **产物**：`E:\code\mmdpipe-ai\A1\out\subai\M08\rebuild_built.blend`，
   **5 929 823 B / `e77851abaf43408bd0006e645cdd393d754cb78c79b59d8c65ba7e180d6c3321`**
   （取读数前后各核一次；本轮只取了一次，第二次核在你手上跑之前）。
2. **`--expect wired` 退出码 = 0**：
   `VERDICT WIRED  patterns=30  disallowed_pairs=36608  separated=36608  exit=0`。
3. **`stage_mask()` 三元组**：`verdict = WIRED` / `constraints_capped = false` / `skipped_count = 0`，
   `verdict_reasons = []`；同一份场景记录里 `constraints_needed=8499`、
   `constraints_added=6686`、`constraints_already_blocked=1813`、
   `constraints_to_add=6686`、`readback_mismatch=0`、`guardrail_hit=false`、
   `constraint_creation=template_copy` —— **恒等式成立：6 686 + 1 813 = 8 499**。
4. **`is_baked` 回读**：`point_cache.is_baked = false`、`is_outdated = true`，
   `cache_state.evaluate() = {verdict: "OK_UNBAKED", exit_code: 0}`（未烘、非回放）。

**负控（同一支探头、同一份 stage json）**：`rebuild_import.blend`（只导入未建物理）⇒
`VERDICT UNWIRED  patterns=1  disallowed_pairs=36608  separated=0  exit=1`
（理由：「位型只有 1 种」「仍有 36608 对没有分开」）。
⇒ **同一个判据在「接了」上是 WIRED、在「没接」上是 UNWIRED**，不是恒绿。

## 3. 三个缺陷（都当场上报，不改别人的脚本）

1. **`m02_build_delivery.py` 假定 `out_dir` 已存在**：`out/subai/M08` 不存在时
   `write_json` 抛 `FileNotFoundError`，**而 Blender 仍返回 0**（`D-135` 那族）。
   本轮手工 `New-Item` 之后才跑通；脚本未改（它是被 identity 记录过 sha 的件）。
2. **`tests_bpy/m08_accept_probe.py` 在真场景上序列化失败**：
   `TypeError: Object of type IDPropertyArray is not JSON serializable`（exit 3，采集器自己的守卫起作用）。
   原因是 `scene["mask_wired"]` 里的 IDProperty 容器直接进 `json.dump`。
   本轮另写 `m02_m08_readback.py` 只补「压成可序列化 + 回读」，没有改 4号 的脚本。
3. **`m02_rebuild_scene_v3.py` 用 `os._exit(0)` 收尾** ⇒ wrapper 永远来不及把 identity 记录写成
   `completed`，本轮记录里 `outcome` 停在 `started`。**换句话说这份 identity 分不出「跑完」与「跑到一半死了」**——
   本轮「跑完」的证据是 `.blend` + `rebuild_report.json` 的 `is_built: true`，不是那个字段。

自报一条我自己的读法错误：第一次回读 `stage.rigid_bodies()` 得 **0**，因为
`mmd_type`/`mmd_rigid` 这些 RNA 属性**只在扩展 enable 之后才存在**；enable 之后 u323 = 312。
「读不到 ≠ 不存在」——这次是我踩，记在脚本注释里。

## 4. 三个数字要对账（**同一棵树上的四个数**，4号 18:02 的更正已采纳）

| 数字 | 来源 | 说的是哪个场景 |
|---:|---|---|
| **6 686** | 本轮 `constraints_to_add`（= 本轮真正要建的条数） | **312 刚体（本轮）** |
| 1 813 | 本轮 `constraints_already_blocked` | 同上 |
| **8 499** | 本轮 `constraints_needed`（= 6 686 + 1 813） | 同上 |
| 8 298 | 任务书交付需求（= `10111 − 1813` 的旧口径） | 324 刚体尺度，**不进本轮 preflight** |
| 10 111 | 4号 的 `constraint_limit(10111)` 读数 | 324 刚体尺度 |

**本轮 preflight 的字面读数**（`out/subai/M00/preflight_delivery_spec.json`，由产物现算、不手抄）：
`needs=6686 ≤ cap=8499`、`skipped=0`、`guardrail_hit=False`、`READY`。
（早先我用 `needs=8298` 配 `cap=8499`，那是**两棵树拼数**——4号 指出后已改成同源。判词不变，但数换了。）

重建仍只得到 **312** 刚体（`rebuild_finding.md` 记过的缺口：11 个 `$name_j` 占位体 + 地面，见
`m08_gap324.md`）。所以 **本轮 WIRED 只能证明「通道在今天的代码上能接通并判绿」，不能替代交付尺度上的 WIRED**。
这一条与 2号 的准入 ② 直接相关：他在 312 刚体上跑 C/D，读数要写明尺度，
不能写成「交付件上的 8298 条已验」。

## 5. 未做到（不许读成已验证）

- **「应用动作」不在本文件范围内**：`D-186` 判给 M05（3号），实现是 `mmdpipe/apply_action.py`（复用 `stage.py:1009` 的 `stage_motion`，不复制第二份）。
  我在本轮曾写过一个**未跑过**的骨架 `m02_make_delivery_actions.py`（`7e8d80b` 里进过 git），
  按「交付链只许一份实现」已**删除**（提交信息见 `git log --grep=骨架`）——所以本树里不存在第二份应用动作的实现，
  本报告也不引用它的任何读数（它从未产出过读数）。

- 交付尺度（324 刚体 / 8 298 条）**没跑**：卡在场景重建缺口，不在通道；
- `bake` 仍然没有：本轮 `is_baked=false` 是**未烘**，`D-153` 说的契约 B 依旧没实现
  ⇒ 交付件按 `s8_prereg_v2.1.md` §1.1 仍属**不合格件**（这一点已写进 S8 §P0）；
- `m08_accept_probe.py` 没修，M08 的机读采集仍缺一条路；
- 本轮只取了一次 sha，`D-126` 要求的「取读数前后各一次」留给 2号 在真读数时做。
