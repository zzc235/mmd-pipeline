# M02 · S8 阶段 E 判据预注册（落盘于开跑之前，跑完不改）

机器时间：2026-11-16T12:56 前后（本文件 sha256 见本轮 SUBMISSION 的 `artifacts[]`；若判据是事后补的，
它的 mtime 会晚于两份 `frames.jsonl`，这是可查的）。

## 实验定义

| 版本 | 唯一改动 |
|---|---|
| A | 原样打开 `out/subai/M02/s8/E_base.blend`（`dd7f6877…`，114… 见 meta） |
| B | 同上，但 **324 个刚体的 `collision_collections` 全部置 0**（= 不属于任何集合 ⇒ 与任何刚体都不碰撞） |

两版都：不存 .blend、不动 `mmd_rigid.collision_group_mask` / `collision_group_number`、
同帧段 1–240、同 `substeps_per_frame` / `solver_iterations`、同观测集。

## 判据（跑之前定死，之后不调）

- **观测集**：`s2_targets.json` 点名的那 18 根 —— `下擺_0_0 … 下擺_0_17`。
- **主判据**：`D = max over (帧 f, 骨 b) |pos_A(f,b) − pos_B(f,b)|`（世界坐标欧氏距离，m）

| 结果 | 判定 |
|---|---|
| `D ≥ 1.0 mm` | `EFFECTIVE` —— 集合字段在驱动解算 |
| `D < 1.0 mm` | `NO_EFFECT` —— 该场景里刚体之间没有互撞 |

- **X = 1.0 mm 的理由（不是事后挑的）**：`matrix_world.translation` 是 float32，1 m 量级的分辨率约
  `1.2e-7 m`；240 帧累积的浮点抖动远小于 0.1 mm。1.0 mm 高于噪声下限约 4 个量级，又低于已知的
  穿入/净空尺度（历史记录 −0.202 m，判据裕度 0.01 m 级）1–2 个量级 —— 落在两端之间的空档，
  不是"贴着噪声"也不是"贴着信号"。
- **次判据（只补记，不参与判定）**：全 324 个刚体上的同一个 `D`。
- **分布要求**：逐帧 `max over 18 骨` 的位移差序列，给 p50 / p95 / p99 / max 与**首次超过 1.0 mm 的帧号**，
  不只给一个最大值。
- **重复性对照（预先声明）**：A 跑两遍 A1 / A2（同一输入、同一参数、同一脚本）。
  **若 A1 与 A2 在任一帧任一刚体上差 > 1.0 mm，本次 A/B 结论作废 → 判 `UNKNOWN` 并升级**，
  因为那意味着本项目此前所有 A/B 对比（含 S2）都不可信。

## 预期

两版除 `collision_collections` 外的序列化差异为 0：`collections.json` 里
`changed_bodies(A) = 0`、`changed_bodies(B) = 324`、`mmd_mask_and_group_untouched = true`。

## 解释表（写死，结果出了照抄）

| 结果 | 结论 |
|---|---|
| `EFFECTIVE` | Blender 层集合字段是真杠杆：将来"不改 PMX 就调碰撞"这条路成立 |
| `NO_EFFECT` | 场景内没有刚体互撞，67° 下摆摆动纯是弹簧驱动 → **F6 穿透门禁与净空判据的存在前提要重估** |
| `UNKNOWN` | 帧集合不一致 / A1≠A2 / 介于 1.0 mm 两侧的边界情况，不硬判 |

## 不做

不存 .blend、不改 MMD 数据层、不换任何实验参数、不加第三个假设、不重跑 S2 的两份副本。

---

## 追加（D0 授权条件四，2026-11-16T13:04，**只追加，上文一字未改**）

**前置条件：`point_cache` 必须为空。** 上述判据只对「真解算」成立；对 `point_cache.is_baked = True`
的输入做同样的 A/B 是在回放缓存（见 `m02_cache_finding.md`，A/B/C/E 四版 `frames.jsonl` 同一个 sha256）。

因此本阶段正式数据改用 `P*` 变体：脚本先 `bpy.ops.ptcache.free_bake_all()`，把调用前后的
`point_cache` 状态写进 `meta.json`，且要求 `point_cache_after_free_bake.is_baked = False`。

判据（1.0 mm、18 根下摆骨）**不变**；本追加不改变主判据，只补一条输入合法性的前置条件。
另按 D0 要求补两条「回放指纹」的反证：

- `P3`（解烘焙 + 挪 1 cm）的结果**不得**是「恰好 1.000 cm、全段逐帧恒定」的刚性平移；
- `P0`（解烘焙重算）与 `A`（烘焙回放）**必须不同**。

## 结论段（D0 要求补，2026-11-16T13:09，只追加）

**`D_hem ≥ 1.0 mm` 只能判「碰撞解算接没接上」，判不了「影响有多大」。**
本场景的解算器既确定性（`P0` vs `P1` 逐位相同）又对扰动极敏感（挪 1 cm 发散到 1.6 m），
在这种混沌系统上，毫米级阈值是**连通性判据**，不是效应量。
因此 `EFFECTIVE` 的正确读法是「刚体集合字段确实进了解算」，不得写成「碰撞造成 8.24 mm 偏差」。

## 预注册（P9，2026-11-16T13:13，尚未跑、等放行）

问题：`mmd_tools` 把 PMX 的 `collision_group_mask` 里「忽略」的对转成 `DISABLE_COLLISIONS` 刚体约束，
**从不写 `collision_collections`**。于是掩码真正的作用点在这批约束上，而 `P2/P5` 动的是集合位向量，
没碰过它们。补一条：

- **`P9`**：解烘焙重算 + 把全部 `rigid_body_constraint.type == "DISABLE_COLLISIONS"` 的约束
  `enabled = False`（= 让掩码认为「该忽略」的那些对重新可以互撞），其余不动；
- 判据同 P2/P4：18 根下摆骨 `D_hem`，1.0 mm，且 `D_hem`（不是 `D_all`）为判；
- 记录 `disable_collisions_changed_count` 与改前/改后的对象名清单；
- 读法：`D_hem ≥ 1.0 mm` ⇒ 掩码（经约束）对摆动有可测影响，M02 的「掩码错配影响量未测」这条缺口补上；
  仍为 0 ⇒ 掩码在这批骨上不参与，缺口改写为「掩码在这些骨上不起作用」而不是「未测」。



