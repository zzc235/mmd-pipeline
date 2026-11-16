# M02 · 交付工程带着「已烘焙 point cache」，一切"改物理参数看轨迹"的实验都会失效

日期：2026-11-16 · 发现于 S8 阶段 E 的正控 · 影响 M02 的 S2 与 S8，不影响"测量交付动画本身"的结论（M04 的穿透/过冲数字）

> **同日晚些时候的两处更正（P12 / P13 实测，见 `rebake_fix.md` §2.5–2.8）**
>
> 1. `is_baked=true && is_outdated=true` **不是**缺陷的证据：真烘焙件保存后重开**也是**这两个值
>    （`J_baked.blend` 冷跳 f109/f240 对 `P0` 逐位 0.000000）。它只说明「打开时无法证明缓存与当前设置一致」。
>    定性必须靠**行为探针**（冷跳中间帧 vs 从 `frame_start` 顺序重算）。本文下面「缺陷」二字请读作
>    「本文件实测到的这一份产物有缺陷」——`B_from_blend1` 是唯一有行为证据的那一份。
> 2. `point_cache.info` 这句中文提示会随 `.blend` 落盘，**重开后文件里仍有它，但帧数据可能已经不在**。
>    它只当线索，不当证据。

## 一、事实（可复现）

`out/subai/M02/s8/E_base.blend`（= `B_from_blend1.blend` 的副本，sha256 `dd7f6877…`）打开后：

```
rigidbody_world.point_cache.is_baked = True
point_cache.info  = "240 帧数在内存里 (2.1 MiB), 缓存已过期!"
point_cache.frame_start / frame_end = 1 / 326
scene.gravity = (0, 0, -9.81), use_gravity = True
```

`reports/subai/M02/cache_state.json` 是全部被测工程的缓存状态：

| 工程 | `is_baked` |
|---|---|
| `B_from_blend1.blend` / `B_x07.blend` / `B_y07.blend` / `B_z07.blend` / `s8/E_base.blend` | **True** |
| `baseline.blend` / `s2_x07.blend` / `prepared_baseline.blend` / `prepared_x07.blend` | False |

## 二、正控（同一脚本、同一输入、同 240 帧、324 刚体）

| 变体 | 改动 | `frames.jsonl` sha256 |
|---|---|---|
| A | 无 | `b53ceb62…d00f208` |
| B | 324 个刚体 `collision_collections` 全 0 | 同上（逐字节相同） |
| C | `effector_weights.gravity = 0` | 同上 |
| E | `scene.use_gravity = False` + `scene.gravity = (0,0,0)` | 同上 |
| D | 265 个刚体 `kinematic = True` | `5075fd38…`（下摆 18 根跨度 0.000 m） |
| F | 一根下摆刚体物体坐标 +1 cm | `7adde99b…`，与 A 差**恰好 0.010000 m 且逐帧恒定** |

D 变、C/E 不变：能改变"哪些物体参与解算"的改动会触发重算，**只改物理参数的不会**。
F 的差是一段刚性平移，不是动力学响应 —— 真解算里把一根摆动骨挪 1 cm，不会让整段轨迹平移 1 cm。

另一条独立的旧证据：`B_from_blend1.blend` 与 `B_x07.blend` 是两个不同文件（后者 constraint 限位
从 ±1.5708 改成 ±0.7），两版采样 240 帧 × 4320 行**逐字节相同**（`7baa7b98…`）；今天重采（B2r）再验一遍，
仍逐字节相同。改参数得到同一份数字，只有缓存能解释。

## 三、边界：哪些结论作废，哪些不作废

| 结论 | 状态 |
|---|---|
| S8 阶段 E 的 A/B（集合全关 ⇒ 轨迹不变） | **作废**（在回放上取的 0.0），判 `UNKNOWN` |
| S2 的"B2 两版逐字节相同 ⇒ ±0.7 rad 变量未激活" | **作废**（同一条缓存的两份回放） |
| S2 的结论本身（限位没吃到） | 仍可能成立：**未烘焙**的 `prepared_baseline` vs `prepared_x07` 差 7e-5 deg（1.2e-6 rad），但证据强度只到"没吃到"，不是"机器证明" |
| M04 在 `B_from_blend1.blend` 上量的穿透/过冲 | **不作废**：测的是交付动画本身，回放的就是要交付的那条轨迹，几何意义不变 |

## 四、以后每份采样必须记的三项

`meta.json` 增：`point_cache.is_baked`、缓存帧范围（`frame_start` / `frame_end`）、
以及探针有没有主动失效缓存（`probe_freed_bake`，当前一律 `false`）。
本仓库里 **B2 / B2r 两批采样缺前两项**（先于这条要求产出），已在本笔 `known_risks` 中披露。

## 五、下一步（待批）

在**不保存的副本**上 `bpy.ops.ptcache.free_bake_all()`（10 §6 只禁 `bake_all()`），
重跑 A' / B' / A''，才是 S8 的真 A/B。批下来之前 S8 停在 `UNKNOWN`，不动缓存。
