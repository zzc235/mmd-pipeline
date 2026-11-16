# 烘焙与缓存：五条实测结论（M02 / 2026-11-16 19:02–19:41）

这份文档只写**量过的东西**，每条都带件、命令出口与读数。目的是让下一个人不用重跑一晚。

## 一、烘焙的调用点在动作之后，不在 `stage_build` 里

`runner.py` 是 `627 stage_import → 635 stage_build → 661 stage_motion`。动作在 build **之后**才应用，所以在
`stage_build(bake=…)` 里烘的是**静止姿态**（`D-207`）。本仓现在的形状：

- `mmdpipe/stage.py`：`stage_bake(scene, bake, objects=None, bake_call=None)` 是**独立函数**，
  `bake_gate_reason(record)` 独立判；`stage_build` 的 `bake=` 参数保持可用（4号 的调用面），
  但 M02 的交付链**不再从那里烘**；
- 调用点：`reports/subai/M02/scripts/m02_bake_delivery.py`，`m02_rebuild_scene_v3.py --bake`
  改成**拒跑**（`BAKE_AT_BUILD_REMOVED`，退出码 5）。

`bake_request` 只认 `{frame_start, frame_end, fps}` 三个键（多给一个键 ⇒ `ValueError`），
`frame_end` 必须取 `int(action.frame_range[1])` 的**回读值**：D 臂是 **833**，导入后的场景值是 250，两者不同。

## 二、探针会在「没有动作 / 无区分力」的件上假绿 —— 这一层只能靠闸门

无动作件上刚体受重力仍在动（`reference_moved=true`），所以 4号 的 `probe_informative` 不能只看
「有没有动」，要看**采样帧之间是否互不相同**；而真正便宜的是在调用点拒跑：

| 闸门 | 触发条件 | reason_code |
|---|---|---|
| 无动作 | `action is None` 或 `fcurves < 100` | `BAKE_NO_ACTION` |
| 窗口不齐 | `scene.frame_end ≠ action.frame_range[1]` | `BAKE_FRAME_END_MISMATCH` |
| 帧率不同 | `scene.render.fps ≠ 24`（跨 dt 不可比，`D-192`） | `BAKE_FPS_MISMATCH` |
| 刚体/掩码不符 | 与冻结回读的 `u323/u324`、`disable_collisions=True` 对不上 | `BAKE_RIGIDS_MISMATCH` / `BAKE_MASK_MISMATCH` |
| 判红 | `bake_gate_reason(record)` 非空 | `BAKE_GATE_RED`（**不写 blend**） |

## 三、缓存在 5.2 里**没有落盘入口**（`D-218`）

- `pc.use_disk_cache = True` 在 Blender 5.2.2 上**直接崩**：`EXCEPTION_ACCESS_VIOLATION`，
  两次复现，其中一次是只做三件事的诊断（`reports/subai/M02/scripts/diag_diskcache.py`），崩点就是赋值那一行；
- `PointCache` 的 RNA 字段里**没有 `directory`**（叫 `filepath`），旧 API 写法连赋值都过不去；
- 因此 `.blend` 里只留标志位：重开烘过的件读到 `is_baked=true / is_outdated=true`，
  `out/subai/M08` 全树**没有任何 `blendcache*` 文件**。

⇒ `T3` ②（交付件已烘焙）在今晚的工具下**不成立**；记法是「**进程内成立、持久化不成立**」，M08 保持 `T2`。
交付件 = 可确定性重建的场景 + 烘焙规程 + 冻结 manifest，**不是**一个自带缓存的文件。

## 四、「开件后第一次求值」是陷阱（`D-221`）

同一份冻结件（`5bc1581e…`）、323 刚体、帧 417、`tol=1e-6`：

| 变体 | 首读之前发生了什么 | `over_tol` | `max_delta` |
|---|---|---|---|
| 开件后立刻冷跳，`is_baked=true`（陈旧标志） | 零求值 | 275/323 | `1.856515` |
| 开件后第一次求值（未清标志） | 零求值 | 275/323 | `1.863228` |
| 先求值一次 → `free_bake_all()` → 冷跳 | 有一次求值 | 275/323 | `1.994664` |
| **先 `free_bake_all()` 再做开件后第一次求值**（副本） | 清标志、零求值 | 275/323 | **`1.994782`** |
| 先走过 1..833，再冷跳 | 全程走过 | 0/323 | `0.0` |

读法：**跟标志位无关**（清掉 `is_baked` 后 1.86 m 不变，落在 1.9948），所以不是「陈旧缓存被当真」；
**开件后第一次求值本身不是顺序重算的结果**。只要有过一次完整顺序步进，冷跳就与顺序重算逐位相同。

操作后果：**任何「开件后立刻读某一帧姿态」的读数都带这个偏差**（与烘没烘过无关）。要读姿态，
先从 `frame_start` 顺序步进到目标帧再读。记录：`firsteval_frozen/`（manifest `2e705758…`）。

## 五、`recomputed` 判据：跨会话可重建（`T2` 的立足点）

`reports/subai/M02/scripts/m02_recompute_verify.py` + `m02_recompute_compare.py`。

- 两个**独立 Blender 会话**、同一冻结件、同一段顺序步进：`pass_a_sequential` 在 417 / 833 两帧的
  pose sha **逐帧相同**（`adf78ad2…`），`diff_frames=[]`、`problems=[]`；
- 两份记录**逐字节相同**（`79f453cd…`，1 771 B）；
- 判词 `RECOMPUTE_CONSISTENT`，冻结 `recompute_frozen_v2/`（manifest `4439ac42…`）。

**这条有两个不许合并的边界**：

1. 它证明「场景可在任意新会话里确定性重建到同一姿态」，**不**证明交付件自带可回放缓存；
2. 它的 leg B（同会话里走过全程后的冷跳）读的是**本会话顺序重算刚填进去的缓存**，
   `A == B` 是构造出来的，**不构成对缓存回放的测量**（`D-221`）。拿这个 `0.0` 去翻案 `D-218` 是错的。

## 六、刚体约束的独立计数（`D-212`/`D-218`）

`obj.type == 'RIGID_BODY_CONSTRAINT'` 在 5.2 的对象类型枚举里**不存在** ⇒ 按类型名数**恒为 0**
（一个假装量过的读数）。要数 `obj.rigid_body_constraint is not None`：

```
324 件的场景：total = 12338
  disable_collisions=True  = 10111  = needed = 掩码 added 8298 + already 1813
  disable_collisions=False = 2227   = 2196（掩码把 disable_collisions 翻成 False，不删对象）+ 31（build() 自带的关节）
账：12338 = 4009 + 31 + 8298      （4009 = plan_324.json 的 blocked_before / disabled_pairs_in_scene，旧件读数）
烘前 / 烘后各数一次，必须相等（`constraints_stable`）。
```

## 七、这一晚的产物索引

| 件 | 位置 | sha256（前 16） |
|---|---|---|
| 烘焙输入（3号 动作版） | `A3/out/subai/M05/arms/20261116_324/D.blend` | `b6e0545a7becd3d7` |
| 烘后件（测量件，非交付件） | `run_20261116_1900/frozen/delivery_324_action_baked_5bc1581e.blend` | `5bc1581ec75dea36` |
| 烘焙报告 / 回读 / facts / 摘要 | 同上 `frozen/`，manifest `49d5bfae…` | — |
| 烘后 strict 摘要 | `content_digest_v1 = 55da0ec7…`（324 bodies，`missing=[]`） | — |
| `recomputed` | `recompute_frozen_v2/`，manifest `4439ac42…` | — |
| 首读探针 | `firsteval_frozen/`，manifest `2e705758…` | — |
