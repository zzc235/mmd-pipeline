# M05 真跑证据：B（单段无预设）+ D4（交接处对比图）

日期 2026-11-16 · 车道 A3 · worktree `E:\code\mmdpipe-ai\A3` · 分支 `ai/a3` · HEAD `247ccfd`
全部在 Blender 5.2.2 LTS 真跑，**不含任何桩**；参数层（`_parse_args`）的桩测试在 `tests/test_runner_args.py`，两者不互相冒充。

取锁一律 `python -m coordination.lock acquire/release --owner "模块负责3|A3"`；每次 run 单独取锁，抢不到就退出。
三次 run 的 `--probe` 全程未开，12 帧探针预算没有再消耗。

---

## 1. B：单段 `--vmd`、不带 `--preset`

缺口的原话是「runner 单段/无预设路径没有自动化测试」。参数层已由 `tests/test_runner_args.py`
（8 条）覆盖；这一笔补的是行为层。

```
blender -b -P E:\code\mmdpipe-ai\A3\run_pipeline.py -- ^
  --pmx <卡芙卡3.0.pmx> --vmd out\subai\M05\fixtures\seg1_91.vmd ^
  --out out\subai\M05\probe_single --frames 2
```

| 项 | 实得 |
|---|---|
| 退出码 | **0**（`PIPELINE_EXIT=0`） |
| 墙钟 | 11.8 s |
| run_id | `20261116_140739` |
| 阶段 | 15 个阶段全 ok，**没有 `S3_chain` 阶段**（单段本来就不该有链式账） |
| 帧账 | `frame_start=1`、`frame_end=2`、`fps=30`、`resolution=[720,576]` |
| 渲染 | `frames_rendered=2`，`png_count=2`，`mp4_frames=2`，`duration_delta_s=0.0` |
| 落地 | `final/20261116_140739/`（ok 才落地，见 runner.py L758-765） |
| 判据脚本 | `verify_single.py` → **8/8 PASS**（`probe_single_verify.json`） |

过程中的三条 issue 都是**已存在的基线警告**，不是这次引入的：`E-05` 2 个刚体单元结构僵死（右ひじ/左ひじ）、
`E-00` 没匹配到裙/配件刚体（0.75/0.25 未施加）、`G4` 片段仅 2 帧不足判静止（跳过）。

**这一笔证明了**：单段 + 默认预设 + 短截断这条路能跑通、能过 S8 校验、能落地 final/。
**这一笔没有证明**：长片（2 帧判不了静止也判不了物理）、`--preset` 自定义、NLA 路线、多段拼接（那在 D4）、
物理活性（`--probe` 未开）。

产物：`out/subai/M05/probe_single/`（`pipeline_state.json`、`work/20261116_140739/frames/s_0001.png|s_0002.png`、
`final/20261116_140739/result.mp4`）、日志 `probe_single.log`、复现脚本 `probe_single.ps1`。

---

## 2. D4：交接处对比图

### 2.1 三次跑，三种结局

| # | 参数 | 退出码 | 墙钟 | 渲染 | 落地 |
|---|---|---|---|---|---|
| 1 | `--motions 3 段 --frames 94`，gap 缺省 | **2** | 1.8 s | **0 帧** | 无 |
| 2 | 同上 + `--force`，`--frames 120` | **3** | 73.8 s | 120 帧 | **无**（未通过不落地） |
| 3 | 同上 + `--chain-gap 22`，`--frames 120` | **0** | 73.2 s | 120 帧 | `final/20261116_140939/` |

第 1 次是被自己的确认门拦下的，原文（`runner.py` L444-454）：

```
× E-16  过渡太快：最大骨差 106.5° 压在 1 帧里（112.0°/帧），建议 --chain-gap ≥ 22 或 --force 显式放行
```

`E-16` 是 `report_mod.BLOCK`，BLOCK 阶段 `record()` 为假时 runner 直接 `return 2`（L266-269），所以一帧都没渲染。
退出码的两种语义在这三次里都出现了：**2 = BLOCK 早退，3 = 跑完但未通过**。

### 2.2 帧账（第 3 次，gap=22）

```
expected_total_frames 377 / chain_total_frames 377   （plan 与文件一致 = 没丢段）
requested_render_frames 120 / rendered_frames 120    （没少渲）
explicit_truncated_frames 257                        （显式截断，不是丢段）
```

`377 = 91 + 91 + 151 + 22×2`。gap=0 时是 333，`spans = [[0,[0,90]],[91,[91,181]],[182,[182,332]]]`。

### 2.3 像素步差：那 22 帧空帧到底有没有用

只看渲染像素（骨点会被 IK 拉偏，包围盒轴对齐且含静止姿态，见仓库 AGENTS.md 第四条）。
指标 = 相邻帧灰度平均绝对差（`measure_frame_step.py`，0..1 归一）。

| 运行 | 窗口 | 最大步差 | 位置 | 相邻常态 |
|---|---|---|---|---|
| gap=0（`--force`） | f88..f95 | **0.016621** | **f91→f92**（交接） | 0.0032–0.0060 |
| gap=0（`--force`） | 同上 | 0.003849 | f90→f91 | — |
| gap=22 | f89..f95 | 0.004263 | f90 | 0.0029–0.0043 |
| gap=22 | f110..f118（空帧带 + 段2 起手） | 0.007312 | f117→f118（段2 内部动作） | 0.0026–0.0073 |

结论两条：

1. **gap=22 真的把跳变摊平了**，不是把它挪到后面——空帧带 f111..f114 的步差 0.0036–0.0039，
   和段内常态同量级；而 gap=0 在 f91→f92 那一步是常态的 **4.3 倍**（0.0166 / 0.0038）。
2. **E-16 的「°/帧」算法被像素支持**：它用 `106.47° / (gap+1)` 估算过渡速度，`recommended_gap=22`
   与 E-16 的建议值 22 完全一致——`plan()` 里这两个来源没有分叉。

### 2.4 图

`out/subai/M05/junction_compare.png`（1762×598，3 行 × 9 格，格 190×152，由 `make_junction_compare.py` 生成）：

- 第 1 行 `gap=0 --force` f88..f96：f91（垂手）→ f92（手已到头顶），交接处最陡；
- 第 2 行 `gap=22` f88..f96：同一窗口内还是垂手——这些帧落在 f92..f113 的空帧带里；
- 第 3 行 `gap=22` f112..f120：f113 仍是垂手，f114 起段2 的手逐步抬到头顶，**跨 22 帧摊开**。

缩略图上第 2、3 行的差别很容易看错，判断只认上面的像素步差数字（缩略图 190 px 宽看不出 0.004 级的差）。

---

## 3. 顺带查出的两件事（给 D0，别读成我改过行为）

1. **默认 gap=0 在 3 段链上是一条 BLOCK 路径**（exit 2、1.8 s、一帧不渲）。远因不是 D-040：
   runner 的 `--chain-gap` 默认值一直来自 `params.py` 的 `Param("chain_gap", "int", default=0)`，
   D-040 只统一了 `chainplan`/`concatvmd` 的默认值，没动 runner。但它与 D-099「默认路径必须是正确路径」
   字面冲突：拿默认参数跑多段，用户得到的是 BLOCK 而不是成片。
2. **`--force` 只放行渲染，不改结论**：第 2 次跑完 120 帧，结论仍是「未通过」、exit 3、不落地 final/。
   任何"自动化跑绿"都不能靠 `--force`，只能靠 `--chain-gap ≥ recommended_gap`。

这两条都不是我单方面能决定的行为（会动 M07 面板契约和 M08 自动化契约），已在提交里作为问题抛给 D0。

---

## 4. 复现

```powershell
# B（约 12 s）
powershell -NoProfile -ExecutionPolicy Bypass -File out\subai\M05\probe_single.ps1

# D4（两次 run + 拼图 + 步差，约 150 s）
powershell -NoProfile -ExecutionPolicy Bypass -File out\subai\M05\probe_junction.ps1
```

两个 `.ps1` 都是 **UTF-8 BOM + CRLF**（PS 5.1 读中文路径必需），且已在
`PowerShell 5.1.26100.8457` 上做过 `Parser::ParseFile` 语法检查。单跑第 1 次（gap 缺省）用
`probe_junction.ps1` 里的 `Invoke-ChainedRun` 换掉 `-Extra` 即可。

---

## 5. 这一笔没覆盖到的（别读成已验）

- **第二处交接**：`pair [1,2] timeline [181,182]`、30 根骨超阈值、112.01°，只在 dryrun 里有数，
  没有取图、没有像素步差。第一处交接的结论不能平移过去。
- **NLA 路线**：D4 全程 `--chain-mode splice`（默认）。NLA 只剩 1 绿/1 部分/2 没有。
- **单一 fixture、单一模型**：91/91/151 三段 + 卡芙卡3.0.pmx，720×576 渲染。换素材没验过。
- **像素只能说明"看起来跳不跳"**：世界坐标位移、骨骼真实角速度没有在这次测（那要另做 bpy 侧测量）。
- `--frames` 截断只在 94/120 两个值上试过；`blend > gap` 那条老风险依旧没有样本。
