# M02 交接（截至 attempt 3，2026-11-16T13:10）

给 M07（面板/门禁接线）与 M08（总验收）的一份事实清单：哪些可用于下游、哪些只能当"输入受限"的数字用。

## 一、可复用的接口

| 接口 | 位置 | 状态 |
|---|---|---|
| `patch_save(model, dst, joint_limit=...)` | `mmdpipe/pmx.py` | 入库（A1 `714d2b9`，已合 main）；字节级守卫 + 23 条测试 |
| `s2_targets.json` | `reports/subai/M02/` | 18 根下摆骨（`下擺_0_0 … 下擺_0_17`）与各自关节/刚体索引 |
| 动态采样列 | `dyn/*/frames.jsonl` | `frame, bone, angle_deg, rot_x_deg, rot_y_deg, rot_z_deg, parent_delta_deg, bone_world_delta_deg` |
| 判据/实验脚本 | `reports/subai/M02/scripts/` | 见下 |

## 二、三个观测量各自的参考系（别混用）

| 列 | 含义 | 与限位可比？ |
|---|---|---|
| `angle_deg` | 该骨相对父骨的**合成**转角（四元数角） | 否 |
| `rot_x/y/z_deg` | 同一相对旋转的欧拉分量 | **`rot_x_deg` 与 `limit_ang_x` 同一轴** |
| `parent_delta_deg` | 父骨相邻帧转角增量 | 否（冻结判据用） |
| `bone_world_delta_deg` | 该骨**世界朝向**相邻帧夹角（每帧增量） | 否 |

## 三、必须写进出处的限制

1. **`B_from_blend1.blend`（= `E_base` = `G_base`，`dd7f6877…`）带 `is_baked=true && is_outdated=true` 的缓存。**
   打开 + `frame_set` 走的是**缓存回放**（P7：单帧跳到 f109 与逐帧步进逐位相同，与解烘焙重算差下摆 **0.9087 m**）。
   ⇒ 凡基于该文件、且**没有解烘焙**的轨迹数字，出处栏写：
   *「输入缓存 `is_outdated=true`；同一文件解烘焙重算后下摆 18 根差 0.91 m；哪条是渲染真正发生的动画尚未判定」*。
   **注意（P13 更新）**：`is_baked=true && is_outdated=true` **本身不是缺陷证据**——真烘焙件重开后也是这两个值。
   这一份之所以是**真坏**，是因为**行为探针**测到它冷跳 == 旧回放、与重算差 1.5867 m（`cache_gate_inventory_v2.json` 里唯一的 `DEFECT`）。
2. **任何「改一个量 → 看轨迹有没有变」的实验**，`point_cache.is_baked` 必须先落进证据；
   `is_baked=true` 的输入不得作为 A/B 实证。脚本护栏：`m02_s8_ab.py` 对 baked 输入且非 `P*` 变体直接拒绝运行。
3. **交付工程与本项目重算不是同一条动画**（0.91 m / 1.62 m）。门禁要说清量的是哪条。

## 三·五、交付契约（D0 13:31 裁定 **B：烘焙**）

| 条 | 内容 |
|---|---|
| 1 | 交付 `.blend` 用 `bpy.ops.ptcache.bake_all(bake=True)` 烘焙；**随件给 sidecar** `*.cache_state.json`（`is_baked` / `is_outdated` / `info` / `bodies` / `use_disk_cache` + `verdict`），生成器 `cache_state.sidecar(record)` |
| 2 | 烘焙产物**必须过行为探针**才算数：冷跳一个中间帧 == 从 `scene.frame_start` 顺序重算的同一帧（P13：f109、f240、整段 240 帧均逐位相等） |
| 3 | `point_cache.info` **不可作为证据**（重开后它仍写「326 frames in memory」，数据可能已经不在） |
| 4 | §6 的 `bake_all` 禁令有**常驻豁免**，四条：只在副本上、每场景单次、崩溃只记退出码不重试、成功也必须过行为探针 |

代价（实测）：**32.2 s / 场景**，`J_baked.blend` 11.94 MB（未烘焙 11.29 MB），**不要求磁盘缓存**（`use_disk_cache=false` 也成功）。
低成本的降级路仍在：解烘焙 + 「必须从 `scene.frame_start` 顺序求值」——适用于渲染整段，不适用于「只渲染中段 / 并行抽帧」。

## 四、结论清单（供 M08 引用）

| 结论 | 状态 | 出处 |
|---|---|---|
| ±0.7 rad 限位对 18 根下摆骨**永不触发** | 已确认（解烘焙重算，逐位 0.000000 m） | `s2_cachefree_limit.json` |
| 收紧到 0.5 rad 同样零效果 | 由上一行推出（±0.7 已是精确零） | — |
| 限位**确实接线**（不是未接入） | 已确认（±0.001 rad → 5.53 mm） | `s2_cachefree_limit_absurd.json` |
| Blender 层 `collision_collections` **进解算** | 已确认（全关 → 8.24 mm；只断地面 → 3.62 mm） | `s8_ab_cachefree.json`、`s8_P5_noground.json` |
| 「场景里没有刚体互撞」的假设 | **被证伪** | 同上 |
| 掩码（`collision_group_mask` ↔ PMX `disable_collisions`）错配的**影响量** | **未测量** | `s8_mapping.md` |
| 单场景单动作（躺姿）外的外推 | **未验证** | — |
| **烘焙可用**：`bake_all` exit 0、32.2 s、326 帧、冷跳逐位等于重算 | 已测（P13，单次） | `P13_bake.json`、`P13_cmp.json`、`P13_cmp_f240.json` |
| **旗标不能定性**：真烘焙件重开后也是 `true && true` | 已测（P13 vs P7） | `cache_state.py` 文档头 |
| **「跑一遍再存盘」救不回来** | 已测（P12） | `p12_cmp.json` |
| **交付场景不可由当前代码重建**（312 vs 324 刚体） | 已测 | `rebuild_finding.md` |

## 五、脚本一览

| 脚本 | 用途 |
|---|---|
| `m02_s8_ab.py` | A/B/正控 + `P0…P6`（解烘焙重算）；对 baked 输入有拒绝护栏 |
| `m02_s8_compare.py` | 18 根下摆骨 `D_hem` + 分布 + 判据（1.0 mm） |
| `m02_s8_index.py` | 全部对比的索引表 |
| `m02_s8_p7.py` | 单帧跳转判别（回放 vs 重算） |
| `m02_dynamics_probe.py` | 240 帧×18 骨逐帧采样（含 `bone_world_delta_deg`） |
| `m02_cache_state.py` | 批量读 `.blend` 的 `point_cache` 状态 |
