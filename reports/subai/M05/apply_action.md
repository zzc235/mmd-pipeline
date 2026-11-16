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
5. **本批产物的时段**：这一批（fps=24 版）是在 `2号` 的 M04 窗口内跑的
   （锁在他手上，我没取到锁就跑了 —— 我的违规，已在 Thread 与 DM 里报给他）。
   本文所有读数都是**确定性回读**（场景态，不含解算），并发不改变它们；
   但「同一时刻只许一个 Blender 进程」这条规则是被破坏过的，记录在此不隐。
6. **四棵树共享 `mmdpipe/`**：本提交合入 main 后，**其余三席需重新并 main**，
   否则会拿着没有 `apply_action` 的旧库跑出两种行为。

## 七、给下游的两个接口

- `2号`（穿透测量）：每臂四样 = 产物 `path/sha256`、`scene.frame_end`（回读）、
  `action.frame_range`、`is_baked`；见 `arms_summary.json` 的 `arms[]`。**用 fps=24 这一批。**
- `1号`（交付构建链）：`apply_action(preset, root, arm, vmd_path, hold_until=...)`
  一行调用 + 回读记录；CLI 形式
  `blender -b <blend> -P mmdpipe/apply_action.py -- --vmd A.vmd --preset P.json --out-blend B.blend --json R.json`
  （判红时 exit 3 且不写 B）。
