# M03 · 已知限制（覆盖缺口与判据边界）

> 结论先行：**六类判据中，F2 没有独立的真实样本标签，R0 没有可用的真实测量文件，
> F4/F5 没有任何真实 confirmed 样本。** 能到 confirmed 的只有 F1、F3、F6。
> 任何"六类都验过了"的说法都不成立。

## 1. 覆盖矩阵（按不同证据文件去重，见 `coverage.json`）

| 标签 | 真实证据文件 | confirmed | suspected | 合成 fixture | 缺口 |
|---|---:|---:|---:|---:|---|
| F1 | 1 | 1 | 0 | 1 | — |
| F2 | 3 | 3 | 0 | 1 | **无独立样本标签**（项目书 8 条没有一条标 F2） |
| F3 | 4 | 1 | 3 | 1 | S3 胸口动态证据 UNAVAILABLE |
| F4 | 4 | 0 | 4 | 1 | **缺真实确认样本**（阈值未标定） |
| F5 | 4 | 0 | 4 | 1 | **缺真实确认样本**（无穿透测量） |
| F6 | 1 | 1 | 0 | 1 | — |
| R0 | 0 | 0 | 0 | 1 | **无真实样本**：S1/S6 都没有逐帧穿透文件 |
| UNKNOWN | 0 | 0 | 0 | 1 | 无真实"健康样本"做阴性对照 |

## 2. F2：没有干净的 F2 样本

项目书的 8 条里没有一条标 `F2 没烘焙`。本轮在 3 个 `.blend` 上实测到
`is_baked=False`（S7 的 `v1` 场景 f1–f240、S1 的 `combined_v3` f1–6570、S5 的卡芙卡 f1–833），
但它们是 F1/F3 的现场，F2 只是伴随状态。

按任务书要求，F2 的**最小正例由合成 fixture 提供**（`tests/test_diagnose.py::fixture_f2`），
覆盖率里按 `synthetic_fixture=1` 记，不冒充真实样本。

## 3. R0：分类学有位置，但没有真实测量

* S1（`feixiao_combined_v3.blend`）是**修复后**的场景，R0 是历史症状；
* S6 只有定性结论，没有穿透 JSON；
* 本轮没有启动长渲染去补穿透矩阵（预算与串行资源都不划算）。

因此 R0 只有合成 fixture（`fixture_r0`）与 `known_numbers` 里的历史基线。
**S1/S6 在 `summary.json` 里按 `mismatch` 记，不算通过**，且 R0 建议单列为新标签
（`taxonomy_version` 里的 `R0`），不要塞回 F5/F6。

## 4. F4：「大角度实测」是代理指标，未标定

`blender.unit_angles.max_angle_deg` 的定义是**采样区间内该单元骨相对 f1 的世界旋转最大变化**。
它不是"布片离竖直多少度"，也不是"离水平多少度"。选它的原因：不依赖具体骨骼轴向，
MMD 各模型的坐标约定不一致。

代价：一段正常舞蹈里，裙摆单元的最大旋转变化实测到 **179.231°**（`feixiao_v2_hsr` f1–f60），
远超 60° 阈值 —— 所以 F4 在"有动"的场景里几乎总会命中 `suspected`。
在阈值标定之前，这条判据只能用来**提示**，不能用来**定罪**。

要标定需要：同一模型只改根部限位（S2 的做法），逐帧记"布片与竖直的夹角"，
再回头看 60° 是否合适。这属于 M04 的门禁标定，不在 M03 做。

`pmx.py` 没解析刚体质量，所以"根部质量 20 kg"这条辅助证据本轮**拿不到**
（`structure.mass_available=false`）；Blender 侧能读到 `rigid_body.mass`，
但本轮没有把它映射到物理单元，只在 `blender.rigid_mass_max_kg` 里记了最大值。

## 5. F5：有结构、没有穿透

`coverage.gaps` 能精确说出"哪一行的哪些骨没有刚体"（飞霄 `下擺` 行 11：11/11 全部缺），
但 `blender.penetration` 本轮始终为空 —— 穿透需要网格级测量（M04 / `phys_probe` 的活），
M03 的 Blender 适配器只采骨骼与刚体状态，不碰 evaluated mesh。

所以 F5 在本轮的 4 个证据文件里全是 `suspected`。要 confirmed，M04 把
`penetration: [{frame, families, bones, max_depth_m}]` 填进 evidence 即可，schema 不用改。

## 6. F3：两类已知偏差

**（a）S3 胸口：结构在，动态不在。**
PMX 静态抓到 7 个焊接冻结根，其中 `右胸`（joint 0）、`左胸`（joint 3）焊在 `上半身2`
上、6 自由度全锁 —— 与项目书 S3 完全一致。但可用候选场景 `feixiao_v2_hsr.blend`
里**胸口骨没有 COPY_ROTATION**（约束直方图 264 条，胸前 6 骨一条都没有），
说明那不是"胸口冻结现场"。按预算（同一故障 3 轮）停止继续找场景，
S3 的动态证据记 **UNAVAILABLE**，F3 只到 `suspected`。

**（b）焊接但不绑骨的碰撞体被排除。**
卡芙卡 PMX 有 22 个焊接冻结根，其中 6 个 `target_bone` 为空（纯碰撞体）。
它们冻不冻不影响任何骨，故 `structure.frozen_roots` 里带 `bone_bound=false`，
F3 只按绑定骨骼的 16 个根判定。没有这个过滤，卡芙卡的 F3 计数会从 16 虚增到 22。

**（c）已知漏报类：两个 mode1/2 刚体之间的焊接关节。**
`frozen_roots` 只认"一侧会回填骨骼、另一侧不参与解算"的焊接。
两个回填体互焊（布料段做硬支撑，MMD 里常见且常是**故意**的）不会被判成冻结根。
这类结构会让该骨的局部增量恒为 0，视觉上确实"僵"，但分不清是设计还是 bug，
所以宁可漏，不误报。

## 7. 判据之外的硬边界

| 边界 | 原因 |
|---|---|
| 不判 substeps/阻尼/iterations | 项目书 §5 明确：那是判据树最后一级，不是 F1–F6 |
| 不用 `matrix_basis` 做因果 | 必须看世界矩阵（世界矩阵或 evaluated 顶点） |
| 不读单帧跳读当动力学证据 | 未烘焙场景必须从 f1 连续步进，`evidence_mode=stepped` 可查 |
| 不判出框/构图 | 只能看渲染像素，不在归因范围 |
| 不比对 PNG 字节判"画面是否相同" | S8 实测：字节不同（编码元数据），像素 0/512000 不同 |
| 不自动找替代工程 | S4 的规范文件已不存在，写 `missing`，不拿 `_废弃`/`.blend1` 顶替 |

## 8. 给下一轮的补采清单（按性价比排序）

1. **穿透测量**（一次 `phys_probe` 风格的逐帧穿透）→ 同时补齐 F5 confirmed 与 R0 真实样本；
2. **F4 阈值标定**（单变量改根部限位 + 逐帧角度）→ 把 F4 从 suspected 提到 confirmed；
3. **S3 胸口场景定位**（哪个 `.blend` 里胸前 6 骨有 COPY_ROTATION）→ F3 就能从静态 suspected 变 confirmed；
4. `pmx.py` 补质量字段（**跨模块申请**，M01 拥有该文件）→ F4 的根部质量证据；
5. `mmd_tools` 扩展只读核对：`mmd_rigid.collision_group_mask` → `rigid_body.collision_collections`
   的映射（S8 的根因），需要 Blender 侧读 `mmd_rigid` 属性，属 M07 的接口冻结之后。

## 9. 覆盖缺口表（2026-11-16 第二轮，M03 → M04 交接）

由 `scripts/m03_coverage.py` 生成 `coverage.json`，数字不手抄。8 条样本：
**match_confirmed 3 / match_suspected 3 / mismatch 2（S1、S6）**。

| 类别 | 有标签样本 | 真实 confirmed | 缺口 |
|---|---|---|---|
| F1 | S7 | S7 | — |
| F2 | 无 | S1/S5/S7（别的主故障场景） | 无独立标签样本 |
| F3 | S3、S5 | S5 | S3 只有静态证据 |
| F4 | S2 | 无 | 阈值 60° 未标定，须等 M02 S2 实测 |
| F5 | S4 | 无 | 缺 penetration 逐帧穿入深度（M04） |
| F6 | S8 | S8 | — |
| R0 | S1、S6 | 无 | 只有合成 fixture |

三条口径修正（都会改变数字，所以写下来）：

1. **不叫「误报」**：8 条样本没有一条是「该类故障明确不存在」的阴性样本，多故障共存本来就允许。
   S1/S5/S7 里 F2 同时 confirmed 是事实（`is_baked=False` 可复核），记作「额外确认」而不是误报。
2. **分母按样本条数**，不按证据文件数：同一飞霄 PMX 被 7 条样本复用，按文件去重会虚增。
3. **可重放回归 20 份证据里 19 份逐位复现**；唯一未复现的是 `evidence/S3_static.json`，
   结论未变（F3 suspected）但指纹早于 F3 候选过滤修正，已被更新的证据取代，不冒充一致。
