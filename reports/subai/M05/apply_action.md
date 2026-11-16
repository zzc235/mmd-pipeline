# M05 · 交付链「应用动作」这一步（`D-186` 插单）

交付物是一个**函数 + 一条 CLI**，不是一段新流水线：下层实现是 `mmdpipe/stage.py:1009`
的 `stage_motion`（`runner.py:661` 一直在用），这一步只在它外面补三件事——**幂等、窗口、回读**。

- 代码：`mmdpipe/apply_action.py`（新增文件，**只增不改**：`stage_motion` 一行没动）
- 测试：`tests/test_apply_action.py`（22 条，全部离屏，不含 bpy）
- 记录：`reports/subai/M05/arms/*.json`（真 Blender 跑出来的原始记录）+ `arms_summary.json`

## 一、四条验收单的读数（真 Blender 5.2.2 LTS，每臂一个独立进程）

输入场景 = `A1/out/subai/M08/run_20261116_1805/rebuild_built.blend`
（`5 923 244 B` / `ef8e31a9…`，312 刚体、482 骨、骨架 `星穹铁道—飞霄（无外套）_arm`）。
四臂输入**同一个文件**，臂间只差动作源与窗口。

| 臂 | 动作源（sha / 帧 / 骨） | action | fcurves | `scene.frame_end`（回读） | `is_baked` | 产物 sha256 | 判 |
|---|---|---|---|---|---|---|---|
| `C@W1` | `B_aligned.vmd` `5d391f1a…` 0..300 / 332 骨 | `B_aligned_bone` 1..301 | 725 | **301** | false | `d244038f…` | READY |
| `C@W2` | 同上 + `--hold-until 832` | `B_aligned_bone` 1..832 | 725 | **832** | false | `d56e50ee…` | READY |
| `D` | `kafuka_all/vmd/原神摇_merged.vmd` `b872fda7…` 0..832 / 259 骨 | `原神摇_merged_bone` 1..833 | 700 | **833** | false | `32a41adc…` | READY |
| `D-对照` | `out/原神摇_merged.vmd` `027179ac…` 0..446 / 52 骨 | `原神摇_merged_bone` 1..447 | 357 | **447** | false | `015a9ca4…` | READY |

四条同时成立：动作显式应用（fcurves 357–725，`stage_motion` 的门槛是 >100）/
`scene.frame_end` **等于回读的** `action.frame_range[1]`（来源字段写死
`readback:arm.animation_data.action.frame_range[1]`）/ 应用后 `is_baked` 仍为 **false** /
每臂都有 `sha256 + frame_end + 动作来源(路径/树/sha/帧/骨) + is_baked 回读`。

`D-对照` 按裁决**不进 D 的判词**：它是 447 帧原片版，只为把「同名不同物」这件事留证。

## 二、帧号换算（三行，逐臂都记在 `plan.notes` + `applied.ops`）

`mmd_tools` 的 `ImportVmd` 落在 `scene.frame_current + 1`，所以：

```
源末帧 300 → 应用后 action 1..301 → 最终 scene.frame_end = 301      (C@W1)
源末帧 300 → 应用后 action 1..301 → 定格到 832 → scene.frame_end=832 (C@W2)
源末帧 832 → 应用后 action 1..833 → 最终 scene.frame_end = 833      (D)
```

**不裁源**（按 `D-186`）：D 臂源第 832 帧落在 action 833，在预注册的测量窗口 1..832 之外
⇒ 「**尾帧未测**」进 `known_risks`，不靠裁掉它来对齐。

`C@W2` 的定格起点：预注册写「301..832 保持末帧姿态」，**回读**给出的
`applied.end_before_ops_readback = 301`（最后一个**有键**的帧）、`ops[0].from_readback = 301`
⇒ 实际保持区间是 **302..832**（在 832 插一个与末键同值的键，两键同值 ⇒ 中间恒为末帧姿态，
不靠改插值模式）。两个口径差一帧，来源是「末键帧算不算保持段」，已写进记录不留给下游猜。

## 三、幂等：判在回读内容上，不判在 `.blend` 字节上

`C@W1` 的产物再喂回同一条命令（`C_W1_rerun`）：

| | action | window | cache |
|---|---|---|---|
| 第一次 | `B_aligned_bone` / 725 / 1..301 | 1 / 301 / readback | is_baked=false |
| 复跑 | 同上（**逐字段相同**） | 同上 | 同上 |
| `cleared` | — | — | `action=True, nla_tracks=0, orphan_actions=1` |

- **回读内容相同**（`arms_summary.json` 的 `idempotence.readback_equal=True`）；
- `.blend` sha **不同**（`d244038f…` vs `d2621e72…`）——与 `1号` 的读数同结论：
  字节不可复现，所以幂等只能建在内容上；
- `cleared.action=True / orphan_actions=1` 证明**清理真的发生了**，不是「本来就没有」——
  这条比「两次结果一样」重要：不清就会在同一个骨架上叠两个动作，而报告里看不出来。

## 四、反控（能红也能绿，红在哪条写得出来）

**离线三条，各自只红它自己那一条**（`D-186` 批准）：

| 反控 | 结果 |
|---|---|
| 声明 `frame_end` 与回读不符 / `frame_end` 不是回读来的 | 只红 `A2_frame_end_readback` |
| 应用后 `is_baked=True` | 只红 `A3_is_baked_false` |
| 计划参数自相矛盾（`hold_until` ≤ 应用后末帧、`trim_end` 越界、两者同时给） | `PlanError`，一个字节都不动 |

另加两条同形状的：`fcurves` 不足只红 `A1`、留 NLA 轨道只红 `A4`、缺字段一律判红不抛异常。

**场景级反控（一条真跑的）**：`CTRL_no_addon` —— 关掉插件闸门后
`stage_motion` 拿到 `import_vmd ... could not be found`（E-14），记录判 **BLOCKED**、
进程 **exit 3**、**没有写出交付件**（`out_blend=null`，盘上 0 个 `CTRL_no_addon.blend`）。
它红在 `A0/A1/A2/A3/A5` 五条上——这与上面三条不矛盾：三条离线反控验的是「判据逐条可分」，
场景级反控验的是「整段没成就整份拒收」，多头红是应该的。

这条反控还顺手暴露了一个真实缺陷并已修：**判红时不许写交付件**。
第一版 CLI 无论判红判绿都 `save_as_mainfile`，等于把「注定不合格的件」留在盘上让人当已有交付。

## 五、已知风险 / 口径

1. **`scene.fps` 被导入改成 30**：交付件是 24 fps，`import_vmd(update_scene_settings=True)`
   按 VMD 的 30fps 基准把场景设成 30（四臂全部 `fps_before=24 → fps_after=30`）。
   `stage_motion` 那句 `E-00` warn 用的是**预设里的** fps，与实际读回值不是一回事，
   记录里 `fps_before/fps_after/fps_changed` 才是准的。
2. **尾帧未测**（D 臂）：源第 832 帧落在 action 833，测量窗口 1..832 之外。
3. **`C@W2` 有 531 帧是定格**，`D vs C` 只在该窗口同段比较；定格段内不存在「动作差异」。
4. **物理不变**：这一步不建物理、不动掩码，312 刚体原样带过来（`is_baked` 全程 false，
   消费方可从 `scene.frame_start` 顺序解算）。
5. **强内容摘要待并线**：`content_digest_v1` 要求逐刚体 `bodies[]`，那部分在 `1号` 的
   重建回读里；我这边交的是两层身份——**实例 sha（本文件）+ 回读内容字段**，
   并与 `1号` 在并线时合成强摘要，不自己再造一份读刚体的实现。
6. **四棵树共享 `mmdpipe/`**：本提交合入 main 后，**其余三席需重新并 main**，
   否则会拿着没有 `apply_action` 的旧库跑出两种行为。

## 六、给下游的两个接口

- `2号`（穿透测量）：每臂四样 = 产物 `path/sha256`、`scene.frame_end`（回读）、
  `action.frame_range`、`is_baked`；见 `arms_summary.json` 的 `arms[]`。
- `1号`（交付构建链）：`apply_action(preset, root, arm, vmd_path, hold_until=...)`
  一行调用 + 回读记录；CLI 形式
  `blender -b <blend> -P mmdpipe/apply_action.py -- --vmd A.vmd --preset P.json --out-blend B.blend --json R.json`
  （判红时 exit 3 且不写 B）。
