# M02 · attempt 2 · 结果

范围：①批准项「加列重采样」（`bone_world_delta_deg`，只重跑 B2 的 baseline/x07 两版）；②S8 阶段 E 的正控取证与边界判定。
状态：**PARTIAL** —— 重采样完成；S8 停在 `UNKNOWN`（等解烘焙批准）；S2 的原证据作废、替代证据强度下调。

## 一、加列重采样（完成）

| 样本 | 行数 | `frames.jsonl` sha256 |
|---|---:|---|
| `dyn/B2r_baseline` | 4320 | 见 `evidence` 的 `artifacts[]` |
| `dyn/B2r_x07` | 4320 | 同上 |

- 列：`frame, bone, angle_deg, rot_x_deg, rot_y_deg, rot_z_deg, parent_delta_deg, bone_world_delta_deg`。
- 可比性（对旧样逐行比，17280 行/版）：`angle_deg` / `rot_x·y·z_deg` 最大差 **0.0** —— 新列只增不改。
- 新列语义：该骨**世界朝向**相邻帧夹角（度），第 1 帧 `null`；不依赖父链。
- 实测：18 根下摆骨里 `bone_world_delta_deg` 最大 **9.302022°**（`下擺_0_12`），
  非零行 2286 / 4302 —— 冻结判据要的"目标自身在动"这条观测，独立于父链可得。

## 二、正控与缓存发现（新，且改变了两笔结论的效力）

`E_base.blend` 打开即 `point_cache.is_baked = True`（240 帧在内存，范围 1–326）。
同一脚本、同一输入、240 帧 × 324 刚体：

| 变体 | 改动 | 结果 |
|---|---|---|
| A | 无 | `b53ceb62…` |
| B | 324 刚体 `collision_collections` 全 0 | 与 A **逐字节相同** |
| C | `effector_weights.gravity = 0` | 与 A **逐字节相同** |
| E | `scene.use_gravity=False` + `gravity=(0,0,0)` | 与 A **逐字节相同** |
| D | 265 刚体 `kinematic=True` | `5075fd38…`，下摆跨度 0.000 m |
| F | 一根下摆刚体 +1 cm | `7adde99b…`，差恰好 0.010000 m 且逐帧恒定 |

结论与边界见 `m02_cache_finding.md`：S8 判 `UNKNOWN`；S2 原证据（B2 逐字节相同）作废，
替代证据为未烘焙的 `prepared_baseline` vs `prepared_x07`（最大差 7e-5 deg），强度仅到"限位没吃到"。
M04 在 `B_from_blend1.blend` 上的穿透/过冲测量**不受影响**（测的是交付动画本身）。

## 三、下一步

1. 等批准：不保存副本上 `ptcache.free_bake_all()` → 重跑 A' / B' / A''，S8 的真 A/B。
2. 重采样这批的 `meta.json` 缺 `point_cache.is_baked` 与缓存帧范围（先于新要求产出），
   已由 `cache_state.json` 事后补齐，并在 `known_risks` 披露。
