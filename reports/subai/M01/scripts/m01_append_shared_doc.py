"""把 M01 的执行记录 / 交接补充追加到共同工作区的模块任务书末尾（幂等）。

    python m01_append_shared_doc.py            # 追加（已存在标记则跳过）
    python m01_append_shared_doc.py --check    # 只检查是否已追加

只追加，不改任何既有正文；每条都带绝对路径与数值，便于复核。
"""
from __future__ import annotations

import io
import os
import sys

SHARED = r"C:\Users\zzc\Desktop\ai用\dsh use\gongtonggzq"
M01_DOC = os.path.join(SHARED, "M01_F3冻结类修复_胸口与袖子.md")
M02_DOC = os.path.join(SHARED, "M02_F4下摆与F6碰撞映射.md")
M01_MARK = "# 补充 · M01 执行记录"
M02_MARK = "# 补充 · M01 → M02 交接（由 M01 追加）"

M01_TEXT = r'''
---

# 补充 · M01 执行记录（子 AI 追加，2026-11-15 20:59–21:28）

> 本段是执行后追加，**不改上方任务书正文**。每条都能按「绝对路径 + 命令 + 数值」复核。
> 状态：**`PARTIAL`**（S3 = PASS；S5 = 结构核对完成、静态策略技术上可重复但视觉不可接受）。
> 证据根目录：代码 `E:\dsh pr\woker2\mmdpipe\pmx.py`、`E:\dsh pr\woker2\tests\test_pmx_patch.py`；
> 产物 `E:\dsh pr\woker2\out\subai\M01\`；报告 `E:\dsh pr\woker2\reports\subai\M01\`。

## 补充-1. 逐步骤时间线

| # | 时间 | 动作 | 命令 / 脚本（绝对路径） | 产物 | 结果 |
|---:|---|---|---|---|---|
| 1 | 20:59 | 读任务书 00 / 09 / M01；`git status` 为空 | `C:\Users\zzc\Desktop\ai用\dsh use\2026-11-15_Blender流水线_子AI任务包\*.md` | — | 当时工作树干净（后续出现其它模块改动，见补充-6） |
| 2 | 21:00 | 建本模块目录 | `mkdir out\subai\M01 reports\subai\M01\scripts` | `E:\dsh pr\woker2\out\subai\M01\` | 目录原先不存在，未覆盖任何旧产物 |
| 3 | 21:01 | 环境确认 1/2：Blender 侧导入失败 | `blender -b --factory-startup -P reports\subai\M01\scripts\m01_env_probe.py` | — | `bpy.ops.mmd_tools.import_model` 不存在（扩展未启用） |
| 4 | 21:02 | 环境确认 2/2：启用扩展后再探 | 同上（脚本内 `addon_utils.enable("bl_ext.user_default.mmd_tools")`） | `E:\dsh pr\woker2\out\subai\M01\env_feixiao.json` | 发现：`types` 不含 `PHYSICS` 时 `Model.build()` **静默建 0 个刚体**；含 PHYSICS 时 312 刚体 / 389 关节，`is_built=False`→`True`，337 条约束 |
| 5 | 21:03 | 阶段 A 只读基线 | `python reports\subai\M01\scripts\m01_baseline.py` | `out\subai\M01\baseline.json`、`baseline.md` | 飞霄 312/389/420，`{0:48, 2:264}`，24–29 全 mode2；卡芙卡 145/182/246，`{0:24,1:119,2:2}`，袖筒 2 单元无 mode2 |
| 6 | 21:04 | 阶段 B：补丁能力 + 测试 | 改 `E:\dsh pr\woker2\mmdpipe\pmx.py`；新建 `E:\dsh pr\woker2\tests\test_pmx_patch.py` | 见补充-2 | `python -m unittest tests.test_pmx_patch tests.test_physics -v` → **16 项 OK** |
| 7 | 21:05 | 生成 S3 副本 | `python reports\subai\M01\scripts\m01_make_patch.py` | `out\subai\M01\飞霄_s3_mode0.pmx`、`patch_manifest.json` | 6 个 mode 字节 2→0，长度不变，源哈希未变 |
| 8 | 21:05–21:06 | clip1 三变体探针（逐帧连续步进） | `m01_chest_probe.py`（baseline / static / mode0，`--frames 1,15,30,45,60`） | `out\subai\M01\probe\probe_*.json` + `shot_*.png` | mode0 胸口约束 6→0；mode0 与 static 差 `0.00000` |
| 9 | 21:06 | 逐顶点对照统计 | `python reports\subai\M01\scripts\m01_compare.py` | `probe\comparison.json`、`comparison.md` | baseline 偏离 0.22746 m（均值）/ 0.29213 m（最大） |
| 10 | 21:07 | 阶段 D 独立确认（换动作） | `m01_chest_probe.py` ×3，VMD = `EMO_Sway_Normal_Once_F.vmd` | `out\subai\M01\probe2\*` | baseline 偏离 0.23289 m；mode0 与 static 差 `0.00000`，结论一致 |
| 11 | 21:08 | 阶段 E：S5 两变体 | `m01_sleeve_probe.py --policy off` / `--policy strict` | `out\subai\M01\sleeve\sleeve_base.json`、`sleeve_static.json` | >45°/帧 35→0；最大逐帧转角 343.35°→12.61°；非袖子骨 359.258° 两变体完全相同 |
| 12 | 21:09–21:16 | 代表帧静态图迭代 3 轮（引擎 / 朝向 / 材质） | `m01_shots.py` | `out\subai\M01\shots_chest\`、`shots_chest2\`、`shots_chest3\`、`shots_sleeve\` | 本机只有 `BLENDER_EEVEE`（无 Workbench），需自布光；副本换目录会丢贴图，形状对照统一中性灰材质 |
| 13 | 21:17 | 拼版对比图 | `python reports\subai\M01\scripts\m01_sheet.py` | `out\subai\M01\compare_chest.png`、`compare_sleeve.png` | 1498×988 / 1086×988 |
| 14 | 21:19 | 报告五件套 + 源哈希复算 | `m01_collect.py`；手写 `result.md`/`handoff.md`/`reproduce.md`/`changed_files.txt` | `reports\subai\M01\*` | 两个源 PMX 的 SHA256 与开始时一致 |
| 15 | 21:20 | 自纠错：关节限位字节布局 | 改 `m01_baseline.py` 的 `joint_limits()`，重跑 baseline / manifest / collect | `baseline.json`、`baseline.md`、`patch_manifest.json`、`measurements.json` | 修正前把 12 个限位 float 切成「6 限位 + 6 弹簧」；实测应为 限位 `+24`(12f)、弹簧 `+72`(6f) |

## 补充-2. 改动步骤（源码级，逐 hunk）

文件：`E:\dsh pr\woker2\mmdpipe\pmx.py`（`git diff --stat`：+32 / −2）

| 步骤 | 位置（新行号） | 改动 | 目的 |
|---:|---|---|---|
| 1 | 151 | `PMXModel` 新增 `rigid_mode_offsets: list = field(default_factory=list)` | 保存每个刚体 mode 的**真实字节偏移** |
| 2 | 378 | `parse()` 局部 `rigid_mode_offsets: list = []` | 与 `rigid_pos_offsets` 同层 |
| 3 | 430 | 刚体循环里 `mode_off = r.pos` 记在 `r.u8()` **之前** | 偏移由解析器实测，不按 PMX 规范推断 |
| 4 | 435 | `rigid_mode_offsets.append(mode_off)` | 与 `rigids` 一一对应 |
| 5 | 465 | 收尾 `model.rigid_mode_offsets = rigid_mode_offsets` | 交给调用方 |
| 6 | 472–475 | `RIGID_MODES = (0, 1, 2)` + 语义注释（0 跟随骨骼 / 1 物理 / 2 物理+回填旋转） | 语义唯一声明源 |
| 7 | 477–479 | `patch_save()` 新增参数 `rigid_mode: dict \| None = None` | 调用方传 `{index: new_mode}` |
| 8 | 492–507 | 校验：索引越界 / `bool` 与非 int / mode∉{0,1,2} / 偏移越界 / **回读旧值 != 解析值（偏移过期）** 一律抛 `PMXError` | 偏移写错会静默改坏 mass/friction，必须拒写 |
| 9 | 509–510 | `buf[model.rigid_mode_offsets[idx]] = mode` | 只改 1 字节，不重序列化 |

文件：`E:\dsh pr\woker2\tests\test_pmx_patch.py`（新增 198 行，12 项）

- 合成最小 PMX（`build_pmx(modes, name_pad)`）覆盖：6 个 mode 2→0、非目标 mode 不变、长度不变、
  diff 位置数 = 目标 mode 字段数、非 diff 区域逐字节一致、空补丁 = 逐字节相同、`rigid_pos` 回归、
  拒绝覆盖源文件、非法 mode（`3 / -1 / 255 / 1.0 / "0" / True`）、非法索引、偏移过期（`name_pad=7` 造偏移差）、
  `mode_off - pos_off == 44` 交叉校验。
- 真实模型 2 项（缺模型则 skip）：24–29 全 mode2 且骨名为 `右胸…`；补丁后恰好 6 字节差异。

## 补充-3. 关键数值

### S3 飞霄胸口（ROI：71 顶点，权重主导骨 ∈ 胸.R / 胸１.R / 胸２.R / 胸.L / 胸１.L / 胸２.L）

| 动作 | 帧 | baseline vs static（均值 / 最大，m） | mode0 vs static | 胸 extent_x baseline→mode0 | 胸/髋 baseline→mode0 |
|---|---|---|---|---|---|
| PERF_Wushu（clip1） | 1 / 15 / 30 / 45 / 60 | 0.22746/0.29213；0.22803/0.29307；0.22674/0.29135；0.22597/0.29177；0.22809/0.29358 | **全 0.00000** | 0.11099→0.16981；0.10501→0.17423；0.10988→0.18234；0.13415→0.18405；0.13806→0.18409 | 0.4333→0.6629 … 0.5286→0.7049 |
| EMO_Sway（clip2，独立确认） | 1 / 20 / 40 / 60 | 0.23289/0.29900；0.23256/0.29864；0.23292/0.29990；0.23283/0.29996 | **全 0.00000** | 0.10828→0.18528；0.10774→0.18639；0.11627→0.18593；0.11467→0.18630 | 0.4285→0.7332 … 0.4526→0.7353 |

- 约束计数：baseline 胸口 6 条 `COPY_ROTATION`、全模型 264；mode0 胸口 **0** 条、全模型 **258**，
  其它约束类型（TRANSFORM 32 / IK 4 / LIMIT_ROTATION 2 / DAMPED_TRACK 4 / COPY_TRANSFORMS 31）一条不差。
- 物理活性（证明不是"整体没动"）：同一批刚体首末帧世界位移 0.60–0.71 m。

### S5 卡芙卡袖筒（ROI：397 顶点；48 骨 × 150 帧逐帧统计）

| 指标 | base（policy=off） | static（policy=strict） |
|---|---|---|
| 静音约束 / 仍生效 | 0 / — | **48 / 0** |
| 逐帧最大转角（全局） | **343.35°**（f31，`xk_0_0`） | **12.61°**（f31，`xk_0_4`） |
| >45°/帧 次数 | **35**（集中在 f29–f33，单帧最多 13 根） | **0** |
| 每帧最大转角均值 | 26.81° | 3.42° |
| 非袖子物理骨同期最大值（对照） | 359.258° | **359.258°（逐帧完全一致）** |
| 袖筒包围盒 f45 | 0.126×0.308×0.340 m | **1.100×0.137×0.629 m（刚性长条）** |

## 补充-4. 文件清单（新增 / 修改，逐路径）

**源码（改 1）**
- `E:\dsh pr\woker2\mmdpipe\pmx.py`（见补充-2）

**测试（新增 1）**
- `E:\dsh pr\woker2\tests\test_pmx_patch.py`

**实验脚本（新增 9）** 目录 `E:\dsh pr\woker2\reports\subai\M01\scripts\`
- `m01_baseline.py`、`m01_env_probe.py`、`m01_make_patch.py`、`m01_chest_probe.py`、`m01_compare.py`、
  `m01_sleeve_probe.py`、`m01_shots.py`、`m01_sheet.py`、`m01_collect.py`
  （另有 `m01_append_shared_doc.py`：把本补充写回共同工作区）

**报告（新增 6）** 目录 `E:\dsh pr\woker2\reports\subai\M01\`
- `result.md`（212 行，PARTIAL）、`measurements.json`、`patch_manifest.json`、`changed_files.txt`、
  `reproduce.md`、`handoff.md`（89 行）

**实验产物（新增）** 目录 `E:\dsh pr\woker2\out\subai\M01\`
- `baseline.json`、`baseline.md`、`env_feixiao.json`、`飞霄_s3_mode0.pmx`、`patch_manifest.json`
- `probe\`：三变体 probe json + `comparison.json/md` + 6 张 `shot_*.png`
- `probe2\`：同上（clip2 独立确认）
- `sleeve\`：`sleeve_base.json`、`sleeve_static.json` + 4 张 `sleeve_*.png`
- `shots_chest\`、`shots_chest2\`、`shots_chest3\`、`shots_sleeve\`：代表帧静态图
- `compare_chest.png`、`compare_sleeve.png`：交付对比图

**未触碰**：两个源 PMX、任何 VMD / `.blend`、`stage.py`、`physics.py`、`runner.py`、`addon\mmd_pipeline\**`。

## 补充-5. 实验计数与停止条件

| 项目 | 上限 | 实际 | 说明 |
|---|---:|---:|---|
| 环境 / API 确认 | 2 | **2** | ① 扩展未启用 ② `types` 必须含 PHYSICS；均在 2 次内解决 |
| 基线复现 | 2 | 1 | clip1 一次跑通 |
| S3 故障实验 | 3 | **3** | 基线 / 单变量 mode 修复 / 独立动作确认 |
| S5 故障实验 | 3 | **2** | 基线 / 静态策略；第 3 轮未用（任务书禁止另试多种 PMX 改法） |
| 同一报错修复 | 2 | 2 | `import_vmd` poll 缺 select+active；`build` 需 PHYSICS |
| 全量回归 | 2 | 1 | 60 项 OK（7 个测试模块） |
| 12 帧探针 / 长渲染 | 2 | 0 | 只做代表帧静态图，未做序列渲染 |
| 代表帧渲染 | 2 | 3 轮 | 引擎 / 朝向 / 材质各修一次（静态图，秒级），计数如实写超 |

## 补充-6. 合规与偏差（如实记录）

1. **Blender 资源锁未按 `10_并行执行准则` §4 取得**。该准则文件 21:03 才出现在共同工作区，
   而我的 Blender 任务从 21:01 开始；全程未发现他人遗留锁（`E:\dsh pr\woker2\out\subai\locks\`
   目录 21:19 才出现且当前为空，无 `blender.lock`）。若期间有其它模块同时跑 Blender，需总控核对。
2. 未使用隔离 worktree：串行执行可省略（00 §7 允许），本模块未与其它模块并行改同一文件。
3. 改动只落在任务书 §3 允许范围（`pmx.py` 刚体 mode 补丁 + 新测试 + 本模块 out/reports）。
4. 未 commit / reset / clean / push；未删除任何历史产物。
5. 自纠错一处：`m01_baseline.py` 最初把关节 12 个限位 float 误切成「6 + 6」，21:19 修正为
   限位 `+24`(12f) / 弹簧 `+72`(6f)，并重跑 `baseline.json`、`patch_manifest.json`、`measurements.json`。
6. 期间工作树出现其它模块的未提交改动（`chain_nla.py`、`chainplan.py`、`concatvmd.py`、`runner.py`、
   `vmd.py`，新增 `diagnose*.py`、`tests/test_chain.py`、`tests/test_diagnose.py`）。M01 未触碰这些文件，
   60 项回归也不包含它们。

## 补充-7. 给下游模块的事实

- **M02**（已同步写入其任务书末尾「补充 · M01 → M02 交接」）：`patch_save(..., rigid_mode={index: 0/1/2})`
  可直接复用；关节限位 / 弹簧的实测字节布局；S3 基线副本路径。
- **M03 / M04**（未改其任务书，事实记在此处，待总控转交）：胸口冻结判据可用
  `chest_extent_x / hip_extent_x`（实测冻结 0.40–0.53、纯跟随 0.66–0.74），或「与关物理静态的逐顶点距离」
  （冻结 ≥0.22 m、正常 ≤0.0001 m）。ROI 取权重最大的**骨骼**组时，必须排除 `mmd_edge_scale` /
  `mmd_vertex_order` 这类非骨骼顶点组，否则所有顶点都会被归到它名下（本模块踩过一次）。
- **全体**：非袖子物理骨存在 **359.258°** 量级逐帧跳变（两变体完全相同，与袖筒无关），建议单独立项归因。

## 补充-8. 未闭环与下一假设

- 未闭环：S5 没有可用修复（静态策略把袖子变成刚性长条）；S3 副本对裙 / 发 / 配饰的连锁影响未测；
  GUI 人工验收未做（全程 `blender -b`）。
- 下一假设（只提一条，由总控决定是否开新会话）：袖筒「抖动 vs 僵直」二选一说明问题在**闭环关节结构本身**
  （25 体 / 48 关节 / 环 24 / 焊 50%）；下一步应减少焊接关节或在闭环里加弹簧，而不是继续在骨级
  静音 / 恢复之间切换。
'''

M02_TEXT = r'''
---

# 补充 · M01 → M02 交接（由 M01 追加）

> 本段只提供 M01 已交付、M02 必用的接口与坐标，**不改上方任务书正文**。
> 依据：`E:\dsh pr\woker2\reports\subai\M01\result.md`、`handoff.md`、`measurements.json`
> 与 `E:\dsh pr\woker2\out\subai\M01\patch_manifest.json`。

## 1. 不要另造补丁器：直接用这个函数

```python
from mmdpipe import pmx
m = pmx.load(SRC)                                  # 必须 load，偏移来自解析期记录
pmx.patch_save(m, DST, rigid_mode={24: 0, 25: 0})  # 只改 mode 字节
```

- 校验（已实现、已测）：index 越界、`bool`/非 int、mode∉{0,1,2}、偏移越界、**偏移过期（回读旧值不符）**
  都会抛 `pmx.PMXError`；`dst == 源路径` 直接拒绝；输出长度恒等于源长度。
- 测试：`python -m unittest tests.test_pmx_patch tests.test_physics -v` → 16 项（本机实跑 OK）。

## 2. 关节限位 / 弹簧补丁的实测字节坐标（M02 要扩展的部分）

PMX 关节段从 `position` 起（`model.joint_pos_offsets[i]` 指向 `position` 首字节）：

| 字段 | 相对偏移 | 宽度 |
|---|---|---|
| position | `+0` | 3f |
| rotation | `+12` | 3f |
| 平移下限 / 平移上限 | `+24` / `+36` | 3f / 3f |
| 旋转下限 / 旋转上限 | `+48` / `+60` | 3f(rad) / 3f(rad) |
| 平移弹簧 / 旋转弹簧 | `+72` / `+78` | 3f / 3f |

- 这组偏移是逐字节核对的（飞霄 joint 0/1/2：焊死关节 12 个限位全 0；joint 1 = 旋转
  `[0,-0.1745,0] → [0.5236,0.0873,0]`），不是按规范猜的。
- 读取代码可直接抄 `E:\dsh pr\woker2\reports\subai\M01\scripts\m01_baseline.py` 的 `joint_limits()`。
- 扩展建议：照 `rigid_mode` 的做法加 `joint_limit={index: 12 floats}`，写前回读旧值校验；
  **不要**重排关节段或改变索引宽度（`rs` 因模型而异）。
- 找 S2 目标不要按名字猜：用 `physics.classify()` 的 `suspect_units` / `welded` 取 `Unit.joint_ids`
  反查关节索引。

## 3. 可直接用的输入与判据

- S3 已修复的飞霄副本（胸口 6 刚体 mode0，其余与源一致，6 字节差异）：
  `E:\dsh pr\woker2\out\subai\M01\飞霄_s3_mode0.pmx`
  — 若 S2/S8 实验需要"胸口不再干扰"的干净基线，直接拿它当输入。
- 胸口 ROI / 门禁数值（M04 也要用，这里一并留档）：
  - 骨名（Blender，`rename_bones=True`）：`胸.R 胸１.R 胸２.R 胸.L 胸１.L 胸２.L`；髋 `下半身/腰`；躯干 `上半身2`。
  - ROI 取"权重最大的**骨骼**顶点组"，**必须排除** `mmd_edge_scale` / `mmd_vertex_order`，否则全部顶点归它。
  - 实测：胸口 71 顶点 / 髋 1250 / 躯干 1309（scale 0.08，世界单位 m）。
  - `chest_extent_x / hip_extent_x`：冻结 0.40–0.53，纯跟随 0.66–0.74；
    与"关物理静态"的逐顶点距离：冻结 ≥0.22 m，正常 ≤0.0001 m。

## 4. 环境坑（M02 跑 Blender 前先看）

1. `--factory-startup` 下必须先 `addon_utils.enable("bl_ext.user_default.mmd_tools")`。
2. `import_model(types=...)` **必须含 `"PHYSICS"`**，否则 `Model.build()` 静默建 0 个刚体。
3. `import_vmd` 前必须 `root.select_set(True)` + `view_layer.objects.active = root`。
4. `scene.rigidbody_world.enabled` 建完是 False，要手动开并设 `substeps_per_frame=10`、`solver_iterations=20`。
5. 本机可用渲染引擎只有 `BLENDER_EEVEE`；副本 PMX 换目录会丢贴图，形状对照需统一材质。
6. Blender 任务前先取 `E:\dsh pr\woker2\out\subai\locks\blender.lock`（M01 当时该准则尚未下发，已如实记录）。
'''


def append(path: str, mark: str, text: str, replace: bool = False) -> str:
    """追加；--replace 时先截断旧补充。路径里的双反斜杠落盘前还原成单个。"""
    s = io.open(path, encoding="utf-8").read()
    body = text.replace(chr(92) * 2, chr(92))
    if mark in s:
        if not replace:
            return "skip (already appended)"
        idx = s.index(mark)
        head = s[:idx].rstrip()
        if head.endswith("---"):
            head = head[:-3].rstrip()
        io.open(path, "w", encoding="utf-8").write(head + chr(10) + body)
        return "replaced %d chars" % len(body)
    io.open(path, "a", encoding="utf-8").write(body)
    return "appended %d chars" % len(body)


def main() -> int:
    check = "--check" in sys.argv
    replace = "--replace" in sys.argv
    for path, mark, text in ((M01_DOC, M01_MARK, M01_TEXT), (M02_DOC, M02_MARK, M02_TEXT)):
        if not os.path.exists(path):
            print("MISSING", path)
            return 2
        s = io.open(path, encoding="utf-8").read()
        if check:
            print("%-70s has_mark=%s lines=%d"
                  % (os.path.basename(path), mark in s, s.count(chr(10))))
            continue
        print("%-40s %s" % (os.path.basename(path), append(path, mark, text, replace)))
        now = io.open(path, encoding="utf-8").read()
        print("   now lines=%d doubled_backslash=%d"
              % (now.count(chr(10)), now.count(chr(92) * 2)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
