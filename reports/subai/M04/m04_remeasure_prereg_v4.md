# M04 重取预注册 v4（掩码通道落地前落盘，跑完不许改）—— **最后一次改版**

> **取代 `m04_remeasure_prereg_v3.md`（23196 B，`sha256=e4ee9ed40c6d93172188b7878e04a774076377cd8c16eb7973b5bdc169f37294`）。v1（`8e294178…`）/ v2（`d3db1c8b…`）/ v3 均保留不删、内容不改。**
> **v4 补四件**（全部依据 D0 的裁决 ①②③ 与 1号 的命名）：① WIRED 要三条同时成立（`distinct_pattern_count≥2` **单独不算**）；② **单位进字段名**，等式只用「对」；③ 交集非 0 ⇒ B 组判 `PARTIAL`（**新造判词，故必须跑前落盘**）；④ **不动点恒等式 + 跨仪器对账**。
> **`0.020 m` 阈值 / ROI / 基线帧 / 四组定义 / 窗口矩阵 / A0 三档 / 帧判词一字未动。**
> **这将是最后一次预注册改版**：v4 之后跑起来的任何改动都算事后解释。
> 归属：A2 车道（M03→M04），@模块负责2。依据 D0 在 thread:03241ae8 的 2×2 裁决与 ①②③。

## 修订记录（诚实起见）

- **draft 1（未发布、未被任何地方引用）**：只有四组与判据，缺两样——**帧窗口没钉死**（写死 1..240，而候选动作 832 帧）、**没写进程隔离**。这两条是 D0 给 1号 复核时点出来的（②③），我照抄到自己身上才发现同样的洞。
- **draft 2（未发布、未被任何地方引用）**：补帧窗口矩阵（§二）、进程隔离与逐步求值计划（§八）、两个因变量分开（§七）、以及一条我自己的仪器限制（§四：探针不产出全对清单）。
- **v1（首次发布）**：再加一个 **对照组 A0**（碰撞全部关掉）作为**仪器灵敏度正控**。理由是 D0 给 1号 定的 `D-093`——**凡是「没有变化」的结论，必须配一个人为改造的对照**；这条对我的「通道效应」比对 1号 的「限位效应」更致命，因为通道一旦不生效，我读出来的就是「什么都没变」，而那与「我的探针看不见碰撞状态」完全同形。A0 不进任何判词。
- **v2（本次）**：补四件事，**epsilon / ROI / 基线帧 / 四组定义 / 窗口矩阵一字未动**：
  1. **A0 判据从「明显不同」硬化成三档**（§二）。触发点是 1号 那组 C 的四档判词——同一条判据的两次应用，他把「X 太小说明仪器有问题」写成了可判的数，我这边只剩一个量词。
  2. **`max_depth_m` 的符号定义写死**，并给 `frames_over_epsilon` 一条**合成负控**（§七）。这是 D0 点出的最危险一处：判据式 `max(0, depth−baseline) > epsilon` 与判词 `max_depth_m < −epsilon` 看着反号，其实是同一个式子；符号理解错时输出的正是 `frames_over_epsilon = 0`。
  3. **`D vs C` 禁止比数值差**（§七）：两组增量各自相对自己窗口的首帧，报告物不同源，相减无意义；只比 `frames_over_epsilon` 的 0/非 0 与最坏对。
  4. **B 组三条读数无论用谁的实现都要报**（§三），以及**死序 + 逃逸条款**（§八）。
- **v3（本次）**：只补两件，`0.020 m` / ROI / 基线帧 / 四组定义 / 窗口矩阵 / A0 三档 / 判词**一字未动**：
  1. **B 组的干预清单扩成五项**（§三）：`collections_set` / `collections_patterns` / `constraints_released` / `constraints_added` / `readback_mismatch`。理由是读了实现才知道「通道」还包含「放掉挡错的 ncc 约束」与「补新 ncc」，不只写位；只报位会把这部分差错误归因。同时 `n_diff` 取消（实现可直接作用于已有场景，不存在第二份实现）。
  2. **A 组标签从「全互撞」改成「未按 PMX 掩码接线」**（§二）：旧场景本来就有大量 `disable_collisions=True` 的 ncc 约束在按距离启发式挡碰撞。**这条是我自己写错的，四组定义不变，只改标签** —— 但标签会被抄进报告，跑前必须改。
  3. 另加**数源标注规则**（§三）：每个数标 `[measured:this-run]` 或 `[quoted:谁@位置]`。
- **v4（本次，最后一次改版）**：四件，`0.020 m` / ROI / 基线帧 / 四组定义 / 窗口矩阵 / A0 三档 / 帧判词**一字未动**：
  1. **判据一**：`distinct_pattern_count >= 2` **单独不构成 WIRED**，须同时 `readback_mismatch_rigid_count == 0` 且 `group_bit_exact_match`（每个 PMX 组号的刚体集合 == 该位被置上的刚体集合，**集合相等**）。
  2. **判据二**：**单位进字段名**（`*_rigid_count` 个 / `*_constraint_count` 条 / `*_pair_count` 对 / `distinct_pattern_count` 种）；**凡进「对」的等式只许用 `*_pair_count`**。原来我把这条当「怎么打印」，D0 反驳得对：**把「条」加进「对」的等式，1c 的加总校验根本执行不起来**，那是判据可执行性。
  3. **判据三**：`released_added_pair_intersection_count > 0` ⇒ B 组判 `PARTIAL` 并列前 10 对。**这是新造判词**，所以必须跑前落盘，否则就是「看到交集非零再当场定它算不算问题」。
  4. **判据四（我自己加的）**：`ncc_pair_count_before/_after` 都是可测的（`disabled_pairs()` 在动手前后各调一次），于是有一条**恒等式**：`after == before − released_pair_count + added_pair_count − intersection`。对不上就判 `PARTIAL` 且**先说「不一致」、不先猜哪个数对**。这是 B 组的不动点自检，外加与 1号 只读探头的**跨仪器对账**（两个独立实现对同一场景，看「一条约束对应哪一对刚体」的理解是否一致）。

## 一、为什么需要预注册

通道落地后如果直接「在更好的场景上重取一版」，三件事会同时改变：**场景换了**（`delivery_v1`）、**解算换了**（掩码接通）、**振幅换了**（腿驱动 0.1031 → 舞蹈级）。三样一起变，差值归因不了。所以要分组，**每次比较只有一个变量不同**——**帧窗口也算一个变量**，所以它必须先进表。

## 二、四组 + 帧窗口矩阵（照抄 D0 的裁决，窗口是我补的）

| 组 | 场景 | 解算 | 动作 | 用途 |
|---|---|---|---|---|
| **A** | `B_from_blend1`（旧交付） | **未按 PMX 掩码接线**（既有 ncc 约束按 mmd_tools 距离启发式部分生效） | `B_aligned` | 已接受记录，基准 |

> **v3 措辞修正**：A 组原来写「全互撞（现状）」，**这不准确**。旧场景里本来就有大量 `disable_collisions=True` 的 ncc 约束（4号 在 `stage.py:351-353` 的注释里写「实测 `J_baked.blend` 4009 条里有 2196 条挡的是本该互碰的对」），它们**部分地**在挡碰撞，只不过挡的依据是 mmd_tools 的距离启发式，**不是 PMX 的掩码**。准确说法是「**掩码没进解算**」，不是「所有刚体都互撞」。
> 这条修正**不改四组定义**（场景/掩码状态/动作三项不变），只改我给的标签——但标签会被抄进报告，所以必须在跑前改掉。
> **另注（数源）**：`4009 / 2196` 是 4号 代码注释里的自报数，**我未复核、盘上无对应产物**，且它说的是 `J_baked.blend`，**不是我要跑的 `B_from_blend1.blend`**。所以它只能当「存在这类约束」的定性旁证，**不许当 B 组的定量预期**；B 组的真实条数由我自己那次 `apply_collision_masks` 的 `constraints_released` 给出。
| **B** | `B_from_blend1`（旧交付） | **掩码接通** | `B_aligned` | 隔离「通道效应」 |
| **C** | `delivery_v1` | 掩码接通 | `B_aligned` | 隔离「换场景效应」 |
| **D** | `delivery_v1` | 掩码接通 | `原神摇` | 隔离「振幅效应」 |
| **A0**（对照，**不进 2×2**） | `B_from_blend1` 副本 | **碰撞全部关掉** | `B_aligned` | **仪器灵敏度正控**：证明探针看得见碰撞状态 |

**为什么必须有 A0**：如果 `B vs A` 给出「没变化」，有两种解释分不开——① 通道真的没改变解算；② 我的探针根本看不见碰撞状态。A0 把碰撞整体关掉，用它证明这台仪器在这个场景上**看得见**碰撞状态。

### A0 的判据：三档，不写「明显不同」（v2 唯一新增）

「明显不同」是个量词，跑完以后怎么解释都行。所以按 **`max |Δ(max_depth_m)|`（A0 对 A，逐帧取差再取最大）** 分三档：

| A0 vs A | 判词 |
|---|---|
| **逐帧逐位相同**（`max_depth_m` 与 `overlapping_pairs` 全等） | **仪器看不见碰撞状态** ⇒ 四组全部作废，判 `UNMEASURED` |
| 有差别，但 `max |Δ| < 1 mm` | **仪器分辨率不足** ⇒ 只许出「结论级变化」判词；**不许**出「结论不变 / 通道无影响」 |
| `max |Δ| ≥ 1 mm` | 仪器有效 ⇒ 两种判词都可用 |

`1 mm` 不是这次挑的：它既是此前预注册的验收判据（1号 S2 用的同一个数），也是 20 mm 判据的 1/20。

**方向也要报**：关掉碰撞后刚体应互相穿透 ⇒ `overlapping_pairs` 与 `raw_depth_m` 应**变大**。方向反了本身就是一条异常，要单列，不许并进「仪器有效」。

A0 的 `mask_state` 记 `collisions_disabled_control`，只跑 W1（1..240），**不进任何判词**。

**每一次比较都写明窗口**：

| 比较 | 唯一变量 | 窗口 | 窗口理由 |
|---|---|---|---|
| **B vs A** | 解算（掩码） | **W1 = 1..240** | A 的记录就是这一窗口；两者必须同窗才可比 |
| **C vs B** | 场景（旧交付 → `delivery_v1`） | **W1 = 1..240** | 同上，先隔离场景 |
| **D vs C** | 动作（振幅 ×20） | **W2 = 1..832** | `原神摇` 全长 832 帧；**在 240 帧窗口里它会截掉峰值，那会造出「未穿透」的假阴性** |

⇒ 因此 **C 要跑两次（W1、W2）**，代价是一次多花几分钟，换来三次比较各自只有一个变量不同。
`B_aligned` 只有 300 帧：`C@W2` 在 301..832 帧是**保持末帧姿态**，这一点写进报告，不藏。它不影响 `D vs C`——两组同窗、只差动作。

**窗口是回读的，不是声明的**：D 组场景必须 `frame_start=1`、`frame_end=832`，且跑前回读 `scene.frame_end` 与动作 `frame_range` 的末帧；**两者不一致即作废本次运行**（不许「大约覆盖」）。

**场景副本**：D 组用 `delivery_v1.blend` 的副本 `out/subai/M04/m04_d_dance.blend`，`delivery_v1.blend` 本身**一个字节都不动**（它是 M08 的验收对象，改了就是第二例「同一路径两个内容」）。

## 三、B 组的混淆可能性，先声明

组 B 要求把掩码**作用到已存在的旧场景**上，而组 C/D 的掩码由 4号 的 `stage.py` 在**建场景时**接上。

**v4 定稿：那个混淆不存在了。** 我读了 `A4@6bcb60a`：`stage.py:279 apply_collision_masks(scene=None, *, collection_index_of=None)` 里 `scene` 只决定 `bodies` 从哪儿取，主体全走 `bpy.data.objects` ⇒ **它本就能作用于已打开的旧场景**。我直接调它，**不另写 applier**，因此「两套 applier 是否等价」这个问题不存在，B 组是干净的单变量隔离。备用字段 `n_diff` 保留但默认 `null`（万一日后被迫另写才填）。


**B 组的干预清单：八项，分三组**（字段名自带单位，见判据二；`collection_patterns` 与 1号 同名同形，便于跨仪器对账）。

| 组 | 字段 | 期望 / 含义 |
|---|---|---|
| 位 | `bits_set_rigid_count` | **324 个**（写了位的刚体数） |
| 位 | `distinct_pattern_count` | ≥2 种，**但单独不构成 WIRED**（见判据一） |
| 位 | `collection_patterns` | `[{"bits":[…],"count":N}, …]`；**必须与 PMX 的 9 个组号逐组对上** |
| 位 | `readback_mismatch_rigid_count` | **0 个** |
| 约束 | `released_constraint_count`（条）+ `released_pair_count`（对） | 放掉的既有 `disable_collisions`；条与对**分列** |
| 约束 | `added_constraint_count`（条）+ `added_pair_count`（对） | 新补的 ncc；条与对**分列** |
| 约束 | `released_added_pair_intersection_count` | **期望 0 对**（见判据三） |
| 对象集合 | `rigid_object_sets_same` / `only_by_rigid_body_count` / `only_by_mmd_type_count` + 两侧差集前 10 名 | **不预设一致**（见本节末前置检查） |

今天已有的教训：用 `hasattr(o, "mmd_rigid")` 数出 4853 个对象，而真值是 324——**读错对象集合与「读对了但真的是 0」长得一样**，所以这三条必须报数，不能写「已确认只改刚体」。

### 判据一：WIRED 要三条同时成立（D0 的 ③，v4 新增）

`distinct_pattern_count >= 2` **单独不构成 WIRED**。三条全过才算通道接通：

1. `distinct_pattern_count >= 2`；
2. `readback_mismatch_rigid_count == 0`；
3. **`group_bit_exact_match`**：对 PMX 里出现的**每一个**组号 g（本场景实测 9 个）都满足
   `{刚体 | PMX 组号 == g} == {刚体 | 位型里含 bit(g)}`（**集合相等，不只是个数相等**）；逐组报 `g / pmx_count / bit_count / set_equal`。

任一条不成立 ⇒ B 组的掩码状态判 `PARTIAL`（或 `EMPTY`），**不许**写「通道已接通」。
理由：`patterns=1` 是「没分区」，但 `patterns=3` 也可能是**三种都错**——只有「每个组号的刚体集合 == 该位被置上的刚体集合」时，位才算按 PMX 语义落位。

### 判据二：单位进字段名，等式只用「对」（D0 的 ① + 1号 的命名，v4 新增）

验收行 1c 的等式左边单位是**刚体对**：

```
separated_by_bits + separated_by_constraint + unseparated == 40418    ← 单位：对
```

所以字段名自带单位，读报告的人不需要记得：

| 旧名（v3） | v4 名 | 单位 |
|---|---|---|
| `collections_set` | `bits_set_rigid_count` | **个刚体** |
| `collections_patterns` | `distinct_pattern_count` | **种** |
| `pattern_histogram` | **`collection_patterns`**（与 1号 同名同形：`[{"bits":[…],"count":N}, …]`） | 种 + 个 |
| `readback_mismatch` | `readback_mismatch_rigid_count` | **个刚体** |
| `constraints_released` | `released_constraint_count` | **条** |
| （新） | `released_pair_count` | **对** |
| `constraints_added` | `added_constraint_count` | **条** |
| （新） | `added_pair_count` | **对** |
| （新） | `released_added_pair_intersection_count` | **对** |

**凡进「对」的等式，只许用 `*_pair_count`；`*_constraint_count`（条）只作诊断。** 把「条」加进「对」的等式，两边单位不同 ⇒ **那个加总校验根本没法执行**，而它看起来还是「算过了」。

### 判据三：交集非 0 ⇒ B 组判 `PARTIAL`（D0 的 ②，v4 新造判词）

同一个 mask 推出的 `release_pairs` 与 `constraints_needed` 应当**互斥**。若 `released_added_pair_intersection_count` **非 0**：

- **B 组的掩码状态判 `PARTIAL`**，列出前 10 对（含两侧 PMX 组号与掩码）；
- **不许**把 `released_*` 与 `added_*` 相减或相加成一个「约束变动数」——方向相反，合并后归因不了；
- 该交集**不改变** A0 三档，也**不改变**穿透判词（epsilon 与帧判词不变），它只影响「B 组这次算不算接通」。

### 判据四：不动点恒等式 + 跨仪器对账（v4 新增，比「交集非零」更强）

`apply_collision_masks` 在动手**之前**就先算了 `already = mask_mod.disabled_pairs(bpy.data.objects)`。所以三组数都是**可测的**，不必靠推理：

```
before  = ncc_pair_count_before      ← 动手前 disabled_pairs() 的去重对数
after   = ncc_pair_count_after       ← 动手后同一次调用
```

**恒等式（期望严格相等；交集为 0 时化简成第二式）**：

```
after == before − released_pair_count + added_pair_count − released_added_pair_intersection_count
```

任一侧对不上 ⇒ **B 组判 `PARTIAL`**，并**先说「不一致」**，不许先猜哪一个数对。这是 B 组的「不动点自检」：它不检查数字好不好看，只检查**同一件事被数了两遍之后是否自洽**。

**跨仪器对账**（1号 的只读探头 ↔ 我的 applier，两个独立实现对同一场景各跑一次）：

| 项 | 来源 | 单位 |
|---|---|---|
| `ncc_pair_count`（落地后） | 1号 探头 | 对 |
| `ncc_pair_count_before` / `_after` | 我 B 组 | 对 |
| `released_pair_count` / `added_pair_count` | 我 B 组 | 对 |
| `released_constraint_count` / `added_constraint_count` | 我 B 组 | 条 |
| **对账结论**：一致 / 不一致（不一致时只报「不一致」，不指派谁的错） | 对账 | — |

理由（D0 的）：两个仪器对「一条约束对应哪一对刚体」的理解可能不同——**那比交集非零更值得知道**。

### 前置检查：两个「刚体集合」是不是同一个

跑之前先报 `rigid_body is not None`（我历史脚本的取法，实测 **324**）与 `mmd_type == "RIGID_BODY"`（该函数 `bodies` 的取法）**两个集合的差**：`rigid_object_sets_same`（布尔）、`only_by_rigid_body_count`、`only_by_mmd_type_count`（个）、两侧差集前 10 个名字。**不预设一致**——`324` 要进报告，先要说清它指哪批对象。


### 数源标注规则（v3 新增，防止转述被当成实测）

报告里每一个数都要带一处标注，二选一：

- **`[measured:this-run]`** —— 我这次跑出来的；
- **`[quoted:<谁>@<位置>]`** —— 引自别人的代码/注释/消息，**我自己没复核**。

起因：`4009 / 2196` 这两个数是 4号 代码注释里的自报数，我引它时说清了出处，但它一旦被转进别人的记录就会被读成「实测」。**转述的数是会掉标签的，所以标签必须写在数的旁边。**

## 四、仪器冻结（不改已接受记录引用的任何脚本）

`m04_capsule_probe.py`、`m04_mesh_probe_v2.py` **一个字都不改**。已接受记录 `evidence/1:8e7de708…`（commit `f3fd0e1`）的 artifacts 引用了它们当时的 sha256；改了等于让那条记录的哈希对不上磁盘。

新增脚本（各自单独入 artifacts）：

| 脚本 | 作用 |
|---|---|
| `m04_apply_mask_channel.py` | 组 B：掩码作用到旧场景副本（首选包 4号 的实现） |
| `m04_baseline_provenance.py` | 纯 Python：给探针写出的基线补溯源字段（§五），不重算数值 |
| `m04_group_compare.py` | 纯 Python：四组比对（§七），不重算任何深度 |

### 精度：定在 6 位小数，不改

探针写基线时 `round(v, 6)` = 1 µm。判据 20 mm ⇒ 1 µm 是判据的 5×10⁻⁵；四组差值在 mm 级。**改到 9 位对结论无一字影响，而改它要动被哈希过的仪器**。所以保留 6 位，并写死这条界：「基线存 6 位，重取与当场算差 ≤1 µm，远小于 20 mm 判据」。溯源脚本**不恢复精度**（6 位已在写盘时损失），它只补字段。

### 仪器限制：探针不产出「全对清单」（我自己先说出来）

`meta.per_frame` 每帧只有一个 `max_depth_m`、一个最坏对（`bone`/`bone_other`）与四个计数（`overlapping_pairs` / `adjacent_pairs` / `other_pairs` / `pairs_without_baseline`），**没有逐对深度表**。后果两条，都进 `known_limits`：

1. 判词只能在**帧最大值**层面给，不能给「多少对翻转过判」；
2. 若两组的最坏对换了一根骨，帧最大值看不出这件事——报告里要打印各自的 `bone`/`bone_other`，让人能看出换没换。

## 五、基线文件：三项溯源 + 命名

新 schema `penetration_baseline/2`，在 v1 的 `scene`（只有文件名）之外**必带三项**：

| 字段 | 内容 |
|---|---|
| `scene_sha256` | .blend 的 sha256（旧交付 `dd7f6877…`；`delivery_v1` 届时另取） |
| `vmd_sha256` | 驱动动作的 sha256 |
| `mask_state` | `disabled_all_collide`（现状）/ `pmx_mask_wired`（接通） |

命名 `<scene>_<vmd_sha8>_<mask_state>_roi18_capsule_v<n>.json`。**三项里任何一项不同 ⇒ 必须是不同文件。**
旧的 `B_from_blend1_roi18_capsule_v1.json` 保留不动（缺三项，只能当历史材料，不再当可比基线）。

## 六、判据：固定，不随档位调

| 项 | 值 | 来源 |
|---|---|---|
| 胶囊 epsilon | **0.020 m** | `thresholds.md`，profile `pg/0.1-exploratory` |
| 判定式 | `max(0, depth − baseline) > epsilon` | D-056 |
| ROI | 18 根 `下擺_0_*`（`roi18_capsule`） | 既有 |
| 基线帧 | **1**（窗口首帧） | 既有基线 `baseline_frame: 1` |
| 逐帧采样 | `plan_sequential_eval`，从 `scene.frame_start` 连续步进 | 既有（P12） |
| 网格 epsilon | −0.020 m（负值=穿入） | `thresholds.md` |
| 缺基线 | **UNKNOWN**，不当 PASS | 既有 |
| 组跑不出来 | **UNMEASURED**，不当 PASS | 本文件 |

**判据不随档位改。** 若大摆幅下 20 mm 不成立，那是**结论**（写「判据在舞蹈级驱动下不成立」），不是放宽容差的理由。

## 七、组间比较怎么判「变没变」——两个因变量分开写

探针给我们两个量，**用途不同，不许互换**：

| 量 | 定义（写死，不许再解释） | 用途 |
|---|---|---|
| `max_depth_m` | **带符号的超出基线增量**：`max_depth_m = −max(0, depth − baseline)`。**负值 = 新增重叠**，越负越深；`0` = 不比基线深 | **只用于判词**：`max_depth_m < −epsilon` 即越判据 |
| `raw_depth_m` | 原始重叠量（含基线本身），同样负值 = 重叠 | **只作量级描述**（比如「绝对口径那批 −0.0946 m 是否消失」），**不参与判词** |

> **符号陷阱（D0 指出的，已改成钉死的写法）**：判据式 `max(0, depth − baseline) > epsilon` 与判词 `max_depth_m < −epsilon` **看起来反号，其实是同一个式子**——因为 `max_depth_m` 就是那个增量的负数（探针 `sign_note` 里写着「负值=新增重叠」）。把 `max_depth_m` 当成「正 = 更深」去判，得到的正是 `frames_over_epsilon = 0`，**今天最让人放心的那个数**。所以下面这条负控是必须过的门，不是建议。

每组报：`deepest.frame`、`deepest.max_depth_m`、`deepest.bone`/`bone_other`、以及 **`frames_over_epsilon` = `per_frame` 里满足 `max_depth_m < −0.020` 的帧数**。判词只有两种，不新造 mm 阈值：

| 情形 | 判词 |
|---|---|
| `frames_over_epsilon` 在两组间 **0 → ≥1 或 ≥1 → 0** | **结论级变化**：列出那些帧、两侧数值、最坏对 |
| 两组都是 0，或都是 ≥1 | **数值变化、结论不变**：必须打印两组 `deepest.max_depth_m` 与 `max |Δ|` |

### `frames_over_epsilon` 的合成负控（不过门就不许引用）

计数规则必须先在**人造数据**上验一遍，再碰真数据。`m04_group_compare.py --selftest` 三条：

| 控制 | 构造 | 期望 |
|---|---|---|
| 正控（该数出来） | 两帧：`max_depth_m = −0.031`（深于 20 mm）、`−0.001`（浅） | `frames_over_epsilon = 1` |
| **负控·符号写反** | 同一份数据按「正 = 更深」数（`> +0.020`） | 得 `0`，脚本必须把这条**打印成「错误约定：若采用则结论反号」** |
| 负控·边界 | `max_depth_m = −0.020`（恰好等于判据） | **不算越**（严格小于才计），计 `0` |

**三条里任一不符 ⇒ 四组的 `frames_over_epsilon` 一律不许引用。** 这就是「验证器自己先要被验证」。

**跑前已经验过（不是写着好看）**：`m04_group_compare.py --selftest` 10 条控制全过（exit 0），并做**变异测试**——

| 变异 | 结果 |
|---|---|
| 把计数符号写反（按「正=更深」数） | selftest **exit 4**，3 条 FAIL |
| 把边界从 `<` 写成 `<=` | selftest **exit 4**，1 条 FAIL（边界那条） |
| 复原 | exit 0 |

即：**实现写错跑不过自检**，所以自检不是摆设。脚本本身入提交时带 sha（预注册只钉规则，不钉脚本字节——脚本还会加功能，钉死它等于每次改都要改判据）。

### C 与 D 的增量不同源，禁止相减

每组按 §五 有自己的基线（各取窗口首帧）：`C` 的增量相对 `B_aligned` 首帧，`D` 的相对 `原神摇` 首帧。**两个增量不是同一参照物，相减没有意义。**

所以 `D vs C` **只比** `frames_over_epsilon` 的 0/非 0、最坏对（`bone`/`bone_other`）与 `deepest.frame`，**不比 `max_depth_m` 的数值差**。要比数值差只能在同一个动作内部比（那是组内比较，不是组间）。

**正控（「结论不变」必须先自证）**：每条比较都要打印两侧的 `pairs_without_baseline`（必须 **0**，否则该组判 UNKNOWN）与 `overlapping_pairs` 的中位数（必须 **> 0**——为 0 说明这一组根本没算到重叠，那个「没变化」是空集给的）。此外还须满足 **A0 正控成立**（§二 三档）：落在第 1 档 ⇒ 四组作废；落在第 2 档 ⇒ **本条「结论不变」一律不许出**。

**截断正控**：D 组必须报 `deepest.frame`。若它 **> 240**，则 240 帧窗口会漏掉峰值——这条就是「为什么必须跑全长」的实测证据；若 ≤ 240，写成「本次未观察到截断效应」，不许写成「裁剪无害」。

## 八、顺序（D0 定为死序，B 组第一）+ 进程隔离

**死序**（D0 定，我照排）：

```
1. 4号 通道合进 main
2. 【我】B 组：副本上应用 applier → --expect wired 退出码 0 → 跑 B → 与 A 记录比
3. 【1号】重建 delivery_v1 → 自己跑 --expect wired → 交场景与掩码读数
4. 【1号】S8 第三层 + S2 A/B/C（都在 delivery_v1 上）
5. 【我】C@W1 / C@W2 / D（都在 delivery_v1 上）
```

**第 2 步必须先于第 3 步**，理由不是「文件会被覆盖」（1号 已核：`m02_rebuild_scene_v3.py` 只吃 preset + PMX，从不打开旧交付文件，所以旧文件不会消失），而是**「旧交付 + 只改解算」这个组合一旦有了新场景就再没人做**——对照组会被遗忘，而不是被破坏。

**A0 紧跟 B**（同一个副本环境、同一次开工），它是 B 的读数许可：B 出来之前 A0 必须已经过三档判定（§二）。

### B 组的逃逸条款（正式化，D0 要求）

如果到那一步 B 组做不成（映射无法单独取出，或应用后探针仍报 `UNWIRED`），我**必须在消息里明说「B 组作废」并给原因**，然后：

- D0 记成 **`通道效应未隔离`** 这个 `known_limitation`——**不是静默跳过**；
- 后续凡「穿透数字变了」的结论都要带这句限定；
- 1号 立刻往下走，不等我。

「做不了」与「不做了」要分清：前者进 `known_limitations`，后者要给原因才能记账。

### 进程隔离

1. **每次跑各自一个 Blender 进程**（A0 / B / C@W1 / C@W2 / D 共 **5 次新跑**，A 用既有记录）。同进程串味今天在 `bake_all` 上已经吃过一次（`is_outdated` 在同进程里为 false、重开文件又变 true）。
2. 每次必记：**PID**、`cache_state`（`is_baked` / `is_outdated`）、`eval_plan.policy`（必须 `sequential_from_frame_start`）、`visited_frames`、`warmup_frames`。`plan_sequential_eval` 抛 `SequentialEvalError` ⇒ **本次作废**（不许改成冷跳凑出来）。
3. **每组跑之前**先跑 1号 的 `m02_mask_channel_probe.py --expect wired`，把那次**退出码原样**写进本组报告：`0=WIRED` 才继续；`1=FAIL`、`2=还没落地` ⇒ 本组不得出结论。
4. 锁：`python -m coordination.lock` 取还；源文件 sha 前后一致；只读源 + 只在副本上写。

## 九、不做什么

- 不改 epsilon / ROI / 基线帧 / 仪器；
- 看到数字之后补判据；
- 把「通道没接通」的组报成「穿透变好了」；
- 把 `UNMEASURED` / `UNKNOWN` 写成 PASS（今天已四次栽在这个形状上）；
- 用 `raw_depth_m` 参与判词，或用增量去描述绝对量级。

## 十、每组要交的东西

三样同笔：**基线文件（带三项溯源）** + **该组穿透读数（§七那五项）** + **该组 `--expect wired` 退出码**。
网格口径四项（可计分样本数 / 不可计分比例 / 合成三项读数 / `target_has_skirt_polys`）不得拆开单独引用。
