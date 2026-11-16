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
（`reports/subai/M05/scripts/ctrl_fcurves_shape.py`，控制脚本自带还原）。

**没验的仍然写着**：这条修法只在离屏哑对象上验过形状；**「拿一件存过盘的臂件再跑一次
`apply_action`」这件事仍然没跑过**——它要拿窗口，而 324 批次之后窗口一直在别人手里
（2号 的 C/D 三臂、1号 的烘焙）。下一批第一次真跑时补。

## 十三、写侧：`chain_nla` 拼 B 的位置曲线（`D-213` 派工）

`4号` 盘库时发现同一个形状还有一处更硬的：`mmdpipe/chain_nla.py:106/108` 是
`_shift_b_action`，它拿 `action.fcurves.find(...)` / `.new(...)` **往 B 的 action 上改/建**曲线。
分层动作上 `.fcurves` 连读都不给，写更没有 —— 一旦有人拿存过盘的件再拼，崩的是**「拼」**，
不是「读」；而「拿存了盘的件再拼一次」正是 `D-210` 记下的那两处未做之一（NLA 三面）。

**可达性（重要，别把这条修法说成「修好了一个正在犯的毛病」）**：今天 `chain_nla` **走不到**那条路。
`concat_via_nla()` 每次进来先 `_fresh_scene()` 清场，再从 PMX + 两支 VMD 重新导入
（`runner.py:468` 也是拿 VMD 段路径调它），所以它手里的动作**永远是本会话刚导入的**，
`.fcurves` 读得到。换句话说：

- **读侧**（`apply_action` 那条：`blender -b <in.blend>` 打开存盘件）—— 真件上真崩过，已修、已验；
- **写侧**（`chain_nla` 这条）—— 今天是**防御性**修复：它保护的是「将来有人写『打开存盘件再拼』
  这个入口」时不炸，而这个入口**目前不存在**（正是 NLA 三面那笔未做的工作）。
  所以「拼接结果对不对」不但没验，**连一条能验它的入口都还没有**。

修法：写侧也走同一个地方，不另留实现（`D-186`：两份实现就是两个真值）。
`apply_action.py` 新增两件：

- `fcurve_container(action, datablock)` —— 返回**可写**容器（有 `.find/.new`）：
  ① `action.fcurves`（同会话刚造的动作，今天在用的那条）
  ② 分层动作里槽位正好是 `datablock.animation_data.action_slot` 的那个 channelbag
  ③ 只有一个 channelbag 时就是它
  ④ 多个又对不上槽位 ⇒ 抛 `FcurveShapeError`。**不挑**：挑一个等于往别人的动作上改键，
  而且写到一半才发现会留下半个拼接结果，比崩更难查。
- `ensure_fcurve(action, datablock, path, index, group)` —— 拿到（必要时新建）一条曲线，返回
  `(fcurve, how)`。顺序：老形状 → 上游接口 → 自己走 channelbag。

**上游接口这件事按 `D-213` 的处理方式来写**：`Action.fcurve_ensure_for_datablock()` 是
**待验假设，不是事实**。所以代码里它只是第二档候选：存在且调用不抛就用，`how` 记
`fcurve_ensure_for_datablock`；抛了就退到 channelbag 那条路，并把异常类名留在 `how` 里
（`channelbags[0](new); upstream_raised:TypeError`）——**它试过、什么时候抛的，读记录的人看得见**。
`_shift_b_action` 现在返回 `(改写到几个键, 曲线从哪条路拿到的)`，`concat_via_nla` 的
`align.fcurves_via` 与 `fcurves_via`（烘焙后那条读回）都落进报告。

### 离屏 15 条 + 反向控制

`tests/test_apply_action.py::FcurveWriteShapeTest` 9 条（老形状 find/new、分层单 bag、
槽位优先于位置、两个 bag 不猜就红、连容器都没有也红、上游被用上、上游抛了退回去且留痕）；
`tests/test_chain_nla_fcurves.py` 6 条（真的调 `_shift_b_action`：老形状建三条曲线两个键、
分层动作位移既有键、槽位选对 bag、两个 bag 拒写且**一个字节都没写进去**、
`action.fcurves.find` 那种旧写法在分层动作上确实 `AttributeError`）。

反向控制 `reports/subai/M05/scripts/ctrl_nla_write_shape.py`：把 `_shift_b_action` 退回旧写法 ⇒ **红 4 条**
（其中两条是「拒写」变「崩」，说明旧写法连拒都做不到）；还原 ⇒ 6 条全绿。
脚本自带还原，跑完 `git status` 只剩本次要提交的文件。

全量 **690 tests × 默认/utf-8/gbk 三环境 OK（skipped 1）**，`status --check` OK。

### 上游接口：`D-213` 那条「待验假设」现在有实测了

派工原话是「先确认 5.2 的 `Action.fcurve_ensure_for_datablock()` 能不能直接用；我说的这句是
待验假设，不是事实」。只读探针（`reports/subai/M05/scripts/probe_fcurve_write_shape.py`，打开臂件
`C@W1.blend`、在 `action.copy()` 上试、不存盘，前后 sha `79862401…` 同值）量到：

| 项 | 读数 |
|---|---|
| `hasattr(bpy.types.Action, 'fcurve_ensure_for_datablock')` | **false** |
| `getattr(action, 'fcurve_ensure_for_datablock')` | **true** |
| `__doc__` 里的签名 | `(datablock, data_path, index=0, group_name="")` |
| `__doc__` 里的前置条件 | "**This action must already be assigned to the data-block**"（并会顺手建 layer/strip/slot 再赋槽位） |
| 对一份没挂到 ID 上的 `action.copy()` 真调 | `RuntimeError` |
| 臂件本体 sha（前后） | `79862401ed1f…` 同值，`blend_untouched=true` |

三件事因此定下来：

1. **只能从动作实例上拿这个函数** —— 类上没有。`hasattr(bpy.types.Action, ...)` 会回答
   「不存在」，跟今天那几个「按名字数东西，名字错了给 0」是同一族：**看不见不等于没有**。
2. 签名和我猜的一致（`(datablock, data_path, index=, group_name=)`），不是「碰巧能跑」。
3. **它有前置条件**，而 `chain_nla` 要写的那条曲线恰恰挂在 NLA 条带上、不挂在
   `animation_data.action` 上 ⇒ 真机上调它必 `RuntimeError`。所以代码改成**先判前置条件**
   （`datablock.animation_data.action is action` 才调），不成立就记
   `upstream_skipped:action_not_assigned` 走 channelbag —— 拿异常当流程控制会让每一次正常
   拼接都在记录里背一条假故障，读的人分不清「真出事」和「本来就走这条」。

同一次探针还量到一处**很容易被误判的命名差**：`arm.animation_data.action_slot` 的标识是
`OBB_aligned_bone`，而那个 channelbag 自己槽位的标识是 `B_aligned_bone` —— **是同一个槽位的
两种叫法**（一个带 ID 前缀、一个是动作名）。代码里按**对象身份**比对（`bag.slot is slot`），
若按名字比，会得出「对不上」然后拒写，而实际上唯一候选就摆在那里。

### 一处去重（`4号` 复审提的，已改）

第一版里读侧 `fcurves_of()` 与写侧 `fcurve_container()` 各写了一遍
`layers[].strips[].channelbags[]` 的遍历 —— **同一形状的两份实现**，正是今天已经付过三次
代价的那个形状（`mask_wired` 手抄 11 键 vs 清单 18 键、两份锁逻辑、`use_disk_cache` 差点
被「好心打开」）。现在两侧共用 `_channelbags_of()`，层级一变只改一处，行为与顺序不变
（`fcurves_of` 的两条控制仍然成立：退回旧写法红 3 条、还原全绿）。

### 没验的（写在这里，别去别处找）

1. **上游接口成功那条路没走过**：它要求动作已挂到 data-block 上，`chain_nla` 的场景里不成立，
   所以真机只验到了「`RuntimeError` → 退 channelbag → `find` 到既有曲线」。
2. **真的拿一份存过盘的件重跑 NLA 拼接，仍然没跑过**。离屏证明的是「形状能过」，
   不是「拼出来的动作对」——对齐量、烘焙窗口、导出这些还得窗口里跑。
3. 探针没量「多 bag 多槽位」的真实件：手上五份臂件都只有一个 channelbag，
   所以 `FcurveShapeError` 那条拒写分支只有哑对象验过，**真件没验**。
4. **第二档（槽位对上的 channelbag）在真件上从未被执行过** —— 这条是 `总控` 从我记录的
   `how` 值反推出来的，补在这里：真机读数 `how = "channelbags[0](find)"` 用的是**第三档
   （唯一 channelbag）**，因为五份臂件都只有一个 bag，第二档被短路。也就是说
   `bag.slot is slot` 这个身份比较**一次都没被真正执行过**，而多槽位真件里跑起来的正是它。
   它 fail-closed（对不上就抛 `FcurveShapeError`，不猜），所以不是正确性风险；
   但「槽位选对 bag」这条目前只有哑对象证据。

引用口径随之定死：`fcurves_via` / `how`（形状读数）可以引；**拼接结果对不对不许引**。

## 十四、324 批次补冻结 manifest（`总控` 19:50 要的那次枚举）

`总控` 用 `coordination.artifact_audit` 盘四棵树时，这一批报的是「**量不了**」：14 个文件里
5 份 `.blend` 是 `0o444`、9 个 `.json` 是可写记录，**整批没有 manifest** ⇒「盘上每个在账上、
账上每个在盘上」这一层没有账可对。按要求补一次枚举，**没有重跑批次、没有动任何字节**。

- 生成器：`reports/subai/M05/scripts/make_arms_manifest.py`（拒绝覆盖已有 manifest）
- 账本：`out/subai/M05/arms/20261116_324/manifest.json`（14 项，sha 与 bytes 全部**今天重算**）
- 条目写**裸文件名**：manifest 与产物同目录，`artifact_audit` 的双向枚举才成立
  （它只在「条目都落在 manifest 自己这一层」时才查 `only_on_disk`）。
- `0o444` 只覆盖 5 份 `.blend`（臂件是物证，`D-189`）；9 份 `.json` 是跑批与回读记录，
  写一次但不冻结 —— 账本**如实记** `readonly=false`，不为好看去 chmod。

### 读数（`artifact_audit` 自己给的，不是我自己说的）

```
state = OK      listed = 14    listed_ok = 14    two_way_checked = true
only_on_disk = []   entries_outside_manifest_dir = []   drift = []   warnings = []
manifest_sha256 = 66d4a5d7f3b91731…   manifest_bytes = 4301
readonly 分布 = 5 / 14
```

### 红绿负控（`D-204/205`：校验类代码必须喂应当被拒的输入）

`reports/subai/M05/scripts/ctrl_arms_manifest_negative.py`，全部在**副本**上做，真批次一个字节不碰：

| 构造 | 期望 | 实测 |
|---|---|---|
| 真批次原样 | 绿 | `exit 0` `AUDIT ok=True drift=0` |
| 副本里多一个未登记文件 | `only_on_disk` | `exit 3` `drift=1` |
| 副本里把一个 `.blend` 改一个字节 | `sha_drift` | `exit 3` `drift=1` |
| 把那个字节还原 | 回绿 | `exit 0` `AUDIT ok=True drift=0` |

「还原后回绿」这一步是必需的：否则红的来源说不清是那次改动还是副本本身。

### 没做到的（写在明处）

- 这份账本**没有把 9 份 `.json` 冻结**：它们是可写记录，冻结会让后续批次重写时失败。
  所以这一批的「冻结」只覆盖臂件那一层，账本里 `readonly` 一列如实分列 5 true / 9 false。
- 账本没有进 git（`out/` 是产物树，与 M08 的 `frozen/frozen_manifest.json` 同性质）；
  进 git 的是审计结果 `reports/subai/M05/arms_audit_324.json`。

### 脚本搬进仓库（同一晚的第二处同类缺陷，`D-228` 第十三条）

报告引用了六个脚本，它们原先都在 `out/subai/M05/` 下 —— 而 `out/` 被 `.gitignore:38` 吞掉。
也就是说**干净 checkout 上这些控制脚本根本不存在**，报告里「红 3 条 / 绿 6 条」「绿能绿、红能红」
在别人机器上无法复跑。这跟 `2号` 那处 `compare.log` 是同一个形状：**账本/证据对着工作树成立，
对着仓库不成立**。

现在六个都搬到 `reports/subai/M05/scripts/` 并进了 git（`out/` 里的旧副本已删：两份实现就是两个真值）：

`make_arms_manifest.py` / `ctrl_arms_manifest_negative.py` / `ctrl_fcurves_shape.py` /
`ctrl_nla_write_shape.py` / `probe_fcurve_write_shape.py` / `readback_324_arms.py`

搬动时顺手把「算根」改成**自定位**（往上走到有 `coordination/` 与 `mmdpipe/` 的那层）：
产物树与仓库深度不同，写死 `dirname` 次数必然有一边算错，而算错的形状是 `ImportError`
——看起来像「这个模块不存在」。走不到就把起点打出来再死。

搬完的实测（从**新位置**跑）：

| 脚本 | 结果 |
|---|---|
| `ctrl_fcurves_shape.py` | 旧写法红 **3** 条 / 还原绿 |
| `ctrl_nla_write_shape.py` | 旧写法红 **4** 条 / 还原绿 **6** 条 |
| `ctrl_arms_manifest_negative.py` | 绿 / `only_on_disk` 红 / `sha_drift` 红 / 还原绿 |
| `make_arms_manifest.py` | 仍认 14 项（并补上「任何 `*manifest*.json` 不入账」的排除规则，与 `artifact_audit` 对齐） |
| `probe_/readback_` | 根均解析到仓库根；`probe` 的守卫负控（拷到别处）仍报「ROOT 算错了」 |

**仍然留在 `out/` 的**：`arms/20261116_324/` 那 14 个产物（含 `manifest.json` 账本本身）——
6–10 MB 的 `.blend` 不进 git 是对的。所以「这批的字节」在干净 checkout 上依然量不了，
能复跑的是**控制逻辑**；枚举的 sha 结论由进 git 的 `reports/subai/M05/arms_audit_324.json` 承载。

### 证据/摘要生成器也镜像进仓，并且**默认拒绝覆盖**

同一条第十三条继续往下一层查：报告里的证据不是凭空写的，它有两条生成链，原先也都只在 `out/`：

- `reports/subai/M05/scripts/build_arms_summary_324.py`：七臂记录 → `arms/20261116_324/summary.json`
- `reports/subai/M05/scripts/build_evidence_attempt11.py`：→ `evidence_m05_attempt11.json` + 闸门包

照 `D-225` 的「能补的用记录、不可逆的用拒绝」分了一下：**这两支的默认输出是已提交的交付证据**，
重跑一次就会静默改写它 ⇒ 默认路径已存在就 `exit 2`，要覆盖必须显式 `--force`；
新增 `--out` 只为**验证**（写到临时目录，产物树不留东西）。

验证不是「应该能跑」：

| 项 | 读数 |
|---|---|
| `summary.json` 重建（`--out` 到临时路径） | **与已提交件逐字节相同**：30 965 B / sha `ca3afd87…` |
| `evidence_m05_attempt11.json` 重建 | `evidence/1:5a46a74d…`，`evidence check` **exit 0**；与已提交的 `0d66add0…` **不同** |
| 已提交证据与闸门包 | 未被改动（`0d66add0…` / `3ae49f68…`） |

digest 不同是**对的**：证据的输入里有 `apply_action.py`、`tests/test_apply_action.py`、本报告、`summary.json`，
而这四份在 attempt 11 之后都改过。它说明**证据是「那个 HEAD 的读数」，不是永久真相** ——
所以更不能让它被随手重跑覆盖。

#### 镜像过程中撞出来的两处，都是我自己埋的

1. **账本混进了输入**：批次目录里放了 `manifest.json`（冻结账本），而 summary 生成器把目录里每个
   `.json` 都当臂记录 ⇒ 重跑会多一条 `{"arm": "manifest", 全 None}` 的假记录，把物证摘要从
   30 965 静默改成 31 580 字节。已加 `*manifest*.json` 排除（与 `artifact_audit` 同一条规则）。
2. **`--out` 只重定向了证据、没重定向闸门包**：第一次验证就把已提交的 `gate_m05_attempt11.json`
   改了一个 snapshot 路径，被 `git status` 抓到、已 `git checkout --` 还原。现在闸门包跟着 `--out` 走
   —— **验证性运行必须能完全落在临时目录里**，否则「只验证一次」就是一次改写。

### 第十三条的另一面：`git status` 看不见 `out/` 里的东西（`4号` 点的）

我给 `4号` 的验收断言是「验证性运行之后 `git status --porcelain` 必须为空」。他指出这条**只覆盖仓库内的文件** ——
而产物树里的读数不在 git 视野里，被覆盖了也不会红。他说得对，而且这条正好咬我：**报告引用的两份读数就住在 `out/`**：

| 脚本 | 输出 | 原状态 | 现在 |
|---|---|---|---|
| `readback_324_arms.py` | `out/subai/M05/arms/20261116_324/readback_arms.json` | 重跑**静默覆盖** | 目标存在即拒绝，`--force` 才覆盖 |
| `probe_fcurve_write_shape.py` | `out/subai/M05/probe_fcurve_write_shape.json`（默认） | 重跑**静默覆盖** | 同上 |

之所以要拒：这两份是**报告 §十一/§十三 的数字出处**，而它们在 `out/` 里没有第二份 —— 覆盖掉就只剩「记忆」。
`D-225` 的判据在这里同样适用：**不可逆的用拒绝，可补的用记录**（生成器那两支写的是 git 里的交付件，一样拒）。

### 真机负控（不是「应该会拒」）

`guard` 代持锁、`blender -b --factory-startup --python-exit-code 3`、目标文件已存在：

```
REFUSE 已有读数：…\readback_arms.json（确需重测加 --force）
GUARD_DONE rc=10
readback_arms.json sha256 前后同为 eaf82204…（一个字节没写）
```

**这里我先写错一次，被 `4号` 用七种形状的真机读数纠正**：第一版守卫写 `return 2`，跑出来是 `rc=0`，
我当时记成「`blender -b` 把 `SystemExit` 吞了」。**不成立。** 他实测（Blender 5.2.2 LTS `d13f752e3b9c`）：
`--python-expr "raise SystemExit(3)"` → 3、`sys.exit(7)` → 7、模块级 `sys.exit(main())` 里 `main()` 抛
`SystemExit(4)` → 4；而**同一个 `main()` 只写 `main()`、返回值没人接** → 0。所以 `rc=0` 的真因是
**返回值被丢掉**，不是码被吞。本文件末尾原本就是裸 `main()` —— 正是这一种。

同时采纳他一条更要紧的：**语义码不要用 3**。`3` 是 `coordination.lock` 自己的「冲突/拒绝回收」码，
而 `guard` 透传子进程 rc ⇒「脚本拒绝覆盖」和「锁被占着」会撞成同一个数。现在这两个脚本用
**10 = 拒绝覆盖**（11 / 12 留给「输入或身份对不上」「断言不成立」），`--python-exit-code 3` 只兜意外异常。

还有一处是我自己发现的、比退出码更要紧的：守卫原先排在**测量之后**——先花 20 秒开臂件做完读数，
再告诉你能不能落盘。已挪到 `main()` 最前面，先判目标再干活；负控因此不再需要一份 `.blend` 也能验
（实测无 `.blend` 时照样 `rc=10`，目标 sha 不变）。真正保证「没写」的仍是文件 sha 前后同值，
退出码只负责让调用方停下。
