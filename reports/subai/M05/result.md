# M05 · 三段拼接丢帧与 NLA 坏姿态 · 回报

## 1. 结论

- 模块：M05（拼接修复 AI）
- 状态：`PARTIAL`（三段丢帧 PASS；NLA **帧偏移层**已定位并修复且数据层对齐；「悬空坐姿」视觉未复现）
- 完成范围：
  - `vmd.concat` 自动偏移游标修复（244 → 337）
  - `chainplan` N 段全交接对 / 帧账本 / NLA 段数门禁
  - `runner` 帧数守恒字段 + NLA N>2 写文件前 BLOCK + **`paths` 变量遮蔽导致的收尾崩溃**
  - `chain_nla` 交叉淡化帧映射修复（`extend_upper_strip`）
  - 15 条纯 Python 回归；Blender 侧 1 次 12 帧探针、4 次 NLA 分阶段探针、1 次 NLA 导出对照
- 未完成范围：悬空坐姿的同机位视觉复现（无原始坏样本）；导出再导入 Blender 的世界姿态
- 实验计数：丢段基线 1/2；丢段修复 3/3（含独立确认）；12 帧探针 2/2；NLA 基线 2/2；NLA 同层修复 2/2；全量回归 3 轮（超出 1 轮，只重跑全绿套件，未改测试）
- 是否触及停止条件：**是**（探针与修复预算用尽），剩余项转 `BLOCKED` 并留证据

## 2. 基线与源文件保护

| 文件 | mtime | SHA256（复算） | 只读 |
|---|---|---|---|
| 卡芙卡3.0.pmx | 2023-07-19 19:37:49 | 287a5556…6de51f0e | 是 |
| 原神摇.vmd | 2026-10-25 07:50:35 | a2e5f978…f7754a0 | 是 |
| 活着dj_VMD-TDA.vmd | 2026-11-02 18:01:40 | 7ed53b14…14573798 | 是 |

说明（过程失误）：开始时没先记哈希，只记了结束值；只读性由 mtime 全部早于本日 + 无写源路径兜底。
Blender 只写 `out/subai/M05/` 下的新目录。

## 3. 实际改动

| 文件 | 改了什么 | 为什么 |
|---|---|---|
| `mmdpipe/vmd.py` | `concat` 自动 offsets 累加自身偏移；返回 `total_frames` | 原式少加 offset，三段时 offsets `[0,93,93]` |
| `mmdpipe/chainplan.py` | 段首偏移纳入 span；每相邻对一条 `junctions`；`nla_segments_check()` | 只比前两段，第 2/3 段交接无人检查 |
| `mmdpipe/concatvmd.py` | `frames=` 与显式截断记账 | 把「截断」与「丢段」分开 |
| `mmdpipe/runner.py` | NLA N>2 写文件前 BLOCK；帧数守恒字段与渲染帧回填；**`paths` → `seg_paths` 防遮蔽** | 原 NLA 分支静默只用前两段；`paths` 被复用成列表，多段跑完在收尾 `paths["final"]` 处 `TypeError` |
| `mmdpipe/chain_nla.py` | 新增 `extend_upper_strip()`：淡化延伸时四个帧值写成恒等映射 | 旧代码把 action 终点也减 shift，B 被压缩 5.5% / 提前 20 帧 |
| `tests/test_chain.py` | 15 条纯 Python 回归 | 见 §5 |

## 4. 实验记录

| 轮次 | 假设 / 目的 | 唯一变量 | 输入 | 数值结果 | 结论 |
|---:|---|---|---|---|---|
| 丢段基线 1 | plan 与 concat 偏移口径不一致 | 无（旧代码） | 91/91/151 gap2 | plan 337；文件 **244**；offsets [0,93,93]；重叠 seg2×seg3；记录 18196 守恒 | 复现 244 |
| 丢段修复 1 | 游标累加恢复 337 | `vmd.concat` | 同上 | 337；无重叠；缺口 0 | PASS |
| 丢段确认 | 两次输出位级一致 | 再跑一次 | 同上 | sha256 均 `38b788f7…758f48` | PASS |
| 12 帧探针 #1 | 端到端验证帧数守恒 | `--factory-startup` | 3 段 gap30 | S2_import 失败（`mmd_tools` 是扩展，factory 启动被禁） | 环境失败，转 #2 |
| 12 帧探针 #2 | 同上 | 去掉 factory 启动 | 同上 | `expected=393 chain=393 requested=12 rendered=12`；渲 12 帧成功；**收尾 `TypeError: list indices`** | 守恒字段 PASS；发现收尾崩溃 |
| 2 帧回归 | 验证 `paths` 遮蔽修复 | `--frames 2` | 同上 | `ok=True`、`final=True`、渲 2 帧、`explicit_truncated_frames=391`、`frame_conservation=truncated` | PASS（成片落 final） |
| NLA 探针 #1 | 无淡化是否已坏 | gap6 blend0 | A+B | 各阶段一致（4_align→6_bake ≤0.00007 m，f1 0.0130 m） | 无淡化不坏 |
| NLA 探针 #2 | 复现坏姿态 | gap20 blend20 | A+B | 条带 `[448,847]`→action `[448,827]`；f846 差 **1.00696 m** | 复现帧偏移缺陷 |
| NLA 修复 #1 | 只前移 action 起点 | 同上 | 同上 | Blender 联动把条带拉成 `[448,867]`→`[448,847]`，误差移到 f847（1.00335 m） | 无效，废弃 |
| NLA 修复 #2 | 四值显式写恒等映射 | 同上 | 同上 | `[448,867]`→`[448,867]`；除 f1 外全部 ≤0.00007 m | PASS |
| NLA 导出对照 | 导出是否与 splice 同源 | 同输入 | A+B gap20 | センター 380 帧、上半身/下半身 827 帧，最大偏差 **0.0000** | PASS（数据层） |

丢段的精确机制：第 1 段后 `cursor=93`，第 2 段后又算成 `cursor=93`（少了 offset），
第 3 段整段写到 93..243，压在第 2 段身上。记录一条没少（18196 守恒），时间轴少了 93 帧。

NLA 的精确机制：交叉淡化要把 B 条带向前延伸，旧代码同时把 `action_frame_end` 减了 shift，
条带 400 帧映射到 action 380 帧 → B 的运动被压缩 5.5%、整体提前约 20 帧、尾部 20 帧不被采样。
表现为交接后整段姿势跟 splice 对不上（f846 差 1 m 级），视觉上就是「人不对」。

## 5. 验收结果

| 验收项 | 期望 | 实测 | PASS/FAIL | 证据 |
|---|---|---|---|---|
| 三段账本总帧 | 337 | 337 | PASS | `frame_ledger_final.json` |
| 基线丢段复现 | 244 | 244（缺口 93） | PASS | `frame_ledger_baseline.json` |
| 每相邻对 junction | 2 | `[[0,1],[1,2]]`，最大 106.5°/112.0° | PASS | `test_every_junction_is_reported` |
| 记录守恒 / gap 空帧 | 18196 / 无 | 一致 | PASS | 同名测试 |
| 表情与 IK 轨道随偏移 | 保留 + 前移 | 123 条表情、IK ≥1，最早帧 ≥93 | PASS | `test_morph_and_ik_tracks_follow_offset` |
| 显式截断 vs 丢段 | 分开记账 | `explicit_truncated_frames=391`、`frame_conservation=truncated` | PASS | `out/subai/M05/probe2_tail/pipeline_state.json` |
| 多段跑完成片落 final | 落 | `final/20261115_213301/result.mp4` | PASS | 同上 `state["final"]` |
| NLA N>2 | 写文件前 BLOCK | `nla_segments_check(3)=False` | PASS | `test_nla_guard_blocks_three_segments` |
| NLA 帧映射 1:1 | 与未淡化一致 | 除 f1 外 ≤0.00007 m；导出与 splice 0.0000 | PASS | `nla_stage_probe.json` |
| 悬空坐姿视觉复现 | 同机位代表帧 | 无原始坏样本，未做 | BLOCKED | — |
| 全量回归 | 全绿 | 71 tests OK | PASS | §6 |

## 6. 复现命令

```powershell
Set-Location "E:\dsh pr\woker2"
python out/subai/M05/make_fixtures.py
python -m mmdpipe.concatvmd out/subai/M05/fixtures/seg1_91.vmd out/subai/M05/fixtures/seg2_91.vmd out/subai/M05/fixtures/seg3_151.vmd --out out/subai/M05/chain_fixed_337.vmd --gap 2
python out/subai/M05/ledger.py --gap 2 --chain out/subai/M05/chain_fixed_337.vmd --out reports/subai/M05/frame_ledger_final.json
python -m unittest tests.test_chain tests.test_vmd tests.test_align tests.test_params tests.test_layout tests.test_statefile tests.test_pmx_patch -v

# Blender 侧（本轮实跑过）
powershell -ExecutionPolicy Bypass -File out\subai\M05\probe12_splice.ps1    # 12 帧三段探针
powershell -ExecutionPolicy Bypass -File out\subai\M05\probe2_tail.ps1       # 2 帧收尾回归
powershell -ExecutionPolicy Bypass -File out\subai\M05\probe_nla5.ps1        # 两段 NLA 分阶段探针（gap20 blend20）
& "E:\code\Blender\blender-5.2.2-windows-x64\blender.exe" -b -P mmdpipe/chain_nla.py -- --pmx "<PMX>" --a "<A>" --b "<B>" --gap 20 --blend 20 --out out/subai/M05/nla_export_run1.vmd
```

`--factory-startup` 不可用：`mmd_tools` 是 Blender **扩展**，factory 启动会禁掉扩展仓库，
`S2_import` 直接失败（已实测）。

## 7. 已知限制与跨模块申请

- 未验证：悬空坐姿的视觉复现（无原始坏样本；只用数值证明帧映射缺陷，未做同机位 A/B 图）。
- 未验证：导出再导入 Blender 的世界姿态（本轮只比到「导出文件 vs splice 文件」）。
- f1 处 bake 与 bake 前差 12.96 mm（只影响首帧），未查。
- `blend > gap`（淡化比空档长）未测：此时 `extend_upper_strip` 会让 B 提前覆盖 A 尾部。
- 跨模块：`mmdpipe/runner.py` 的 `paths` 遮蔽是**所有多段拼接**共有的收尾崩溃，M07/M08 的
  端到端必须用带 `--motions` 的用例才能覆盖到；建议 M08 把「多段跑完 state.final 非空」列进 D 表。
- 接口：`chainplan` 旧字段 `pose_diff` 仍是第一个交接对；M07 面板若展示 N 交接请读 `junctions`。

## 8. 下一步（只给一条）

- 让 M08 用 `--motions` 跑一次 12 帧三段 E2E 并断言 `state.final` 非空；悬空坐姿若仍要闭环，
  需先找到当时的坏样本渲染或 `scene.blend`，否则只能停在「帧映射已修」这一层。

## 9. 提交登记（2026-11-16 · A3 / 模块负责3）

- 提交：`e205151`，父 `d54f3c8`（M03），基线 `7f764ea`。入版本 5 个文件：
  `mmdpipe/chainplan.py` `chain_nla.py` `concatvmd.py` `runner.py` `tests/test_chain.py`（+370 / −69）。
- 回归：`python -m unittest discover -s tests` → Ran 117 tests, OK, exit 0。
- 归属说明：`vmd.py` 的 9 行游标累加修复由 模块负责1（A1）在 `7f764ea` 一并提交，
  M05 只承接其测试基线、未重复改动；`test_chain.py` 中依赖该修复的用例因此在该提交之后才全绿。
- 源只读复核（提交前后一致）：卡芙卡3.0.pmx `287a5556…6de51f0e`、原神摇.vmd `a2e5f978…f7754a0`、
  活着dj_VMD-TDA.vmd `7ed53b14…4573798`。
- 未 push、未 merge。历史事故（amend 造成的两次「内容/信息不符」）已由总控记 W2，本报告不重复辩解。
