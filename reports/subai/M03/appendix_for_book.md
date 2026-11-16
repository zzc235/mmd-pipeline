# 附录 A · 执行记录（子 AI 补充，2026-11-15 21:04–21:35）

> 回写者：M03 会话（归因工具 AI）。本节只追加，不改上面 §1–§7 的任务书原文。
> 所有数字来自仓库 `E:\dsh pr\woker2` 里已落盘的文件，不做二次推断；
> 每条结论都能顺着「仓库相对路径 + sha256」回溯到原件。

## A.0 一句话结果

`PARTIAL` —— 判据引擎（F1–F6 + R0）、Blender 只读采集器、37 条测试、8 条样本 manifest 全部落地；
真实 confirmed 只有 3 处（S5=F3、S7=F1、S8=F6），**F4 / F5 / R0 没有真实 confirmed 样本**。

## A.1 时间线与前置事实

| 时间 | 事实 |
|---|---|
| 21:04 | 读任务包 4 份文档 + 项目书 §4–§6；确认 `pmx.Joint` 已有 `limit_span / spring_max / welded`，可直接当 F3/F4 静态判据原料 |
| 21:07 | schema v1 + 判据引擎落地，静态 CLI 在飞霄 PMX 上首跑：`primary=F3 [suspected]` |
| 21:10 | 取 Blender 锁，开始元数据普查（`out/subai/locks/blender.lock`，owner.txt 记模块号/PID/时间/命令） |
| 21:15 | 发现两处误判并修复（四元数双覆盖 357°→2.75°；F3 只认 PMX 焊接冻结根候选） |
| 21:19 | S5 袖子 60 帧实测拿到 F3 confirmed；**释放 Blender 锁** |
| 21:26 | 8 条样本 manifest / 覆盖矩阵 / 汇总落盘 |
| 21:35 | 统一回报五件套 + known_limits + schema 说明完成 |

前置事实（开工时**未**有的东西）：仓库里没有 `diagnose*` 任何文件；没有 F1–F6 的可执行判据；
项目书 §5 的判据树只是文字。M01 的 `pmx.py` 已在改动中（本模块只读，不碰）。

## A.2 步骤表（每一步的文件与命令）

| # | 动作 | 文件（创建/修改，仓库相对路径） | 命令 / 关键数值 |
|---:|---|---|---|
| 1 | 盘点现有能力（先找现成的） | 只读 `mmdpipe/pmx.py`(607 行)、`mmdpipe/physics.py`(330 行)、`mmdpipe/stage.py`(摘 165–224)、`E:\flowhmr-test\tools\phys_probe.py`(207 行) | 复用 `physics.classify()` 的物理单元，不新写并查集 |
| 2 | 冻结 schema + CLI | `mmdpipe/diagnose.py`（新建） | `SCHEMA_VERSION=diagnose/1`、`TAXONOMY_VERSION=F1-F6+R0/1`、7 个阈值各带 `source` |
| 3 | 判据引擎 F1→F6→R0 | `mmdpipe/diagnose.py`（新建，1126 行，48,146 B，`7e289966768934a1…`） | `collect_pmx()` / `judge()` / `build_report()` / `judgment_fingerprint()` |
| 4 | 合成 fixture 先行 | `tests/test_diagnose.py`（新建，37 条，21,672 B，`e087d75c23699f87…`） | `python -m unittest tests.test_diagnose` → `Ran 37 tests … OK` |
| 5 | 静态 CLI 首跑（中文路径） | 产物 `reports/subai/M03/evidence/static/S3.json` | `primary=F3 [suspected]  secondary=F4(suspected), F5(suspected)` |
| 6 | Blender 只读采集器 | `mmdpipe/diagnose_blender.py`（新建，17,950 B，`ce84489793b6acc1…`） | 不 save、前后两次 SHA256、`os._exit` 绕析构段错误 |
| 7 | 元数据普查 5 场景 | 产物 `reports/subai/M03/evidence/blend/probe_*.json`（6 个） | 每场景约 3 秒 |
| 8 | 修 `_find_root`：多模型挑骨最多的 ROOT | `mmdpipe/diagnose_blender.py`（改 `_find_root`） | 修前拿到 `刀_arm`（1 根骨），修后 `卡芙卡3.0_arm`（296 根骨） |
| 9 | 60 帧动态（S3 候选场景） | 产物 `reports/subai/M03/evidence/blend/S3_chest_60f.json` | `下擺_10_7` 局部 0.48° / 父链 65.83° → **误判 F3** |
| 10 | 修四元数双覆盖 | `mmdpipe/diagnose_blender.py`（改 `_angle_deg`） | `rotation_difference().angle ∈ [0,2π]`，超 π 取补角 |
| 11 | 修 F3 候选过滤 | `mmdpipe/diagnose.py`（改 `_f3`） | 该场景 F3 → `suspected`，误报消除，指纹 `2819533922cd` |
| 12 | S5 卡芙卡 60 帧 | 产物 `reports/subai/M03/evidence/blend/S5_sleeve_60f.json` | 16 根袖骨 **0.0°** / 父链 **66.41°** → **F3 confirmed**，`fd960f16c1be` |
| 13 | 修 F3 计数：焊接但不绑骨的碰撞体不算根 | `mmdpipe/diagnose.py`（`_frozen_roots` 加 `bone_bound`，`_f3` 过滤） | 卡芙卡 22 根 → 16 根绑定根，结论不变 |
| 14 | S8 真实 A/B 像素比对 | `reports/subai/M03/scripts/m03_manifest.py`（新建）→ `evidence/ab/S8_{A,B}_render.json`、`evidence/static/S8_f6.json` | 3 帧 800×640：**0/512000 像素不同**（PNG 字节不同）→ **F6 confirmed**，`f918267aaf4f` |
| 15 | 8 条样本 manifest / 覆盖 / 汇总 | `reports/subai/M03/scripts/m03_manifest.py` → `sample_manifest.json`(29,320 B)、`coverage.json`(6,258 B)、`summary.json`(5,869 B) | 8/8 有 manifest 项；覆盖按「不同证据文件」去重（同一 PMX 被 7 条样本复用不能算 7 份） |
| 16 | schema 示例 + measurements | `reports/subai/M03/scripts/m03_examples.py` → `schema_example_{confirmed,insufficient}.json`、`measurements.json`(54,087 B) | 含 7 条实测命令与退出码 |
| 17 | 判据改动后重采全部证据 | 覆盖 6 个 probe + 2 个 60 帧 JSON | 指纹：v1 `9650782fc695`、combined `3f1695bbb24c`、v2 `2819533922cd`、kafuka `fd960f16c1be` |
| 18 | 统一回报五件套 | `reports/subai/M03/{result,handoff,reproduce,changed_files}.md/.txt`、`known_limits.md`、`schema.md` | `result.md` 141 行 ≤300；`handoff.md` 83 行 ≤100 |
| 19 | 释放锁 + 复算源哈希 | 删除 `out/subai/locks/blender.lock`（先核对 owner.txt） | 6 个源文件 SHA256 全部一致 |

## A.3 改动明细（改前 → 改后）

| 文件 | 类型 | 改前 | 改后 | 为什么 |
|---|---|---|---|---|
| `mmdpipe/diagnose.py` | 新增源码 | 不存在 | 判据引擎 + schema + CLI | 项目书 §5 的判据树必须可执行、可测、可复现 |
| `mmdpipe/diagnose_blender.py` | 新增源码 | 不存在 | 只读证据采集器 | `is_built` / `point_cache` / 世界矩阵只有 Blender 侧能读 |
| `tests/test_diagnose.py` | 新增测试 | 不存在 | 37 条 | 合成 fixture 先行，边界可回归 |
| `reports/subai/M03/scripts/m03_manifest.py` | 新增脚本 | 不存在 | manifest/覆盖/汇总生成 | 数字不手抄，可重复运行 |
| `reports/subai/M03/scripts/m03_examples.py` | 新增脚本 | 不存在 | schema 示例 + measurements | 示例与实测分离 |
| `mmdpipe/pmx.py` 等 6 个源文件 | **未改** | — | — | 任务书禁止；`git status` 的 `M` 来自并行的 M01/M05 |

判据口径上的两次自我修正（写在这里是因为它们改变了结论）：
1. **`_angle_deg` 归一化**：`mathutils` 四元数双覆盖会把「几乎没动」报成 357°；
2. **F3 候选过滤**：只允许 PMX 焊接冻结根的目标骨进对照 —— 否则一根没有刚体的普通骨
   「跟着父骨转」也会呈现 0 增量（实测 `下擺_10_7`：0.48° 对 65.83°），那是骨架父子关系，不是冻结。

## A.4 数值证据（输入 → 判定）

| 输入 | SHA256（前 16） | primary | confidence | `judgment_fingerprint` | 证据文件 |
|---|---|---|---|---|---|
| `飞霄_MMD物理_v1.blend` | `b9ba95d3cab9faa9` | **F1** | confirmed | `9650782fc695` | `reports/subai/M03/evidence/blend/probe_v1.json` |
| `feixiao_combined_v3.blend` | `dd6190947468ef2e` | F2 | confirmed | `3f1695bbb24c` | `.../evidence/blend/probe_combined_v3.json` |
| `feixiao_v2_hsr.blend`+飞霄 PMX，f1–f60 | `b957143a0b76cad7` | F4 | suspected | `2819533922cd` | `.../evidence/blend/S3_chest_60f.json` |
| `kafuka_all/scene.blend`+卡芙卡 PMX，f1–f60 | `3df0e033205955b7` | **F3** | confirmed | `fd960f16c1be` | `.../evidence/blend/S5_sleeve_60f.json` |
| 飞霄 PMX（静态） | `2db720a2281a9ea9` | F3 | suspected | `5d71d1431cad` | `.../evidence/static/S3.json` |
| 飞霄 PMX + S8 A/B | `2db720a2281a9ea9` | **F6** | confirmed | `f918267aaf4f` | `.../evidence/static/S8_f6.json` |

8 条样本：`match_confirmed 3 / match_suspected 3 / mismatch 2`；误报 **0**；漏报 5（S1、S2、S3、S4、S6）。
明细见 `reports/subai/M03/sample_manifest.json`、`coverage.json`、`summary.json`。

源文件保护：飞霄 PMX `2db720a2…`、卡芙卡 PMX `287a5556…`、`feixiao_combined_v3` `dd619094…`、
`feixiao_v2_hsr` `b957143a…`、`飞霄_MMD物理_v1` `b9ba95d3…`、`kafuka_all/scene` `3df0e033…`
—— 采集前后两次复算全部一致。

## A.5 未完成与阻塞

1. **F4 无真实 confirmed**：`f4_angle_deg=60°` 未标定；正常舞蹈实测摆角 **179.231°**，阈值明显偏低。
2. **F5 无真实 confirmed**：缺 `blender.penetration`（网格级穿透测量，属 M04）。
3. **S3 胸口动态 UNAVAILABLE**：`feixiao_v2_hsr` 里胸前 6 骨**没有 COPY_ROTATION**，不是冻结现场；
   按「同一故障 3 轮」预算停止找场景，不换文件碰运气。
4. **R0 无真实样本**：S1/S6 都没有逐帧穿透文件，只有合成 fixture。
5. **F2 无独立标签样本**：3 个场景实测到未烘焙，但都是别的故障现场。
6. 跨模块申请：`pmx.py` 增加刚体质量解析（**该文件属 M01**），否则 F4「根部质量」辅助证据拿不到。

## A.6 下一步（唯一一条）

把 `evidence.blender.penetration`（逐帧穿入深度 + 穿入骨 + 帧号）接进 M04 的穿透测量，
一次同时补齐 **F5 真实 confirmed** 与 **R0 真实样本**（两者现在都是 0 真实样本）。schema 不用改。

## A.7 交叉印证与依赖

- **与 M01 互证**：M01 从 PMX 原始字节读出 chest 关节 0/3 旋转与平移限位全 0、弹簧全 0
  （`右胸`/`左胸` 焊在 6 号刚体上）；本模块静态判据 `frozen_roots` 抓到的正是 joint 0 / joint 3。
  两条独立路径互证「胸口是硬约束冻结，不是动力学过冲」。
- **对 M05 的影响**：M05 的 NLA 动态探针因 Blender 锁被 M03 持有而 `BLOCKED`；
  锁已于 **21:19** 释放，`out/subai/locks/` 现为空，M05 可重排 Blender 阶段。
- **给 M04**：消费 `diagnosis.json` 的字段清单在 `reports/subai/M03/handoff.md` §4。
- **给 M07**：CLI 与退出码 `0/1/2/3/4` 在 `handoff.md` §5、`schema.md` §5。

## A.8 回写元信息（本节自身的可追溯性）

| 项 | 值 |
|---|---|
| 回写时间 | 2026-11-15 21:28–21:40（Asia/Shanghai） |
| 回写位置 | 本文档末尾「附录 A」，append-only；§1–§7 原文未改 |
| 追加前文件 md5 | `086f960c40a1062e7e990859bb1dc512` |
| 验证方式 | `python -m unittest tests.test_diagnose`（37 条 OK）+ 两次静态 CLI 指纹一致（`5d71d1431cad`） |
| 仓库交付根 | `E:\dsh pr\woker2\reports\subai\M03\` |
