# M05 模块书逐条复核（只读，2026-11-16）

> 复核基线：main `5cf1241`。M05 六个文件的 blob 与入库 `e205151` 相比只有
> `chainplan.py` / `concatvmd.py` / `tests/test_chain.py` 变过，那三处全是 D-040（gap 默认值同源 + 预检两列）。
> 本文件是 Thread 里那张表的存档版，字段：条目 / 现状 / 证据 / 对 M08 的影响（仅「部分」「没有」写）。

## 结论

- **丢段**：§6 四条 4/4 全绿 → **PASS**（D0 已按此落裁决）。
- **NLA 姿态**：§6 只到 1 绿 / 1 部分 / 2 没有 → **PARTIAL**，不得写 PASS。
- 缺口里对 M08 出片有影响的三条：**F2**（runner 单段/无预设无自动化测试）、**§1-3**（导出→Blender 重导入未验）、**E5**（不同交接位置未确认）。

## §1 完成口径

| 条目 | 现状 | 证据 |
|---|---|---|
| splice 三段帧数与记录守恒 | 已实现 | `vmd.py:277` 游标累加；实跑 plan 337 帧；`test_plan_three_segments_is_337`、`test_bone_records_conserved`；`chain_fixed_337{,_b}.vmd` sha 均 `38b788f7…` |
| NLA N>2 写文件前 BLOCK | 已实现 | `chainplan.py:29,47`；`runner.py:463,466`；实跑 `nla_segments_check(3)` → `(False, …)` |
| NLA 坏姿态定位到具体一层 + 最小复现 | **部分** | `chain_nla.py:185-202` 帧映射层，f846 差 1.00696 m → 修后 ≤0.00007 m、导出对照 0.0000；**导出重导入未测**、`blend>gap` 未测、f1 12.96 mm 未查 |

**M08 影响**：splice 不受影响；NLA 路线「姿态正确」只能声明到数据层。

## §5-A 帧账本

| 条目 | 现状 | 证据 |
|---|---|---|
| A1 复原命令/参数 | 已实现 | `frame_ledger_baseline.json` + `result.md` §2 |
| A2 输入 VMD 的 sha256/首末帧/记录数/尾部轨道 | **部分 → 本轮补** | 起始哈希 11-15 未记（过程失误）；本轮补 `source_hashes.json`（fixtures 可逐字节重建；源文件只给今日值 + mtime 佐证，不写成「起始哈希已补」） |
| A3 纯 Python 期望账本 | 已实现 | `out/subai/M05/ledger.py` |
| A4 断言 337 + 截断与丢段分开 | 已实现 | `concatvmd.py:27-30`、`test_explicit_truncation_is_not_loss` |
| A5 actual/rendered 计数 | **部分** | chain 侧有；`rendered_frames` 只有 2 帧那次 |
| A6 首个丢失阶段 | 已实现 | `vmd.concat` 自动 offsets |

**M08 影响**：A2 属证据链缺口（本轮补到「今日值 + 可重建性」为止）；A5 在短区间验收下不阻塞。

## §5-B 回归

| 条目 | 现状 | 证据 |
|---|---|---|
| B1 `tests/test_chain.py` 先失败后修 | 已实现 | 20 条 |
| B2 七类覆盖 | **部分** | 六类有对应测试；「表情/IK 轨道跟随偏移」在本机 `skipped=1`（缺样本），即该类只在有样本的机器上验过 |
| B3 junctions 扩展 + 兼容说明 | 已实现 | `chainplan.py:220,231`；`m07_interface.md §8` |

**M08 影响**：B2 的 skip 意味着「尾部轨道随偏移保留」可能未在本机验过，M08 机器上应复跑。

## §5-C 消除静默丢段

| 条目 | 现状 | 证据 |
|---|---|---|
| C1 修首个不一致位置 | 已实现 | `vmd.py:274-277` |
| C2 N>2 BLOCK | 已实现 | 同 §1 |
| C3 禁止「只渲前两段报成功」 | 已实现 | `runner.py:463-466`、`520-526` |
| C4 state 五帧字段 + 每段 span | 已实现 | `runner.py:482-484`、`503-512`、`488`/`506`、`737-742` |
| C5 守恒断言 | **部分** | 断言在，但只有 Blender 实跑验证过字段，无自动化 bpy 测试 |

**M08 影响**：C5 是回归风险——断言被改坏时纯 Python 回归抓不到。

## §5-D 短探针

| 条目 | 现状 | 证据 |
|---|---|---|
| D1 导出后重新解析核对 | 已实现 | `chain_fixed_337.vmd` 337 帧 / 18196 条 |
| D2 短渲染核对 | 已实现 | `out/subai/M05/probe2_tail/`（ok/final true） |
| D3 独立确认 sha256 | 已实现 | 两次均 `38b788f7…` |
| D4 交接处对比图 | **没有** | `out/subai/M05` 下无任何 png/jpg |

**M08 影响**：视觉证据缺一项；若 M08 要求图像证据必须补。

## §5-E NLA 最小复现

| 条目 | 现状 | 证据 |
|---|---|---|
| E1 splice 对照 + NLA 复现 | 已实现 | `splice_ref_gap20.vmd` vs `nla_export_run1.vmd`；run1/2/4/5 |
| E2 各阶段世界测量 | **部分** | run5 六阶段逐帧有（含 `センター`/`頭`）；**脚只有 `feet_delta_mm=351.46` 聚合**；**导出重导入未做** |
| E3 动作活性自检 | **部分** | 数据够反查，但没落成字段或断言 |
| E4 只改该层 | 已实现 | run4 无效 → run5 只改四值 |
| E5 短区间对照 + 不同交接位置 | **部分** | 短区间对照有；**不同交接位置全仓无记录** |

**M08 影响**：E2/E5 是外推风险（单交接点修好 ≠ 别的点也对）；E3 缺失使「动作是活的」靠人读。

## §5-F 回归收尾

| 条目 | 现状 | 证据 |
|---|---|---|
| F1 跑 test_chain/test_vmd/test_align | 已实现 | `Ran 34 tests, OK`（main `5cf1241`） |
| F2 无预设、单段 `--vmd` 自动化测试 | **没有 → 本轮补参数层** | 新增 `tests/test_runner_args.py`（8 条，打桩 bpy，**只覆盖参数层**）：单段 `--vmd` 无 `--preset`、`--motions`、preset 透传、缺 `--pmx` 被拒、无 `--` 分隔被拒、默认值等同 `params.add_arguments` 生成的解析器、`_parse_args` 无手写 `add_argument`。**不代表单段路径已跑通**——那要 Blender 实跑（排下一个锁窗口，与 D4 一起） |
| F3 NLA 限制写进帮助与验收文档 | 已实现 | `chain_nla.py:274`；`handoff.md`、`m07_interface.md §5` |
| F4 报告写最后正确/首个错误阶段 | 已实现 | `handoff.md` §2/§3 |

**M08 影响**：F2 原状直接压在出片上（改过 runner 而无单段回归）；本轮只补到参数层，**真行为仍需一次 Blender 跑**。

## §6 验收标准

- 丢段 PASS 4 条：① 337 一致 ✅ ② 首末帧/记录数/交接对/渲染帧数可追踪 ✅ ③ N>2 BLOCK ✅ ④ 单段+两段旧路径回归 ✅
- NLA 姿态 PASS 4 条：① 根/脚/头差异有数值 → 部分（脚只有聚合）② bake Action/slot/帧范围/导出重导入 → 部分（重导入没有）③ 悬空坐姿视觉复现 → 没有（无坏样本）④ 状态词不冒充 ✅

## §7 回报

`frame_ledger_{baseline,final}.json` ✅ / `nla_stage_probe.json`（+run1/2/4/5）✅ / `changed_files.txt`+`reproduce.md`+`handoff.md` ✅ / 给 M07 参数兼容说明 ✅（`handoff.md` + `m07_interface.md`）/ 给 M08 三段验收命令与预期帧数 ✅（`handoff.md`「给 M08 的验收」）
