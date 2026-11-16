# M04 C/D 发车前体检：**交付场景没有动作** ⇒ 本轮判 `UNMEASURED`（缺料，不是做错）

> 时间：2026-11-16 17:59–18:01。锁我 17:59:39 取、18:00 还，期间只有我一个 Blender 进程（两次短进程）。
> 对象：1号 交的 `E:\code\mmdpipe-ai\A1\out\subai\M08\rebuild_built.blend`（5 929 823 B / `e77851ab…`，**我核过，与 1号 报的同一字节**）。
> 结论一句话：**四样都验过、都成立；但场景里没有任何动作**，C@W1 / C@W2 / D 三个臂在这个文件上跑出来的会是**静止姿态的常值**，不是「换场景 / 换振幅」的效应。所以本轮**不发车**，判 `UNMEASURED`，理由写「交付场景无动作」，不判 `FAIL`。

## 一、1号 交的四样：我逐项复核（不是抄他的数）

| # | 项 | 1号 报 | 我复核的方式 | 结果 |
|---|---|---|---|---|
| 1 | 产物 + sha256 | `rebuild_built.blend` / `e77851ab…` | `Get-FileHash` 直接算文件 | **5 929 823 B / 一致** |
| 2 | `--expect wired` 退出码 | `0`、`WIRED patterns=30 separated=36608` | 未重跑（见 §三，我改在场景上回读） | 采信，**但以 §三 的回读为准** |
| 3 | `stage_mask` 三元组 | `WIRED` / `capped=false` / `skipped=0` | **在要测的那个场景上** `scene["mask_wired"]` 回读（`D-162`） | **WIRED / false / 0**，且 `needed=8499`、`added=6686`、`already=1813`、`readback_mismatch=0`、`guardrail_hit=false` ⇒ 恒等式 `6686+1813=8499` 成立 |
| 4 | `is_baked` 回读 | `false` / `is_outdated=true` | 我自己读 `rigidbody_world.point_cache` | **`is_baked=false`、`is_outdated=true`** |

## 二、挡住的这一条（本轮判 `UNMEASURED` 的唯一原因）

同一支体检脚本在这个文件上读到：

```
actions_all        = []                                  ← 文件里一个动作都没有
armature_action    = {action: null, nla_tracks: [], drivers: 0}
scene              = {frame_start: 1, frame_end: 250, fps: 24}
rigids             = 312（无 `$` 占位体）
roi                = 482 根骨，其中 `下擺_*` 166 根（ROI 解析得出）
cache              = {is_baked: false, is_outdated: true, frame_start: 1, frame_end: 2400}
```

**为什么这是硬挡**：C/D 的三个臂各自要求「场景 + 掩码 + **动作**」三选一变一个（预注册 v4 §二组表）。动作不在场景里，240 帧就是同一个静止姿态——`max_depth_m` 会是一条水平线，而这条水平线**长得和「通道没有影响」一模一样**。这正是今天反复出现的那种形状：**没测成的东西必须长得不像结论**。

**我的体检脚本不是瞎的（正控）**：同一支脚本跑 `B_from_blend1.blend` 立刻读到 `action=和胡桃睡觉_bone`（`frame_range` 1..301）、`actions_all` 两条、`rigids=323`、`is_baked=true`。同一判据「有动作 ⇒ 读得到 / 没动作 ⇒ 空表」，不是恒绿。

## 三、两个尺度事实（写报告时必须带，不许抹平）

1. **312 刚体，不是 324**：本轮 `constraints_needed=8499`，而任务书交付需求是 8298、4号 的 cap 是 10111——三个数说的**不是同一个场景尺度**。1号 已在 `result_m08_rebuild_round1.md` §4 按「两棵不同的树」记了；即使本轮能跑，读数也只能写「312 刚体尺度」。
2. **`B_from_blend1` 是 323 刚体**（我这次顺手读到的），与「324」也不是同一个数。**数不许漫游**：三个数各自绑定它来自哪份文件。

## 四、缺的是什么、谁能补

| 缺项 | 归属 | 补法 |
|---|---|---|
| 交付场景上的**动作**（`B_aligned` 用于 C@W1/C@W2、`原神摇` 用于 D） | 1号（交付构建）/ M05（动作库接线） | 在 `rebuild_built.blend` 上应用动作并落成 `delivery_v1`；应用后 `scene.frame_end` 必须与动作末帧一致（D 组要 832） |
| 324 刚体（11 个 `$name_j` 占位体 + 第 11 行刚体） | M01 | 占位体补齐后重建；届时 `needs` 会从 8499 变成 8298 那套派生值 |

两件都补完之后，C/D 照 `reports/subai/M04/m04_cd_run_plan.md` 的七条前置重跑；**本轮没有产出任何物理数字，也没有截取任何「看起来像结论」的中间量**。

## 五、顺手记的两件事（都不改别人的文件）

1. **`IDPropertyArray` 序列化**：我的体检脚本第一版也在 `scene["mask_wired"]` 上撞了 `TypeError: Object of type IDPropertyArray is not JSON serializable`——和 1号 在 `tests_bpy/m08_accept_probe.py` 上踩的是同一个坑。已加 `_plain()` 递归压平（压不动就记 `repr`，**不许让字段静默消失**）。**注意 Blender 的退出码是 0**：脚本崩了它照样返回 0，所以判断脚本成不成只能看产物（`D-135` 那族）。
2. 体检一次只开一个 Blender 进程，只读不写场景（`open_mainfile` 后只读属性，不存盘）。

## 六、产物

- `out/subai/M04/penetration/health_delivery_v1.json`（对 `rebuild_built.blend`，被挡的那份）
- `out/subai/M04/penetration/health_B_from_blend1.json`（正控，动作读得到）
- 脚本 `reports/subai/M04/scripts/m04_delivery_health.py`
