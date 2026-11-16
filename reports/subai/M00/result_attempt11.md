# M00 · attempt 11 · 通道建约束路径「复制既有 ncc」+ M08 验收一键判据

> HEAD **`31d6a1a`**（`8aba272` + `8ec02b9` + `31d6a1a`），`ai/a4`，未 push。
> 纯 Python **470 tests OK（skipped=15）× 三环境**（默认 / `PYTHONIOENCODING=utf-8` / `gbk`）。
> Blender 侧：**三条真跑**（行为正控/反控 + 同场景两条路计时），数字见下，全部来自本节记录的原样输出。

## 一、先说最要紧的三个数

| 项 | 值 | 出处 |
|---|---:|---|
| 同场景（145 刚体、1549 条约束）建约束耗时 | **0.172 s** | `mask_small_145_copy_attempt11.txt` |
| 同场景走旧路（逐条 `bpy.ops`） | **184.269 s** | `mask_small_145_ops_attempt11.txt` |
| 倍数 | **≈1071×**（每条 0.11 ms vs 119 ms） | 同两次读数 |

两条路的**后态逐项相同**（这是"等价"的判据，不是"没报错"）：

| 项 | template_copy | ops |
|---|---:|---:|
| `constraints_needed` / `already_blocked` / `to_add` | 1549 / 0 / 1549 | 同 |
| `constraints_added` | 1549 | 1549 |
| `constraints_identity` | true | true |
| `readback_mismatch` | 0 | 0 |
| `skipped_count` | 0 | 0 |
| `nocollide_pairs_still_colliding` | 0 | 0 |
| `blocked_wrong_after` | 0 | 0 |
| `verdict` / `verdict_reasons` | `WIRED` / `[]` | `WIRED` / `[]` |
| `source_unchanged` / `bits_are_mask_or_own` | true / true | true / true |
| 幂等（第二次 `added=0`） | true | true |

外推（**算术，不是实测**）：交付场景要补 8298 条 ⇒ 旧路 8298 × 119 ms ≈ **16.4 分钟**；
2号 在带环的大场景上测到 0.39–0.48 s/条 ⇒ 54–66 分钟。新路 ≈ 8298 × 0.11 ms ≈ **0.9 秒** + 场景开销。

## 二、行为正控/反控（`mask_behaviour_attempt11.txt`）

场景：地面 `G`（被动，组 1，掩码只允许组 1 ⇒ 位 `{1}`）+ `P`（组 0，掩码允许 `{0,1}` ⇒ 位 `{0,1}`，
PMX 语义**不该碰**，位却重叠 = 假碰）+ `Q`（组 1，掩码允许 `{0,1}`，PMX 语义**该碰**）。
判据不是"标志位读回来是 True"，是**让 Bullet 解算 60 帧看行为**：

| 路 | `P` 末高 | `Q` 末高 | 地面 | 结论 |
|---|---:|---:|---:|---|
| `template_copy` | **-26.6905**（穿过） | **1.3**（停住） | 1.0 | 约束真的分开了 P/G，且没把位一起关掉 |
| `ops` | **-26.6905** | **1.3** | 1.0 | 与复制路**逐位相同** |

`both_paths_effective=true`、`paths_agree=true`、`all_fresh_solve=true`
（`pose_source=fresh_solve`、`is_baked=false`、`is_outdated=false`——按 2号 15:21 那条，
不报这三项的话，"两组读数相同"分不出"真没差"还是"谁都没动"）。

## 三、改了什么（对着 D0 15:11 的五条）

| D0 要求 | 落法 |
|---|---|
| ① 建约束不触发全场景求值 | `_ncc_template()` + `_new_constraint_object(template=...)` 复制既有 ncc；复制失败记 `copy_errors` 再退回 ops，`constraint_creation` 报实际走的路；`constraint_creation=` 可强制两条路之一，强制复制而无模板 ⇒ **抛异常**（不许"以为走复制其实是 ops"） |
| ② `mask_wired` 补三项 | 补 `constraints_needed / constraints_already_blocked / constraints_to_add / constraints_capped / guardrail_hit / skipped_count / constraint_creation / constraints_identity / verdict_reasons`；清单收敛到一处 `MASK_WIRED_KEYS` |
| ③ `WIRED` 需 `skipped` 为空 | 追加：`skipped` 空 **且** 记账恒等式 `added + already == needed` 成立 |
| ④ 上限由 plan 推出、护栏只作护栏 | `max_constraints=None` ⇒ `limit = len(plan["constraints_needed"])`；超过 `DEFAULT_MAX_CONSTRAINTS`（4000→**20000**）才 `guardrail_hit` + `capped` |
| ⑤ fail-closed | 通道开着而 `verdict != WIRED` ⇒ `stage_build` 在**烘焙之前** BLOCK 返回，原因带 `verdict_reasons` |

两个归零量（`D-142`）入 `mask_report()`：`blocked_and_should_collide` / `nocollide_pairs_still_colliding` /
`unexpressible_pairs`；**没有该类对给 `None`，有但不剩给 `0`**。`stage_mask()` 据此给判词四条，
并把建场事实写进 `scene["mask_wired"]`（存盘后仍看得见；没有记录 ⇒ 不可能是 `WIRED`）。

## 四、M08 验收一键判据（D0 15:10 派）

- `coordination/acceptance.py`：纯 Python 判据 + CLI，退出码 **0 / 3 / 4**（写进 `--help`，脚本自己 `sys.exit`）；
  期望值是**数据**（`DEFAULT_EXPECTATIONS`），换验收对象只换期望文件；
  产物 `reports/subai/M08/accept_<sha8>.{txt,json}`。
- `tests_bpy/m08_accept_probe.py`：Blender 侧**只采事实**；通道判词吃 `stage_mask()`、缓存判词吃
  `cache_state.evaluate()`，**不写第三份实现**；三次 sha 独立读三遍。
- 负控（`tests/test_acceptance.py` 里就是它）：把交付期望打在一份 **J_baked 形状**的事实上，
  必须在**具名行** FAIL——`rigids_u323`(323≠312)、`rigids_u324_equals_u323`、`placeholders`(11≠0)、
  `bones`、`vertices`、`cache_verdict`、`nocollide_pairs_still_colliding`(38605)。
  缺事实 ⇒ `CANNOT`（exit 4），不许当 PASS。

## 五、自报两个我自己造的缺陷（都是同一个形状：失败长得像正常）

1. **`bpy.ops.rigidbody.world_add()` 第二臂 poll 失败**：首跑 `BEHAVIOUR_DONE exit=3`，输出里只有一行
   `RuntimeError: ... poll() failed, context is incorrect`。原因是我在同一进程里跑两臂，第二次调用时刚体世界
   已存在。**修法**：`if scene.rigidbody_world is None` 才 `world_add`；并把每臂 try/except 进 `runs`，
   一臂失败不再让整支无输出。**顺带说明**：那次失败之所以看得见，正是 `D-135` 的守卫
   （`except BaseException → traceback → exit 3`）在起作用——没有它，Blender 会给 0。
2. **`tests_integration/` 被 `.gitignore` 挡着**（`.gitignore:12` 只白名单 `!/tests_bpy/`）：
   采集器第一版放在那儿，`git add` 只得到一句 "paths are ignored"，**文件没进仓**。
   已移到 `tests_bpy/m08_accept_probe.py`（`8ec02b9`），任务书里的目录约定与实际仓库规则不一致，以仓库为准。

## 六、没做到的（不许读成"已验证"）

- **交付尺度（8298 条）没有真跑**：这要重建场景，等 1号。本轮验的是 145 刚体/1549 条的同构小场景 +
  逐条代价外推。**交付件上的 `WIRED` 仍待重建时确认。**
- **`stage_build` 的 fail-closed 分支只有单测覆盖**，没在真建场里触发过（它会 BLOCK，真跑一次很贵）。
- `mask_wired` 的 `constraints_added == constraints_needed` 在**新建场景**上成立（`already=0`）；
  在 `J_baked` 那种"`mmd_tools` 已经挡对 1813 条"的场景上恒等式是 `added + already == needed`，
  两个数不相等是对的——验收时别拿"相等"当判据。
- 探针里的 `apply_seconds` 不含场景搭建；`ops` 那次 184 s 比我 15:10 报的 93 s 更高，以这次为准。

## 七、状态

锁已 `release`（`A4|mask-channel-verify`，两次占用：15:23:46 与 15:27:15）。`ai/a4` 干净在 `31d6a1a`，未 push。
Human 暂停令期间不再取锁、不再接新活。
