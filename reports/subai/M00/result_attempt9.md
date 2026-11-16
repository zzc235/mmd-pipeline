# M00 attempt 9 · PASS（掩码通道：语义实测 + 位/约束双路 + 放掉挡错的 2196 条 + D-094）

A4 / `ai/a4` / HEAD **`e80f8ac`** / 未 push。本笔覆盖三个提交：
`6bcb60a`（掩码实现骨架 + D-094 `WRONG_TESTS_FIELD`）、`e80f8ac`（语义实测修正 + 双向打通 + 上限护栏）。
`13c4ff7`（attempt 8）已并入 main `88e971e`，不在本笔。

## 一、先钉语义——这一步做错，全部读数会整体反号

我第一版按「原始位置位 = 与第 i 组碰」写的，读数全是反的（当时报「不该碰 4535 对」）。
钉住之后是 **7367 对**。证据链三步，缺一条都不够：

| 证据 | 内容 |
|---|---|
| 导入器 | `mmd_tools/core/pmx/importer.py:491` `collision_group_mask[i] = (raw & (1<<i)) == 0` ⇒ **属性 True = 与第 i 组碰**；PMX 原始位是「非衝突フラグ」（置位 = 不碰） |
| 导出器 | `pmx/exporter.py:996-999` 反向写回，往返一致（所以不是导入器单边写错） |
| **名字** | 组 5 的 48 个刚体全是 `HairA1_JNT…`（头发），mask `0xffdf` = 除 bit5 外全置位。只有「置位 = 不碰」能得出「头发只与头发碰」；反读得出「头发与头发不碰、与身体全碰」——而头发刚体与身体在静止姿态就重叠，那样必然炸开。组 4 是 `zxk__*`（裙子，`0xff2f` = 除 {4,6,7} 外全置位）同理 |

**Blender 侧语义是实测的**（`tests_bpy/mask_semantics_probe.py`，5.2.2 LTS，40 帧重力下落）：

| 实验 | 读数 |
|---|---|
| D(bit1) 落到 G(bit1) 上 | 停在 **z = 1.000** → 共享位就碰 |
| D(bit1) 落到 G(bit2) 上 | 掉到 **z = −9.704** → 不共享就穿 |
| D(bit1+bit2) 对 G(bit1) / G(bit2) | 两侧都被挡（都停 1.000） → **一侧有位就够**（不是双向声明） |
| 全 0 位 vs 全 1 位 | 快照不同（单元级判据的机器版） |
| `collision_collections` 长度 | **20 位**（写 16 项抛 `ValueError`），16..19 恒 False |

## 二、位编码与代价

`collision_collections = mask | (1 << own_group)`。加自己组那一位是**可证**的：PMX 该碰的一对，
同组则两位都落在自己组的位上；不同组则 A 的 mask 含 bit(g_B)、B 含自己组的 bit(g_B) ⇒ 必然共享。
所以「PMX 该碰却无共享位」恒为 0——实测也确实是 0。

145 刚体 / 10 440 对（真 PMX）的分账：

| 项 | 数 |
|---|---:|
| PMX 该碰 | 3 073 |
| PMX 不该碰 | **7 367**（70.6%；1号 在交付场景上测 40418/52326 = 77.1%，同量级） |
| 其中靠位自己就分开 | 5 818 |
| 其中需要补 `DISABLE_COLLISIONS` | **1 549** |
| 表达不了（该碰却无共享位） | **0** |
| 单向掩码（一侧允许、另一侧不允许） | 1 462 |

## 三、既有场景里有一批**挡错的**约束，必须放掉

这条是我自己测出来的，不是推断。`J_baked.blend`（sha256 `e22e03f5…`，13:28:32，未变）只读前态：

```
rigid_objects 323（mmd_type=="RIGID_BODY"）
collections 只有 1 种位型 {0001}，323/323  ← 与 1号 的「全 bit0」一致
带 disable_collisions 的约束 4009 条（ncc 3651 + JOINT 358），覆盖 4009 对
  ├─ 挡错（PMX 说该碰）     2196 对   ← 例：下擺_6_11 × 下擺_6_12（两条同在下擺组）
  └─ 挡对（PMX 说不该碰）   1813 对
```

⇒ `mmd_tools` 的 `buildRigids()` 相对它**自己的导入器**是反的（`if not ignore: continue`
把「属性 = True 即与该组碰」当成了「忽略」）。所以只补不放，"通道接上"了仍会静默停碰 2 196 对。
`apply_collision_masks` 因此有第 3 步：对挡错的对置 `disable_collisions=False`
（**不删对象**，可逆的最小动作），计入 `constraints_released`。

## 四、接口（spec §1，可单独作用于已存在场景——2号 的 B 组直接用）

```python
stage.apply_collision_masks(scene=None, *, collection_index_of=None, max_constraints=None) -> dict
```

四步：① 写位（`collections_set` / `objects_modified` / `objects_touched_outside_mmd_rigid`）
→ ② 逐刚体回读（`readback_mismatch`）→ ③ 放掉挡错的（`constraints_released`）
→ ④ 补该挡的（`constraints_added`）。纯逻辑在 `mmdpipe/mask.py`（不 import bpy），
bpy 侧只有薄封装，所以「同一套映射只有一份实现」。

## 五、验证（真 Blender，探针随本笔入库）

**145 刚体全模型**（93.3 s）：

| 项 | 读数 |
|---|---|
| 位分开 + 补约束 + 仍互撞 | 5 818 + 1 549 + **0** == 7 367（**加总严丝合缝**，spec §1c 的等式） |
| `readback_mismatch` | 0 |
| `objects_modified` / `objects_touched_outside_mmd_rigid` | 145 / **0** |
| 源数据（组号/掩码） | `source_unchanged = True` |
| 幂等 | 第二次 `constraints_added=0`、`released=0` |
| `unexpressible` / `verdict` | `[]` / **WIRED** |

**40 刚体快检**（1.7 s）：400 + 37 + 0 == 437，同样 WIRED。
**上限护栏**（应当被拒的输入 `--max-constraints 5`）：`capped=true`、`skipped` 32 条逐条带 reason、
仍互撞 27、**verdict=PARTIAL**（被 cap 的 run 不许判 WIRED）。

## 六、代价：大场景必须走建场路径（自报，含一次跑飞）

逐对象 `bpy.ops.rigidbody.constraint_add()` 每次触发整场景 depsgraph 求值，而 `J_baked` 有
**12 个依赖环 / 323 个刚体**：两次尝试分别跑到日志 **459 MB / CPU 1780 s** 与 **339 MB / 1240 s**
仍未完成，我手动掐断（`rbw.enabled=False` 与 `point_cache.frame_end=1` 都拦不住——create 约束会
重置缓存）。145 刚体 / 1549 约束 ≈ 93 s（≈60 ms/条）可作参考。
⇒ **通道要在 `stage_build` 建场时接**（那时刚体还没烘焙），事后 apply 只适合小场景。
这条也解释了我为什么没在 `J_baked` 上打出后态：不是没做，是那条路代价不可接受，已改成
「小场景全链路 + 交付场景走建场路径」。

## 七、验证（三环境）

| cmd | exit | 结果 |
|---|---:|---|
| `discover`（默认） | 0 | **370 passed / 0 failed / 15 skipped** |
| `discover` + `PYTHONIOENCODING=utf-8` | 0 | 370 / 15 |
| `discover` + `PYTHONIOENCODING=gbk` | 0 | 370 / 15 |
| `tests.test_stage_mask` | 0 | 23 passed（含「全 0 与全 1 位必须不同」「非对称被检出且仍精确」） |
| 护栏 | 0 | `scanned=132 violations=0 skipped=0` |

## 八、`known_risks`

- 位编码对**单场景**实测「表达不了 = 0」，但那是这 145 个刚体的性质（有证明支撑：见第二节）；
  新模型若出现「该碰却无共享位」，`unexpressible` 会逐条进 `skipped[]`，不会静默。
- 非对称掩码 1 462 对：**精确处理靠约束**（不是近似），所以 `skipped` 为空——这与 spec §4.3
  的字面要求（非对称 ⇒ `skipped` 非空）不同，理由写在 `plans()` 的说明里：没有东西被跳过。
- 事后 apply 的代价随刚体数与依赖环数非线性上升，未做大场景基准；只用小场景验过。
- 「通道接上 ⇒ 此前所有物理数字作废」是预期行为（spec §5），不是本笔的缺陷。
- `1号` 的前态数 40418/52326（324 刚体）与本笔 40095/52003（323 刚体）差值来自刚体数差一个，
  不是口径分歧。
