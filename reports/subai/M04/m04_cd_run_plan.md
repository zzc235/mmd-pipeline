# M04 C@W1 / C@W2 / D 发车清单（等 `delivery_v1`，本轮不发车）

> 把已冻结的 `prereg v4+amendA1A3`（`D-179`）落成一份**可以照着跑、也能照着拒**的顺序。写完不发车：等 1号 的 `delivery_v1` 重建 + 4号 的 `max_constraints` 进 main。
> 归属：A2 车道（M03→M04），@模块负责2。依据：`prereg v4+amendA1A3`、`D-134`（B 组作废）、`D-143`（1 mm 先量化）、`D-149`（C/D 解禁条件 `pose_source=fresh_solve`）、`D-173`（交付按 `fresh_solve` 烘焙）、`D-155`（缓存不可重现）。

## 一、发车前必须同时成立的六条（缺一条 ⇒ 不发车，不是「跑了再说」）

| # | 条件 | 怎么验 | 不成立时 |
|---|---|---|---|
| 1 | `delivery_v1` 文件存在且可开 | 1号 交回路径 + `sha256` | 停 |
| 2 | 掩码通道 `--expect wired` **exit 0** | `python m02_mask_channel_probe.py --blend <delivery_v1> --expect wired`（退出码原样进报告） | 停，记 `1=FAIL` / `2=还没落地` |
| 3 | `stage_mask(root)` 判 `WIRED` + `constraints_capped == false` + `skipped_count == 0` | 见 C/D 准入两条（`D-149`/`D-162`），必须在**要测的那个场景**上回读，不是 `bpy.context.scene` | 停，`UNMEASURED`（理由「没有记录」≠「接错」） |
| 4 | `preflight` `READY`：`needs ≤ cap=constraint_limit(needed)`、`skipped=0`、`provenance` 指本 worktree | `python reports/subai/M04/scripts/m04_preflight_spec.py --worktree E:\code\mmdpipe-ai\A2 --spec-source <场景自己的 stage_mask 记录>` ⇒ `python -m coordination.preflight --spec <A2>/out/subai/M04/preflight_cd_spec.json --worktree .` | `BLOCKED`+`reason_code` 报 D0 |

> **两个数不许跨树拼**（`4号` 2026-11-16 18:02 抓、`总控` 18:03 确认）：`8298 / 10111` 是 **324 刚体树**的数；本轮的交付场景是 **312 刚体树**，同源读数是 `needed=8499 / already=1813 / needs(补)=6686 / cap=8499`。生成器因此去掉默认值：只接受 `--spec-source <场景记录>`，或 `--needed/--already` **且带 `--note-source`**；两者都不给就 **exit 4**（不是「用默认值凑一个」）。
> **实测（2026-11-16 18:03，只读、不开 Blender、不占锁）**：从 1号 的 `stage_mask_after_rebuild.json`（sha `fb022a72…`）取数 ⇒ `needs=6686 ≤ cap=8499`（`guardrail_hit=False`）、`skipped=0` ⇒ **`READY / EVIDENCE_COMPLETE`**；三条反控（什么都不给 / 给数不给出处 / 记录不存在）**各 exit 4**。
> 早前那版 `needs=8298 ≤ cap=10111` 的 `READY` **不再是本轮的读数**——它是 324 树的自洽结果，与本轮场景无关，保留在原快照里仅作历史。
| 5 | 场景 `is_baked == false`（A1） | 跑前、跑后**各回读一次** `rigidbody_world.point_cache.is_baked` | 任一为真 ⇒ `UNMEASURED`，理由 `pose_source=cache_replay` |
| 6 | 锁空闲且取到 | `python -m coordination.lock acquire`；长跑每 10 分钟 `touch` | 等，不抢 |
| 7 | `delivery_v1` 与 `--expect wired` 的读数是**同一份字节** | 记下 `delivery_v1` 的 `sha256_lf_normalized` 之后、**跑 C/D 之前再核一次**（每臂开跑前核，不是跑完核） | 两次不同 ⇒ **该组作废**（`D-126`：前后同仪器同字节） |

第 7 条不是形式主义：重建窗口里最容易发生的就是「1号 又改了一笔，我手上的路径指向新文件」。核不上就作废，不解释成「应该差不多」。

`delivery_v1` 若是 1号 用 `stage_build()` 新建的（不烘），第 5 条只需回读确认，**不必** `free_bake_all()`；文件里发现有烘过的缓存 ⇒ 先清、清完再回读，两个动作都进报告。

## 二、三个臂怎么跑（A1/A2 口径）

| 臂 | 场景 | 动作 | 窗口（**回读，不是声明**） | 姿态来源 | 输出 |
|---|---|---|---|---|---|
| `C@W1` | `delivery_v1` | `B_aligned` | **W1 = 1..240** | `fresh_solve` | `C_W1.meta.json` |
| `C@W2` | `delivery_v1` | `B_aligned` | **W2 = 1..832** | `fresh_solve` | `C_W2.meta.json` |
| `D` | `delivery_v1` | `原神摇` | **W2 = 1..832** | `fresh_solve` | `D.meta.json` |
| **A（基准）** | `B_from_blend1` | `B_aligned` | W1 = 1..240 | `fresh_solve`（`R_free` 臂，**已跑**） | `R_free.meta.json`（`is_baked=false`） |
| `A_cache`（参考行） | `B_from_blend1` | `B_aligned` | W1 = 1..240 | `cache_replay` | `A240.meta.json`（**不进比较**） |

- **为什么 C 跑两次**（v4 §二窗口矩阵）：`B vs A` 与 `C vs B` 都在 W1（同窗才可比）；`D vs C` 在 W2，因为 `原神摇` 全长 832 帧、**240 帧窗口会截掉峰值，造出「未穿透」的假阴性**。D 只能与 `C@W2` 比。
- **`B_aligned` 只有 300 帧**：`C@W2` 在 301..832 帧是**保持末帧姿态**——`D vs C@W2` 那 1..832 里**有 532 帧是末帧定格**。读数是真有，但**姿态不是动作给的**。这条**必须同时出现在证据的 `known_risks` 与报告显眼位置**，不许只写在清单里（`D0` 17:47 明确要求）。
- **窗口是回读的**：D 组场景必须 `frame_start=1`、`frame_end=832`，跑前回读 `scene.frame_end` 与动作 `frame_range` 末帧，不一致即**作废本次运行**（不许「大约覆盖」）。

- **每臂一个独立 Blender 进程**（同进程串味在 `bake_all` 上吃过一次：`is_outdated` 同进程 false、重开 true）。
- 每臂必记：`PID`、`cache_state`（`is_baked`/`is_outdated`）、`eval_policy`（必须 `sequential_from_frame_start`）、`visited_frames`、`warmup_frames`、**真实退出码**（Blender 5.2.2 在 `--background` 退出清理阶段会 `0xC0000005`，实测 `-1073741819` 而产物完整 ⇒ 判成功看**产物完整性**，退出码原样记、不折算）。
- `plan_sequential_eval` 抛 `SequentialEvalError` ⇒ 本臂作废（不许冷跳凑）。

## 二之一、`delivery_v1` 的基线：**先建一次，三个臂复用**（`D-056`）

探针的判据是**增量**（`max_depth_m = −max(0, depth − baseline)`），所以基线必须是**这个场景**的，不能借用 `B_from_blend1` 的：

1. **第一臂之前**用 `--baseline-write out/subai/M04/penetration/baseline_delivery_v1.json` 跑一次（探针在 `baseline_frame` 上取静止姿态的成对深度，落盘时带哈希）；
2. 之后 C@W1 / C@W2 / D 三臂一律 `--baseline <那份 JSON>`，**不许各建各的**——各建各的等于三臂三个零点，`D vs C` 会把基线差算成「振幅效应」；
3. 基线文件记进报告：`path` + `sha256_lf_normalized` + 建它的那一次运行的 `blend` sha；
4. **`roi_missing` 必须为空**：`delivery_v1` 是新场景，ROI 18 根骨在它身上解析不出来时，探针会给出 `roi_missing` 非空 ⇒ 该臂判 `UNMEASURED`（理由「ROI 对不上这个骨架」，不是「没穿透」）。

> 这条是写清单时补的：原清单列了三臂却没写基线，跑起来最可能的错是「三臂各建一份基线」或「沿用旧场景基线」，两种都会把姿态差混进判词。

## 二之二、身份两层：`sha256` 是「这一份」，`content_digest_v1` 才是「可复现」

1号 2026-11-16 18:09 给的事实：**`.blend` 不是逐字节可复现**（同输入三次 5 929 823 / 5 928 599 / 5 923 244 B，规范化内容相同）。所以本清单里第七条（跑前核 sha）要说准它在证什么：

- **实例身份 = 该文件的 `sha256`**：证明「我测的就是这一份」，**不**证明重建会得到同一个字节序列。第七条核的就是它——跑前跑后各一次，不同即该臂作废。
- **可复现性 = `content_digest_v1`**（1号 的 `reports/subai/M02/content_digest_v1.md` + `m02_content_digest.py`，`--facts` 口径）：跨次应当相同。每臂记录它，并**写明是弱摘要还是强摘要**——`bodies[]` 缺项时是弱摘要（只覆盖 `rigids`/约束/`chain_ratio`），**弱摘要不许给「内容一致」背书**，更不许给 T3 背书。
- **不许**把「sha 相同」说成「内容可复现」，也不许把「content_digest 相同」说成「测的是同一份文件」。两句各管一头。

## 三、判据（照 `prereg v4+amendA1A3`，一条不加一条不减）

1. **量化在先**：`max_depth_m` 与 `raw_depth_m` 先 `round(…, 6)`（探针精度 1e-6 m）再比较，判据是 **1 mm**；`BOUNDARY`（跨 1 mm 线）记两个数、不判通过（`D-143`）。
2. **方向只看两条**：`max_depth_m` 更负 + `overlapping_pairs` 更多；`raw_depth_min` 只作参考行（A3）。
3. **比较的是"变没变"**：`C@W1 vs A(R_free)` 隔离「换场景」（同 W1）；`D vs C@W2` 隔离「振幅」（同 W2）；`C@W2 vs C@W1` **不是**一次合法比较（同组不同窗），只用来展示窗口效应。
4. **二十毫米判据**只在两臂同窗口、同动作、同姿态来源时启用；窗口不同（W1 vs W2）**不许**互相减。

## 四、拒（fail-closed，这几种情况一律不出物理数字）

| 情况 | 判词 |
|---|---|
| 掩码 `verdict != WIRED` 或 `capped > 0` 或 `skipped != []` | `UNMEASURED`，理由写清是三条里哪条 |
| `is_baked` 跑前/跑后任一为真 | `UNMEASURED`（`pose_source=cache_replay`） |
| `frames_measured != 计划帧数` | `UNMEASURED`（缺帧不算少几帧，是整臂作废） |
| 探针自检不过 / `plan_sequential_eval` 报警 | 整臂作废 |
| 只有 `raw_depth_min` 变化而另外两条不动 | 不许当结论，参考行单列 |

## 五、交什么（同笔三样 + 一份比较表）

1. 三支 `*.meta.json`（各自 `cache_state`/`eval_policy`/退出码）；
2. 每次 `--expect wired` 的**退出码原样**，与 `stage_mask` 的三元组回读；
3. 与 `R_free` 的逐帧差分布（中位 / P90 / 最大 / 最大帧），口径与 `a0_v2_table.json` 一致——**同一支脚本**加 `--pair "<tag>=<臂A>,<臂B>"` 即可（已实现并验过：默认路径输出与已提交件**逐字节相同** `3bc9e193…`，自定义对跳过对账并明说「换了臂就不装作还在对账」；三种坏输入各 exit 2）。
4. `truth_tier`：**`T2`（代表性逐帧）**，本轮只报这个——不自升，也不许为了好看写成 `T3`。`T3`（交付尺度）要**四条同时成立**（`D0` 17:47 钉死）：
   1. 掩码通道在**交付场景自身**上回读 `WIRED / cap=0 / skipped=[]`（不是别的场景、不是单测的假 bpy）；
   2. 交付件按契约 B **已烘焙**，且行为探针过（冷跳中间帧 == 顺序重算）；
   3. `delivery_v1.blend` 的 `sha256` 记录在案，且与 C/D 读数同一次；
   4. `preflight` 的 `cap` 来自 `constraint_limit()` 返回值、`skipped=0`。

   第 2 条现在做不到（`stage_build()` 至今不烘焙，`D-153` 的缺陷还在）⇒ **这轮最多 `T2`**。四条哪条不成立就在报告里点名，不糊成「接近 T3」。

## 六、当前挡在哪

- 挡在 1号 的 `delivery_v1`（M08 重建）与 4号 的 `max_constraints` 进 main（`plan()` 推出的 cap；4号 实测 `needs=8298 ≤ cap=10111`、`guardrail_hit=False`）。
- 1号 交回时要带：`delivery_v1` 路径 + `sha256`、`--expect wired` 退出码、`stage_mask(root)` 三元组、`is_baked` 回读值。缺任一项我这边判 `UNMEASURED` 不是 `FAIL`（「没给」≠「不对」）。
