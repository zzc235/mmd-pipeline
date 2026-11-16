# M05 · 交付链「应用动作」这一步（`D-186` 插单）

交付物是一个**函数 + 一条 CLI**，不是一段新流水线：下层实现是 `mmdpipe/stage.py:1009`
的 `stage_motion`（`runner.py:661` 一直在用），这一步只在它外面补三件事——**幂等、窗口、回读**。

- 代码：`mmdpipe/apply_action.py`（新增文件，**只增不改**：`stage_motion` 一行没动）
- 测试：`tests/test_apply_action.py`（24 条，全部离屏，不含 bpy）
- 记录：`reports/subai/M05/arms/*.json`（真 Blender 跑出来的原始记录）+ `arms_summary.json`

## 一、四条验收单的读数（真 Blender 5.2.2 LTS，每臂一个独立进程）

输入场景 = `A1/out/subai/M08/run_20261116_1805/rebuild_built.blend`
（`5 923 244 B` / `ef8e31a9…`，312 刚体、482 骨、骨架 `星穹铁道—飞霄（无外套）_arm`）。
四臂输入**同一个文件**，臂间只差动作源与窗口。

| 臂 | 动作源（sha / 帧 / 骨） | action | fcurves | `scene.frame_end`（回读） | `is_baked` | `is_outdated` | 产物 sha256 |
|---|---|---|---|---|---|---|---|
| `C@W1` | `B_aligned.vmd` `5d391f1a…` 0..300 / 332 骨 | `B_aligned_bone` 1..301 | 725 | **301** | false | true | `251146e9…` |
| `C@W2` | 同上 + `--hold-until 832` | `B_aligned_bone` 1..832 | 725 | **832** | false | true | `c02c982f…` |
| `D` | `kafuka_all/vmd/原神摇_merged.vmd` `b872fda7…` 0..832 / 259 骨 | `原神摇_merged_bone` 1..833 | 700 | **833** | false | true | `be6c0a1c…` |
| `D-对照` | `out/原神摇_merged.vmd` `027179ac…` 0..446 / 52 骨 | `原神摇_merged_bone` 1..447 | 357 | **447** | false | true | `80a952a3…` |

四条同时成立：动作显式应用（fcurves 357–725，`stage_motion` 的门槛是 >100）/
`scene.frame_end` **等于回读的** `action.frame_range[1]`（来源字段写死
`readback:arm.animation_data.action.frame_range[1]`）/ 应用后 `is_baked` 仍为 **false** /
每臂都有 `sha256 + frame_end + 动作来源(路径/树/sha/帧/骨) + is_baked 回读`。

`D-对照` 按裁决**不进 D 的判词**：它是 447 帧原片版，只为把「同名不同物」这件事留证。

`is_outdated` 现在**无条件读**。上一版只在 `is_baked` 时才读，于是 D 臂留了个 `null`，
让人去猜「是没值还是没读」——沉默的缺就是缺（`D-186` 三）。四臂读数均为 `true`
（未烘焙的缓存本来就标脏），与 `is_baked=false` 一起构成「可 fresh_solve」的完整状态。

## 二、`fps` 固定 24：`A6` 是**红**判据，不是 warn

Blender 刚体解算的步长 `dt = 1/fps` ⇒ 改 fps 就是改物理。而 M04 的 A/B 组跑在老场景
（preset 24 fps）、C/D 组跑在这份交付件上——若交付件被改成 30 fps，`C vs B` 就成了
**跨 dt 比较**，与「掩码/动作」一起变成两个变量（`D-104`）。

所以：`import_vmd(update_scene_settings=True)` 会按 VMD 的 30fps 基准把场景 fps 改成 30，
**这一步必须把它按住**——`apply_action` 在调用 `stage_motion` 前把
`preset["motion"]["update_scene_settings"]` 强制改成 `False`，并记
`profile.update_scene_settings_forced_off`；`A6_fps_matches_preset` 拿
`scene.fps_after` 与 `preset.render.fps` 比，不等即**红**。

四臂全部 `fps_before=24 → fps_after=24`，`A6` 绿。

## 三、帧号换算（三行，逐臂都记在 `plan.notes` + `applied.ops`）

`mmd_tools` 的 `ImportVmd` 落在 `scene.frame_current + 1`，所以：

```
源末帧 300 → 应用后 action 1..301 → 最终 scene.frame_end = 301      (C@W1)
源末帧 300 → 应用后 action 1..301 → 定格到 832 → scene.frame_end=832 (C@W2)
源末帧 832 → 应用后 action 1..833 → 最终 scene.frame_end = 833      (D)
```

**不裁源**（按 `D-186`）：D 臂源第 832 帧落在 action 833，在预注册的测量窗口 1..832 之外
⇒ 「**尾帧未测**」进 `known_risks`，不靠裁掉它来对齐。

`C@W2` 的定格起点：预注册写「301..832 保持末帧姿态」，**回读**给出的
`applied.end_before_ops_readback = 301`（最后一个**有键**的帧）⇒ 实际保持区间是 **302..832**
（在 832 插一个与末键同值的键，两键同值 ⇒ 中间恒为末帧姿态，不靠改插值模式）。
两个口径差一帧，来源是「末键帧算不算保持段」，已写进记录不留给下游猜。

## 四、幂等：判在回读内容上，不判在 `.blend` 字节上

`C@W1` 的产物再喂回同一条命令（`C_W1_rerun`）：回读**逐字段相同**
（action 名/725/1..301/frame_end 301/is_baked false/is_outdated true），
`cleared.action=True, orphan_actions=1` —— 这条比「两次一样」重要：
不清就会在同一个骨架上叠两个动作，而报告里看不出来。

`.blend` sha **不同**（`251146e9…` vs `b46810b7…`）——与 `1号` 的读数同结论：
字节不可复现，幂等只能建在内容上。

## 五、反控（能红也能绿，红在哪条写得出来）

**离线五条，各自只红它自己那一条**：

| 反控 | 结果 |
|---|---|
| 声明 `frame_end` 与回读不符 / `frame_end` 不是回读来的 | 只红 `A2_frame_end_readback` |
| 应用后 `is_baked=True` | 只红 `A3_is_baked_false` |
| 导入把容器 fps 改成 30 | 只红 `A6_fps_matches_preset` |
| 缺 `preset_fps`（无法比对） | 只红 `A6_fps_matches_preset` |
| 计划参数自相矛盾（`hold_until` ≤ 应用后末帧、`trim_end` 越界、两者同时给） | `PlanError`，一个字节都不动 |

另加同形状的单点红线：`fcurves` 不足→只红 `A1`、留 NLA 轨道→只红 `A4`、
插件没就绪→只红 `A0`、窗口与计划不符→只红 `A5`、缺字段一律判红不抛异常。

**场景级反控两条（真跑）**：

| 反控 | 读数 |
|---|---|
| `CTRL_no_addon`（`--skip-ensure`）：插件闸门关掉 | `import_vmd ... could not be found`（E-14）⇒ BLOCKED / exit 3 / **盘上 0 个产物**；红在 A0/A1/A2/A3/A5/A6 |
| `CTRL_fps_changed`（`--allow-scene-settings`）：允许导入改 fps | `24→30` ⇒ BLOCKED / exit 3 / **盘上 0 个产物**；**只红 A6 一条** |

这两条与上面五条不矛盾：离线那五条验「判据逐条可分」，场景级验「整段没成就整份拒收」。
`CTRL_fps_changed` 还顺带证明 A6 是**唯一**挡住「输入改环境」的那条。

反控顺带撞出一条真缺陷并已修：**判红时不许写交付件**。第一版 CLI 无论判红判绿都
`save_as_mainfile`，等于把「注定不合格的件」留在盘上让人当已有交付。

## 六、已知风险 / 口径

1. **尾帧未测**（D 臂）：源第 832 帧落在 action 833，测量窗口 1..832 之外。
2. **`C@W2` 有 531 帧是定格**，`D vs C` 只在该窗口同段比较；定格段内不存在「动作差异」。
3. **物理不变**：这一步不建物理、不动掩码，312 刚体原样带过来（`is_baked=false`、
   `is_outdated=true`，消费方可从 `scene.frame_start` 顺序解算）。
4. **强内容摘要待并线**：`content_digest_v1` 要求逐刚体 `bodies[]`，那部分在 `1号` 的
   重建回读里；我这边交两层身份——**实例 sha（本文件）+ 回读内容字段**。
5. **本批产物的时段**：本批（fps=24，带锁证据）是 **18:29:43 取锁、干净窗口独占**跑的，
   每个进程入口先 `assert-owner`。上一批（同样 fps=24）跑在 `2号` 的 M04 窗口里（我的违规，
   已报）；两批的比对见 §七——回读字段逐字段相同。
6. **四棵树共享 `mmdpipe/`**：本提交合入 main 后，**其余三席需重新并 main**，
   否则会拿着没有 `apply_action` 的旧库跑出两种行为。

## 七、补证：干净窗口独占重跑 vs 并发窗口那一批（`recheck_vs_7a95651.json`）

同一份输入、同一份代码，只改了「有没有别人同时在跑」。比 5 臂 × 7 个回读字段 + 产物 sha：

| | 结果 |
|---|---|
| 回读字段（`action.name` / `fcurves` / `frame_range` / `frame_end` / `is_baked` / `is_outdated` / `fps_after`） | **5/5 臂逐字段相同** |
| 产物 sha256 | **2/5 相同**（`C@W2` `c02c982f…`、`C_W1_rerun` `b46810b7…`），**3/5 不同** |

⇒ 「并发没有污染读数」从判断变成证据。同时得到一个更准的结论：**`.blend` 字节的复现性不稳定**——
同一输入两次跑，有时逐字节相同、有时不同，所以「字节变了 = 有人改过」永远不成立，
幂等只能判在回读内容上（§四）。这条比原来那句「字节不可复现」更准：不是「一定不同」，是「不稳」。

`C_W1` 两批记录除 `profile`（新加的锁字段）与 `out_blend` 外，**差异 0 条**——逐字段脚本核过。

## 八、落盘版本化（`D-189`）与一次被覆盖的补救

**已发生的覆盖（不变更历史，只记账）**：`2号` 的三臂读数钉的是
`C_W1 = 251146e9…`、`D = be6c0a1c…`；我在补证时把同一路径重写成了
`C_W1 = 8a8d7daa…`、`D = 5eb83a80…`，**那两个旧 sha 在盘上已不存在**。
内容等价由「5 臂 × 7 个回读字段逐字段相同」证明（§七），**不用重跑**。

| 臂 | `2号` 读数钉的 sha（已被覆盖） | 盘上现件 sha |
|---|---|---|
| `C@W1` | `251146e9…` | `8a8d7daa…` |
| `C@W2` | `c02c982f…` | `c02c982f…`（未变） |
| `D` | `be6c0a1c…` | `5eb83a80ad75…` |

**下一批起的规矩（已实现，见代码）**：

1. `--out-dir <根> --batch-id <批次>` ⇒ 产物写到 `<根>/<batch_id>/<arm_role>.blend`，
   记录里同时记 `out_blend.path` 与 `out_blend.batch_id`（**不可变路径**）；
2. **默认拒绝覆盖**：目标已存在且没给 `--allow-overwrite` ⇒ `REFUSED`、exit 3、一个字节都不写
   （臂件是「那次读数的物证」，不是中间产物）；
3. `--freeze` 把写出的臂件设成只读（`0o444`），记录 `out_blend.frozen_mode`；
   收尾判定作废时会先解冻再删除，不留下「作废但仍可写」的文件。

这三条当时只有纯 Python 部分被离屏测过（路径拼装 / 不覆盖 / 冻结后再写入抛 `PermissionError`）。
**2026-11-16 18:51–18:52 的 324 批次是第一次在真 Blender 里端到端走通**，读数见 §十一。

**下一批是一条命令**：`reports/subai/M05/scripts/run_arms.py` 把七臂（四臂 + 对照 + 两条反控）
的臂表、版本化路径、`--freeze`、以及「不是自己持锁就一个进程都不许起」全写死在里面；
`--dry-run` 只打印将执行的命令与目标路径（不起 Blender、不要锁）。
脚本**不 acquire、不 release**：锁的取得与放回保持显式，留给人。
反控臂的期望退出码在臂表里写死（`CTRL_*` = 3），跑完若不符会逐个点名而不是笼统判失败。

**强内容摘要**（逐刚体 7 字段 `content_digest_v1`）**没做，臂记录里连这个字段都还没有**：
`bodies[]` 要 `1号` 的重建回读给出（`D-186` 明令不造第二份读刚体的实现），我这边只把它的输出
喂进 `m02_content_digest.py`。这一条是「已知未做」，不是「留了 null」——`324` 批次的臂记录
（`summary.json` 的 `arms[]`）里没有 `content_digest` 键，谁核这一项都会拿不到。

## 九、锁的三步闸（`D-188`）

| 位置 | 做什么 | 失败时 |
|---|---|---|
| 进程第一句（`import bpy` 之前） | `assert_lock_owner(--owner)`，记 `profile.lock_start`（ident + `heartbeat_age` 两个值） | `NOT_OWNER` → exit 3，**连 bpy 都不进** |
| 落盘**之前** | `touch` 刷心跳 + 再 assert 一次，记 `profile.lock_before_save` | **不落盘**，退出 3 |
| 收尾 | 再 assert 一次，记 `profile.lock_end`，与开局比对 `lock_tail_verdict()` | 两处 ident 不同 ⇒ 删掉已落盘的产物、`verdict=NOT_APPLICABLE`、风险入册 |

`lock_tail_verdict()` 是纯函数（离屏 3 条测试：同 ident 放行 / 易主作废 / 缺 ident 作废）。
本批 5 臂全部 `lock_tail.ok=true`，开局心跳 8.08 s、收尾 0.51 s。

**函数侧不校验锁**：`apply_action()` 的 docstring 明写「本函数不校验锁，调用方须先 assert-owner」。
理由：库函数强制锁会逼离屏测试与扩展场景各编一个假身份，闸门一旦能被假身份通过就稀释了。

## 十、给下游的两个接口

- `2号`（穿透测量）：每臂四样 = 产物 `path/sha256`、`scene.frame_end`（回读）、
  `action.frame_range`、`is_baked`；见 `arms_summary.json` 的 `arms[]`。**用 fps=24 这一批。**
- `1号`（交付构建链）：`apply_action(preset, root, arm, vmd_path, hold_until=...)`
  一行调用 + 回读记录；CLI 形式
  `blender -b <blend> -P mmdpipe/apply_action.py -- --vmd A.vmd --preset P.json --out-blend B.blend --json R.json`
  （判红时 exit 3 且不写 B）。

## 十一、324 批次：版本化 + 冻结的真 Blender 端到端（`D-189` 结账）

输入 = `1号` 的 `run_20261116_1847/rebuild_built.blend`（`ffaa6780a2f7e765…`，6 102 478 B；
与 `frozen/delivery_324_ffaa6780.blend` 同一条 sha ⇒ 输入身份有独立锚点）。
臂表一条命令跑完七臂，**五份产物全部版本化落盘、全部 `0o444`、无一份被覆盖**：

| 臂 | 产物 | 字节 | sha256 | fcurves（走哪条路） | 动作区间 | `frame_end` | fps | `is_baked` |
|---|---|---|---|---|---|---|---|---|
| `C@W1` | `C@W1.blend` | 6 137 030 | `79862401ed1f…` | 725（`channelbags`） | [1, 301] | 301 | 24→24 | `false` |
| `C@W1` 重跑 | `C@W1-rerun.blend` | 6 136 986 | `2a2efb3e1073…` | 725 | [1, 301] | 301 | 24→24 | `false` |
| `C@W2` | `C@W2.blend` | 6 139 523 | `c3c5cdcb762b…` | 725 | [1, 832] | 832 | 24→24 | `false` |
| `D` | `D.blend` | 10 230 897 | `b6e0545a7bec…` | 700 | [1, 833] | 833 | 24→24 | `false` |
| `D` 对照（447 源） | `D-_.blend` | 8 769 753 | `3669481c2d7c…` | 357 | [1, 447] | 447 | 24→24 | `false` |

两条反控：`CTRL_fps_changed` 判红**且只红 `A6`**、`rc=3`、**一个字节都没写**；
`CTRL_no_addon` 直接 `BLOCKED`、不落盘。`lock_tail.ok` 五臂全 `true`。

**产物回读（只读，一个 Blender 进程循环 `open_mainfile`，不 save）**——把「臂件还是 324 件」
从结构性推断抬成实测：

| 项 | 五臂读数 |
|---|---|
| `rigid_body is not None` 的对象数（`u324`） | **324 / 324 / 324 / 324 / 324** |
| `scene["mask_wired"]` 四条 | `needed=10111 / added=8298 / already=1813 / capped=False / skipped=0 / readback_mismatch=0`（五臂逐项相同） |
| `is_baked` / `is_outdated` | `false` / `true`（五臂） |
| `point_cache_range` | 跟随场景窗口：`[1,301] / [1,301] / [1,832] / [1,833] / [1,447]` |

⇒ 加动作这一步**没有动刚体和掩码通道**，且五臂都可以 fresh_solve。原始记录：
`arms/20261116_324/summary.json`（`artifact_readback.status = "measured"`）。

**字节复现性（第二次实测）**：同一输入、同一脚本跑两遍，`C@W1` 与 `C@W1-rerun`
`sha256` **不同**（`79862401…` vs `2a2efb3e…`），而六个回读字段
（`frame_end / fcurves / frame_range / fps_after / is_baked / is_outdated`）**逐项相同**。
⇒ 「字节变了 = 有人改过」永远不成立；幂等与身份只能建在回读内容上。

**没能给下游的一份**：烘过的件。`apply_action` 只到「未烘」为止，烘焙是 `4号` 的
`stage_bake()`；本批不涉及，也不拿「另存一次」冒充烘焙。

## 十二、Blender 5.2：`Action.fcurves` 在**读回来的件**上不存在

产物回读时撞上：`C@W1.blend` 里的 `B_aligned_bone` 只有
`layers[].strips[].channelbags[].fcurves`，直接 `.fcurves` 抛 `AttributeError`。
同一份代码在**同一会话里刚导入的动作**上却读得到（`324` 批次七臂全绿就是靠这个）。

后果不是「少一个数」：`mmdpipe/apply_action.py` 的 `_trim_action` / `_hold_action` /
`A1_action_applied` 三处都走 `.fcurves`，所以**「幂等 / 可重复运行」此前只在一个会话内成立**，
拿一件已经存过盘的件再跑一次会直接崩——而「可重复运行」正是 `D-186` 对这一步的硬要求。

修法：新增 `fcurves_of(action)`（先试 `.fcurves`，再退到 `layers/strips/channelbags`，
返回 `(列表, 走哪条路)`），三处调用点全部改走它，记录里多一个 `action.fcurves_via` 字段
说明这个数从哪条路读出来的。离屏 5 条（含「`fcurves` 一碰就抛」「`strip` 没有
`channelbags`」两个形状）+ 一条反控：把 `fcurves_of` 退回旧写法，新测试红 3 条、还原后 41 条全绿
（`out/subai/M05/ctrl_fcurves_shape.py`，控制脚本自带还原）。

**没验的仍然写着**：这条修法只在离屏哑对象上验过形状；**「拿一件存过盘的臂件再跑一次
`apply_action`」这件事仍然没跑过**——它要拿窗口，而 324 批次之后窗口一直在别人手里
（2号 的 C/D 三臂、1号 的烘焙）。下一批第一次真跑时补。
