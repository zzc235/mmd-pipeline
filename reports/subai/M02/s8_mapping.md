# M02 · S8 映射语义核查（阶段 D 第 1–2 步，离线）

> 生成：2026-11-16（模块负责1 / A1 车道）
> 依据：M02 任务书 §5 阶段 D 第 1–2 步。**只读源码定位**，不启动 Blender，不改任何 `.blend`。

## 1. 结论先说

**mmd_tools 4.5.14 完全不碰 `rigid_body.collision_collections`。**

- 在 `%APPDATA%\Blender Foundation\Blender\5.2\extensions\user_default\mmd_tools` 全树 `.py` 里搜
  `collision_collections` → **命中 0 次**。
- 它消费 MMD 掩码的方式是**在关节/约束层**：把「应忽略碰撞」的刚体对各建成
  `disable_collisions=True` 的约束，或补一条非碰撞约束对象。

这解释了 M02 历史基线里那条观察：**312 个刚体在 Blender 里全是 `collision_collections=(0,)`**——
不是漏配，是这份扩展根本没写过那个字段。

## 2. 源码位置（可复核）

| 位置 | 内容 |
|---|---|
| `core/model.py:1201` | `self.buildRigids(non_collision_distance_scale, collision_margin)` —— **全树唯一调用点**（除定义本身），发生在导入/建链阶段 |
| `core/model.py:1484` | `buildRigids()` 定义 |
| `core/model.py:1491` | `rigid_object_groups[i.mmd_rigid.collision_group_number]` —— 按 MMD group（0–15）分组 |
| `core/model.py:1507` | `for n, ignore in enumerate(obj_a.mmd_rigid.collision_group_mask)` —— **读掩码的唯一位置** |
| `core/model.py:1516-1518` | 若该刚体对已有 joint：`joint.rigid_body_constraint.disable_collisions = True` |
| `core/model.py:1519-1523` | 否则按距离阈值决定是否补一条非碰撞约束（`__createNonCollisionConstraint`） |
| `core/model.py:1452` | `__createNonCollisionConstraint()` 定义 |
| `core/pmx/importer.py:491` | `collision_group_mask=[rigid.collision_group_mask & (1 << i) == 0 for i in range(16)]` —— **位取反**：PMX 的 mask bit=1 表示「参与碰撞」，Blender 侧的布尔语义是「忽略」 |
| `core/pmx/exporter.py:996-999` | 导出时再取反回 PMX 掩码 |

## 3. 映射表（MMD ↔ Blender）

| MMD 侧 | mmd_tools 落到哪 | 是否影响真实碰撞 |
|---|---|---|
| `collision_group_number`（刚体所属 0–15） | `mmd_rigid.collision_group_number`；`buildRigids` 按它建 16 个桶 | 间接：桶只用于配「非碰撞对」 |
| `collision_group_mask` bit n = 0（PMX 语义：不与该组碰撞） | `mmd_rigid.collision_group_mask[n] = True`（忽略）→ 该对刚体建 `disable_collisions` 约束 | **是**，但**只在 `buildRigids` 执行时生效** |
| `rigid_body.collision_collections` | **没有任何写入者**（导入后保持默认 `(0,)`） | 是 Blender 侧真正的碰撞过滤机制，但本扩展没用它 |
| 关节 `disable_collisions` | 由上面第 2 行产生 | 是 |

## 4. 对 S8 实验的直接后果（待 Blender 阶段验证）

1. **改 PMX/MMD 掩码后不重建，穿模不会变**——因为掩码只在 `buildRigids` 里被读一次；导入完成后改
   `mmd_rigid.collision_group_mask` 不会回头改约束。这正是历史基线"A/B 穿模数据逐位相同"的最可能原因。
2. **改 `rigid_body.collision_collections` 才是"动真的"**——它是 Blender 5.2 实际使用的过滤位，
   且当前全模型都在同一个 collection 里，等于**所有刚体互撞不被过滤**。这与"下摆穿腿"这类现象自洽。
3. 因此最小 A/B 实验的**有效变量**是 `collision_collections`，而 MMD 掩码是**无效变量（除非重建）**。
   任务书 §5 阶段 D 第 5 步要求"运行前序列化两版碰撞集合，确认 B 的真实字段与 A 不同"——按上面结论，
   A/B 的差异必须做在 `collision_collections` 上，否则实验无效。

## 5. 仍需 Blender 才能定的事（阶段 D 第 3 步、阶段 E）

- 目标刚体对的点名与它们的 `collision_collections` 现值（要读历史 `.blend`）。
- A/B 两版集合的序列化差异（任务书要求先证明字段真的不同，再谈渲染/穿模）。
- 穿模指标：穿模帧数、累计骨次、最大深度（逐帧 JSON）。

**本文件不构成 S8 结论**；S8 三种状态（`EFFECTIVE` / `NO_EFFECT` / `UNKNOWN_MAPPING`）必须在
A/B 实测之后才能判。

## 6. 一个必须记下的风险

上面第 1 条是**源码推理 + 历史基线一致**，但我**没有**在 Blender 里验证"改掩码后手动重跑
`buildRigids` 会不会改变结果"。若阶段 E 要用它当结论，必须在 Blender 里补一次重跑对照，
否则只能写「源码层面成立、运行时未验证」。

## 7. 阶段的实测补正（2026-11-16 13:37，S8 第三层的前置）

§1 与 §4 的源码推理，在真场景上对了两半、错了一半——**错的一半是我自己踩的假阴性**。

| 事实 | 测法 | 结果 |
|---|---|---|
| 交付场景里有没有 MMD 掩码载荷 | 扩展**未启用**时读 `ob.mmd_rigid` | **读不到**（`dir(obj)` 里没有这些属性）→ 会误判「场景没有掩码」 |
| 同上，扩展**启用后** | `m02_mask_probe_after_enable.py` | **324/324 个刚体都有 `mmd_rigid`**，`collision_group_number` 与 PMX 的 9 个组一致，**28 种不同 mask 值**（如 `128`=只与组 7 碰 ×115、`0`=不与任何组碰 ×30） |
| `mmd_rigid` 的 mask 进不进解算器 | 同上 + 约束清单 | **不进**：`rigid_body.collision_collections` 全部 `(0,)`（20 位里只有 bit0）、`DISABLE_COLLISIONS` 约束 **0 条**；场景里只有 `GENERIC` 3651 条 + `GENERIC_SPRING` 389 条 |
| PMX 侧掩码的实际强度 | 纯 Python 对 312 个刚体两两判 | **19 191 / 48 516 对（≈40%）按 PMX 语义应当互不碰撞** |
| `P9`（关掉 `DISABLE_COLLISIONS`） | `m02_s8_ab.py -- P9` | **被 `REQUIRE_CHANGE` 拒绝**：`disable_collisions_changed_count = 0` —— 场景里没有这类约束可关 |

**所以掩码这条的结论是「结构性未接线」，不是「未测量」**：

- 掩码数据在场景里（`mmd_rigid`）；
- 但它没有任何通往 Blender 解算器的通道（collection 位全 0 = 默认全互撞，且没有 disable 约束）；
- 因此在**本场景**里改 `mmd_rigid.collision_group_mask` 不会改轨迹——这是结构性的零，
  和执行「改了再看」得到零是两件事，前者不需要跑实验、后者还没跑。

**要测「掩码影响量」，前提是先让掩码有通道**（二选一）：把 mask 翻成 `collision_collections` 位，
或按 `core/model.py:1507` 的路子补 `DISABLE_COLLISIONS` 约束。这两条都是产线改动，不是实验参数，
所以 S8 第三层在拿到 D0 的排期前**不该跑**。

**另记一条方法论**：`mmd_*` 是扩展注册的 RNA 属性，**必须在 `addon_utils.enable()` 之后读**，
否则「读不到」会被误读成「场景里没有」——今天我先踩了一次，靠 `s8_mapping.md` §1 的源码结论才发现。

