# 掩码通道口径（D0 起草 2026-11-16 14:05，`D-075` 的实施口径）

本文件是**口径**，不是实现。4号 按它实现，D0 按它验收。与模块书冲突时以本文为准（理由写进 `decisions.jsonl`）。

## 0. 为什么要这一件

实测（`D-075`）：交付场景里 324/324 个刚体都带 `mmd_rigid.collision_group_mask` 载荷（28 种不同取值），但

- `collision_collections` 全为 `(0,)`（20 位里只有 bit0），
- **`disable_collisions` 约束：条数 `NOT_MEASURED`（原报「0 条」是仪器错，已撤回，见 `D-114`）**。
  `DISABLE_COLLISIONS` **不是** `rigid_body_constraint` 的类型（枚举只有 `FIXED/POINT/HINGE/SLIDER/PISTON/GENERIC/GENERIC_SPRING/MOTOR`），
  它是约束上的一个**布尔** `rbc.disable_collisions`；mmd_tools 的 ncc 物体就是 `type="GENERIC"` + `disable_collisions=True`。
  按类型数它**永远为 0**，与场景里有没有无关。场景里现有 `GENERIC` 3651 + `GENERIC_SPRING` 389，其中 ncc 条数待 1号 的探头 v3 复测。

⇒ 解算器跑在「谁跟谁都碰」上。按 PMX 语义两两判，**19 191 / 48 516 对（≈40%）本应互不碰撞**。
改掩码不会改轨迹——不是「测出来没影响」，是**没有输入通道**。

## 1. 交付物（4号 提供的最小接口）

一个纯函数 + 一个可跑的探针，**不写实验脚本**（实验由 1号/2号 自己接）：

```python
apply_collision_masks(scene) -> dict
# 逐刚体把 mmd_rigid 的组号与掩码翻成 Blender 的 collision_collections 位，
# 并按互不碰撞语义补 DISABLE_COLLISIONS 约束。
# 返回统计：bodies, groups_seen, mask_histogram, collection_patterns, separated,
#           separated_symmetric, separated_asymmetric_unexpressible,
#           constraints_added, skipped[], read_failures, blender_semantics
```

`skipped[]` 必须逐条列出（刚体名 + 原因），**不许静默跳过**（`D-086`）。`read_failures` 必须单独计数（`D-101`：读不到 ≠ 不存在）。`blender_semantics` 是本文件 §2 那次实测的结论（`intersection` / `oneway` / `membership`），**必须由实测填，不许写"未测"就交货**。

## 2. 语义映射（这是本文档的核心，实现前必须先认同）

PMX / mmd_tools 语义（`mmd_rigid` 上就有）：

- `collision_group`：该刚体**属于**哪一组（0–15）；
- `collision_group_mask`：该刚体**与哪些组碰撞**。**实测事实（1号 14:04）：它是 16 个布尔（位集合），不是 int。**
  ⇒ 读它必须按位折算（`bits |= 1 << i for i, flag in enumerate(value)`），**不许 `int(value)`**——
  1号 的第一版就是 `int(mask)` 抛 `TypeError` 被吞掉，于是「不该互撞的对」算成 0，输出读起来像「PMX 里没有这种对」，实际差 40 418 对。

## 2.5 场景级现状基线（1号 的探头实测，`J_baked.blend`）

```
VERDICT UNWIRED  patterns=1  disallowed_pairs=40418  separated_by_bits=0
rigid_objects 324   mmd_rigid_objects 324   mask_read_failures 0
distinct_group_mask 28   distinct_group_number 9
collection_patterns 只有 1 种（全 bit0，324/324）
separated_by_constraint 待测（原报「disable_collisions 约束 0 条」是仪器错，已撤回，见 `D-114`）
```

324 个刚体共 52 326 对，其中 **40 418 对按 PMX 掩码不该互撞，而按碰撞位看一对都没被分开**。

**注意措辞**：能说的是「**按 `collision_collections` 位看，separated = 0**」；不能说的是「掩码完全没进解算」——
场景里存在大量 `disable_collisions = True` 的约束（mmd_tools 的 ncc 物体，`type="GENERIC"`），
它们**部分地**在挡碰撞，只是不按 PMX 掩码挡。

**已知的双向错配（结构判断成立，量级待测 —— `D-118`）**：

- **漏挡**：40 418 对按 PMX 该互不碰撞的刚体对，按碰撞位看一对都没被分开（**这个数是测过的**：1号 探头与 2号 导出表两条独立路径逐位相同）；
- **错挡**：场景里存在 `disable_collisions = True` 的既有约束，其中一部分挡的是**本该互碰**的对。
  **条数：待测**，且**必须分文件报**——`J_baked.blend`（`e22e03f5…`）由 1号 的 v3 探头出，`B_from_blend1.blend`（`dd7f6877…`）由 2号 的 B 组 `constraints_released` 出。
  **那两个文件不是同一个**（11 940 653 vs 11 283 023 B，差 645 KB），任何一方的数**不许漫游到另一方**。
  （来源：4号 `mmdpipe/mask.py` 的注释自报 `J_baked.blend` 4009 条里 2196 条挡错；该数**未进任何 artifact**，不得当作已测引用。）
  ⇒ 交付场景的碰撞是**既漏挡又错挡**，不是单向的「谁跟谁都碰」。凡引用「按全互撞解算」这句话的地方，都要改成「按碰撞位未接、且存在错挡约束的解算」，**不含量级**。

**双路交叉校验（1号 的探头 / 2号 的导出表，两条路径互不依赖）：`52326 / 40418` 逐位相同。**
2号 的分层对账（同一份交付物）：

| 层面 | 对 | MMD 判不互撞 | 比例 |
|---|---:|---:|---:|
| 全场景（324 刚体） | 52 326 | 40 418 | 77.24% |
| ROI（18 根 `下擺_0_*` × 306） | 5 508 | 3 276 | 59.48% |
| 基线里「有重叠」的骨对 | 92 | **36** | **39.13%** |

分界线：允许互撞的 56 对全部是**裙摆×裙摆**（组 8、掩码 128）；判不互撞的 36 对全部是**裙摆×身体**，对面是 `kinematic=True` 的静态体，其中 `下半身` 的掩码是 **0（不与任何组碰）**。

⇒ 两条对验收有用的推论：

1. **绝对口径那批数（已作废）在通道接通后会大幅消失**——它们的来源正是「掩码说不该碰、解算里照样碰」的对；
2. **基线相对口径那批数的配对机制不在这个集合里**（允许互撞），所以不会因掩码而**结构性**失效；但轨迹会变，**仍必须重取**——「机制还在」不等于「数字还在」。

Blender 语义（`rigid_body.collision_collections`，20 位布尔）——**以下是 D0 的理解，尚未实测，实现者必须先验证再照做**：

- 一对刚体碰撞当且仅当存在某一位 i，使两者的第 i 位都为真（交集非空）。

> **这一条必须先被实测钉住，不能拿它当前提开工。** 验证方式（4号 做，5 分钟内）：造三个刚体，A 只开 bit1、B 只开 bit2、C 同时开 bit1+bit2，跑几帧看 A/B 是否互穿而 A/C 是否碰撞。三种结果各自对应一种语义（交集 / 单向 / 成员+碰撞同一位），**按实测语义再决定映射**，并把实测读数写进返回值。
>
> 如果实测发现 Blender 的位是「成员即碰撞」的单一位语义（即两个刚体共享某位就碰），那么 §3 的映射要改成「每位对应一组，刚体加入自己组所对应的位」，并且**非对称掩码的处理方式会不同**——那时以实测为准，本文档按实测更新后再实现。

⇒ **Blender 的交集模型无法表达非对称掩码**：若 A 想碰 B 而 B 不想碰 A，交集语义一定给出碰撞。
这不是实现瑕疵，是模型限制，因此：

1. **实现只保证「对称掩码」下的语义等价**；非对称掩码必须**逐条计入 `skipped[]`** 并在返回值里给出计数，不许静默近似。
2. 对称性判据可机械算：对每对 (A,B)，`mask_A[g_B] == mask_B[g_A]`。非对称的对数必须在返回值里报出来（今天的交付物上是多少，实现完要报一个数）。

**本节第 1、2 条要在实现里落成代码，不是文档声明。** 验收时会喂一个非对称的合成场景，返回值必须报出非对称对数 ≠ 0。

## 3. 位映射（要在实现里写死，不许"看着像"）

- 组号 `g = collision_group`，掩码位 `mask[i]`（i ∈ 0..15 有效，16..19 保留为假）。
- 每个刚体：`collision_collections[i] = mask[i]`，**并且**必须让「自己所在的组」参与判定（否则两组互相掩码开启的刚体不会碰）。
  具体采用「`collision_collections[g] = True` 加上 `mask` 位」还是「直接用交集可满足的等价编码」，**由实现选定并在 `--help`/文档里写明理由**；本文只要求：
  1. **不得改变刚体的 `collision_group`/`collision_group_mask` 本体**（源数据只读，`AGENTS.md` 第五条）；
  2. 映射必须是一对一可回读的（见 §4）。
- **`disable_collisions` 是约束上的布尔，不是约束类型**（`D-114`）：mmd_tools 的 ncc 物体是 `type="GENERIC"` + `rbc.disable_collisions = True`。
  实现要按**布尔**数、并按 `object1`/`object2` 收成「被约束挡住的刚体对」集合；**不许按 `rbc.type` 数**（那样永远为 0，与场景无关）。
  若实现选择用碰撞位表达互不碰撞、不再补约束，必须在返回值里说明走的是哪条路，并报现有 ncc 约束的条数与它挡住的补集。

## 4. 验收（D0 会逐条执行，缺一条不算过）

### 4.0 `WIRED` 的唯一定义（`D-20261116-145`，两份实现都必须实现这一条）

`WIRED` ⟺ **四条同时成立**：

1. `distinct_pattern_count >= 2`（位型不止一种）；
2. **逐刚体回读全符**（`readback_mismatch == 0`）——写进去的位与算出来的位一致；
3. **覆盖面齐全**：PMX 说不该碰的每一对，都被分开（位或约束），即 `nocollide_pairs_still_colliding == 0` 且 `blocked_and_should_collide == 0`；
4. **没有被 cap、没有被跳过**：`constraints_capped == false` 且 `skipped == []`。

任一条不成立 ⇒ `PARTIAL`（能指出命中哪一条）或 `EMPTY`（一条位都没读到）。

**为什么要把第 3、4 条写死**：`m02_mask_channel_probe.py` 旧口径是「位型 ≥2 **且** 至少一对该分而被分开」，它在 `constraints_capped=true` 的场景上**照样报 `WIRED`**（`D-145` 的实测分歧：同一份 capped 场景，探头 `WIRED`、`stage_mask` `PARTIAL`+`capped=true`+`skipped_count=4298`）。**两根仪器各读一半，读起来都像绿。**

允许**两份独立实现**（独立性要保留），但不许**两套判据**；词表统一用 `WIRED / PARTIAL / EMPTY`，探头的 `0/1/2/3` 保留但在输出里映射到这三个词。**两仪器分歧时只报分歧，那个数不许用。**

### 4.0b 退出码：判词与闸门分开，数字不兼职（`D-20261116-148`，出处：1号 在真 Blender 上量的矩阵）

| 退出码 | 含义 |
|---:|---|
| 0 | `WIRED` |
| 1 | 判词不是 WIRED，**且**调用方给了 `--expect wired` ⇒ 闸门不通过 |
| 2 | 判词不是 WIRED（`PARTIAL`/`UNWIRED`/`EMPTY`），没要求闸门 ⇒ 这是**读数**，不是失败 |
| 3 | `CANNOT`：读不到 / 参数错 / 脚本异常 |

理由：同一个数字曾被三份说法同时占用（`EMPTY→3`、`CANNOT→3`、旧 spec 的 `0/2/1`），而**一个数三个意思**正是本 spec 要治的族。判词本身永远在 `verdict` 字段与 `VERDICT …` 那行里，读的人不必从数字反推。

**退出码不是成败判据**（`D-20261116-148`）：Blender 上两个方向都不可信——脚本抛异常可以是 **0**（1号 最小复现），正常跑完在退出清理阶段崩可以是 **0xC0000005 / -1073741819**（2号 两次探针，`per_frame` 240 帧齐全）。所以**唯一可信的是产物完整性**：帧数齐 + 字段在 + 该有的键都在，退出码**原样记录、不折算**。

### 4.0c 读数分两类，各自自报来源（`D-20261116-151`）

| 类别 | 例子 | 受 `point_cache` 缓存回放影响吗 | 自报字段 |
|---|---|---|---|
| **静态 RNA 读** | `collision_collections` 位型、`mmd_rigid.collision_group_mask`、约束的 `disable_collisions` 布尔 | **不受**（无 `frame_set`、不触发 depsgraph 求值） | `pose_source: "not_applicable_static_read"`（**字段必须写出来，不许省**） |
| **动态姿态读** | 穿透深度、裙摆摆动、位移差 | **受**：`frame_set` 顺序走帧读的是已烘焙的缓存姿态 | `pose_source: "cache_replay"` / `"fresh_solve"` |

⇒ 掩码通道的判词（`WIRED / PARTIAL / EMPTY`）属静态读，**不受缓存回放影响**；凡「干预前后读数相同」的动态结论，若 `pose_source=cache_replay`，**不构成证据**——那可能只是「谁都没动」。

**清缓存后必须再验一次**：`free_bake_all()` 之后 `frame_set` 走一遍，场景设置有可能把缓存**重新烘上**，于是「自由解算臂」静默变回回放臂。跑前与读数前各验一次 `cache_state.is_baked`，任一为真 ⇒ exit 3、不出数。

| # | 判据 | 应当被拒 / 应当区分的输入 |
|---|---|---|
| 1 | 逐刚体回读：`collision_collections` 与源掩码一致 | **全 0 掩码与全 1 掩码必须给出不同的位**（4号 自己提的那种单元级判据） |
| 1b | **场景级**：`reports/subai/M02/scripts/m02_mask_channel_probe.py`（1号 交；**退出码见 §4.0b，判词见 `verdict` 字段**） | 通道落地后必须从 `UNWIRED separated=0` 变成 `WIRED`，且 `separated` 相对 40418 的差能被解释。**判据按 §4.0 四条**，不是「位型 ≥2 且至少分开一对」 |
| 1c | **差额分三桶报**（`D-114`/`D-115` 修正）：`separated_by_bits` / `separated_by_constraint` / `unseparated` | **三桶相加 == 40 418**，否则这个数说不清是「没接上」「表达不了」还是「早就被 ncc 挡住」。另须**分开归因**：`separated_by_constraint` 里哪些来自**通道新增**的约束、哪些是**落地前就存在**的——否则会把 2196 条被放掉的旧约束与新增的混成同一件事 |
| 2 | 源数据未被改动 | 跑前跑后 `mmd_rigid.collision_group`/`collision_group_mask` 逐刚体快照相同；源 `.blend` sha256 前后一致 |
| 3 | 非对称掩码被报出 | 合成场景里放一对非对称掩码，返回值 `asymmetric_pairs > 0` 且 `skipped[]` 非空 |
| 4 | 约束/通道数量可核 | `constraints_added` 与 `collections_set` 都是具体数，不是布尔；`skipped[]` 为空（除非有非对称对） |
| 5 | 幂等 | 同一场景连续调用两次，第二次的 `constraints_added == 0`（或明确说明为何不幂等） |
| 6 | 空场景 | 0 刚体的场景返回 `bodies=0` 而不是异常，且**不许判绿**（`scanned==0` 同族，`D-100`） |

## 5. 这一件**不**承诺的东西（防止被读成「物理对了」）

- 它只把**输入通道**接上；接上之后轨迹**必然改变**——那是预期行为，不是缺陷；
- 接上之后，此前所有物理数字（M02 的 S8 影响量、M04 的穿透深度、S2 的摆幅读数）**全部作废**，必须在新的解算上重取（`D-075`）；
- 它不解决「胶囊体是作者摆的近似体」这个更根本的精度问题；
- 它不改变 M08 的启动前提（交付场景仍须能由当前代码重建，`D-087`）。

## 6. 落地顺序

1. 4号：`tests[]` 未知字段抛 `WRONG_TESTS_FIELD` + 不动点规则进 `evidence_hash_v1.md`（`D-094`/`D-096`）；
2. 4号：本文 §1–§3 的实现 + §4 六条自验；
3. 1号/2号：通道落地后各自接实验（S8 第三层、S2 重测、M04 穿透重取），**数字四样同笔**（`D-074`）；
4. D0：按 §4 逐条验收，六条全过才算通道落地。
