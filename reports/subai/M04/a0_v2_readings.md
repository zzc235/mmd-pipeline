# M04 A0 正控 v2 读数表（只读重算，不开 Blender）

> 数据来源：`out/subai/M04/penetration/` 里 2026-11-16 15:20–15:24 跑出的四支 `*.meta.json`（`R_free` / `A0_free` / `R_free2` 为 `is_baked=false`，`A240` 为 `is_baked=true`），逐帧 240 帧、`eval_policy=sequential_from_frame_start`。
> 本表的数由 `reports/subai/M04/scripts/m04_a0_table.py` 重算并落盘到 `reports/subai/M04/a0_v2_table.json`；中位数等分位值**此前只印在 stdout、没落过盘**，这份是第一次进文件。
> 判据一律先在**探针分辨率（6 位小数）**上量化再比（`D-143`），raw float 同笔给出。
> 归属：A2 车道（M03→M04），@模块负责2。这是 A0 正控（`D-156` 前后的那批），**不是 A/B/C/D 任何一组的数**。

## 一句话结论

| 问题 | 臂 A → 臂 B | 事实 | 判词 |
|---|---|---|---|
| 探针看得见碰撞状态吗？ | `R_free`（位不动，清缓存，重解） → `A0_free`（位全清，清缓存，重解） | 240 帧里 **239 帧 A0 更深**、1 帧相等；`\|Δ max_depth\|` 中位 **10.878 mm**、均值 10.332 mm、最大 **15.544 mm @ f19**；重叠对数 **41815 → 43619** | **tier=3 仪器有效** |
| 同一场景解两遍一样吗？ | `R_free` → `R_free2`（独立会话再解一遍） | **240/240 帧逐位相同**（Δ=0.0 m，重叠对数 41815/41815，`raw_depth` −97.323/−97.323 mm） | **解算确定** |
| 那份自带缓存能由重解重现吗？ | `A240`（缓存回放） → `R_free`（重解） | 最大差 **71.059 mm @ f88**（−74.536 vs −3.477 mm）、中位 0.42 mm；重叠对数 **23451 vs 41815**；差集中在第 86–90 帧 | **不可重现**（`D-155`，该缓存降级为参考行 `A_cache`） |

## 读数前提（硬条件，缺一条这份表就不成立）

| 臂 | blend | `is_baked` | `is_outdated` | `eval_policy` | 帧数 |
|---|---|---|---|---|---|
| `R_free` | `out/subai/M04/penetration/R_free.blend` | **false** | true | `sequential_from_frame_start` | 240 |
| `A0_free` | `out/subai/M04/penetration/A0_free.blend` | **false** | true | `sequential_from_frame_start` | 240 |
| `R_free2` | `out/subai/M04/penetration/R_free.blend`（独立会话再解） | **false** | true | `sequential_from_frame_start` | 240 |
| `A240` | `out/subai/M02/blend/B_from_blend1.blend` | **true** | true | `sequential_from_frame_start` | 240 |

`is_outdated=true` 在四支里都是 true，**不当好坏用**（健康烘焙件重开后也是 true/true）；这里的分量全在 `is_baked`：三支 `false` 的读数是顺序走帧重新解算出来的，`A240` 那支是缓存回放。

## 分布（不止 max 一个数）

`|Δmax_depth_m|`，240 帧全体；单位 mm，已量化到 1e-6 m：

| 对 | P10 | P25 | **中位** | P75 | P90 | 最大（帧） | 帧数分布 |
|---|---|---|---|---|---|---|---|
| sens：`R_free` vs `A0_free` | 6.087 | 8.602 | **10.878** | 12.419 | 13.266 | **15.544**（f19） | A0 更深 239 / 相等 1 / R_free 更深 0 |
| repro：`A240` vs `R_free` | 0.309 | 0.341 | **0.420** | 1.087 | 2.082 | **71.059**（f88） | A240 更深 202 / 相等 1 / R_free 更深 37 |
| determ：`R_free` vs `R_free2` | 0.000 | 0.000 | **0.000** | 0.000 | 0.000 | **0.000**（f1） | 全等 240 / 240 |

均值：sens 10.332 mm、repro 2.173 mm、determ 0.0 mm。
**repro 那一行要连着读**：中位 0.42 mm 说明 240 帧里大多数帧两只臂差不到半毫米，但 P90 已经 2.08 mm、最大值 71.059 mm——分布是**一条尾巴**，第 86–90 帧一次碰撞事件上分岔。只看中位会得出「缓存基本可用」，只看最大值会得出「完全不可用」，两个都不对。

方向（只有 sens 对有意义）：`overlapping_pairs` 41815 → 43619（+1804 对，与 `max_depth_m` 同向）；`raw_depth_min` **−97.323 → −92.024 mm（反向）**。方向判据只该用 `max_depth_m` 与 `overlapping_pairs` 这两条同向的指标；`raw_depth_min` 测的是窗口内单对最深，碰撞全开后裙片互相穿过再滑开，最深反而变浅——**它反向不是反例，是它测的不是同一件事**，只作参考。

## 自检与对账（表里的数为什么可以发）

`m04_a0_table.py` 自带两段：
- **自检 6 项**（构造序列）：偶数/奇数中位、1e-6 量化边界、max 取真最大。第一版把「0.0004 → 0」写进断言，被自检抓住（分辨率是 1e-6，0.0004 s = 400 µs 本来就该留着）——改了断言与理由，不放过。
- **对账 15 项**：与既有 `a0_free_sensitivity.json` / `a0_free_reproducibility.json` / `a0_free_determinism.json` / `a0_free_perframe_compare.json` 逐项比 `max_abs_delta_m`、`worst_frame`、`overlapping_pairs`、`identical_frames`。**全 PASS，exit 0**。

复算（只读，不开 Blender、不碰锁）：

```powershell
cd 'E:\dsh pr\woker2'
python 'E:\code\mmdpipe-ai\A2\reports\subai\M04\scripts\m04_a0_table.py' `
  --pen 'E:\dsh pr\woker2\out\subai\M04\penetration' `
  --out 'E:\code\mmdpipe-ai\A2\reports\subai\M04\a0_v2_table.json'
```

退出码：0 全对 / 1 有对不上的项 / 2 算不出（产物缺）。**2 不许当 1 读**（`D-155` 那类「验不了」被记成「验过了有问题」是另一个方向的错）。

## 两处缺口（缺口 1 已按 `D-179` 修好；缺口 2 是这张表存在的理由）

1. **`a0_free_determinism.json` 里的 `tier=1 / word=UNMEASURED / verdict=仪器看不见碰撞状态 ⇒ 四组全部作废` 是错位的——已按 `D-20261116-179` 修好。**
   原来是把 A-vs-A0 的判官（`m04_a0_control.py` 里「逐位相同 ⇒ 档 1、仪器瞎」）**原样套在「确定性」这对上**：同一场景解两遍，相同正是要的结果，不是仪器瞎。
   - **判官加 `--question sensitivity|determinism`**：确定性输入 ⇒ `DETERMINISTIC`（**不套三档**：`tier=null`、`tier_applicable=false`，`direction_ok=null`）；两次解算不同 ⇒ `NOT_DETERMINISTIC`；**灵敏度分支一字未动**（档 1/2/3 的分界与判词原样）。
   - **`a0_free_determinism.json` 已按新判官重写**：2 234 B，`sha256=ecc73e95c6ba9de14907cce7d583e6d7245067fa93664c42d3437d9a8b56f2cd`，`word=DETERMINISTIC`、`tier=null`、`verdict=同一场景两次独立解算逐位相同 ⇒ 解算确定（姿态可复现）`；文件里带 `superseded_reason`（「旧判词作废原因：判官套错对象，数据未变」）与旧件哈希。旧件**原样保留**为 `a0_free_determinism_v1_superseded.json`（1 443 B，`d195263c8d5f0c5cd79852929db93d35e09e1bc48bc1c009dcb3b481ab84ef2f`，`tier=1 / UNMEASURED / 仪器看不见`），不删不改——**数据未变，作废的是判词**。
   - **回归护栏 8 条**：`tests/test_m04_a0_judge.py`（套件 541 → 549）。两条主测按裁决写死：确定性输入必须判 `DETERMINISTIC`、**不许**出 `UNMEASURED`；灵敏度输入逐位相同**才**判「仪器看不见」。另有三档分层未挪（档 1/2/3 各一条）、非法 `question` 抛 `ValueError`、CLI 落地 `question` 字段、`--supersedes` 记旧文件哈希。
   - **`D-154` 没有被撤回**：A vs A0 实测 tier=3，四组是解禁状态；「四组全部作废」只属于那份错位文件的旧判词。
2. **旧 `a0_free_perframe_compare.json` 只存了 `max_abs_delta_m`**，中位数只在 stdout。本表把它补进 `a0_v2_table.json`（含 P10–P90、均值、两条 `identical` 口径：「同一帧 max_depth 量化后相等」与「三元组全等」是两件事，sens 对上两个口径都给 1）。

## 这份表不能支撑什么

- **不能支撑 A/B/C/D 任何一组的数**——A0 不进任何判词，四组一个数都还没取。tier=3 说明的是「这台探针在这个场景上看得见碰撞状态」，不是「掩码通道有/没有效果」。
- **不能支撑场景可重现性**：71 mm 那条只说「`B_from_blend1.blend` 自带的那 240 帧缓存不可由重解重现」，不是「这个场景不可重建」（`D-155` 原文口径：场景结构可重建 ≠ 姿态可重建）。
- **不能外推到交付尺度**：A0 只在 `B_from_blend1` 的副本上跑过。交付场景（`delivery_v1`）上 tier 是几，要等 1号 重建完、按 `pose_source=fresh_solve` 重跑才知道。
