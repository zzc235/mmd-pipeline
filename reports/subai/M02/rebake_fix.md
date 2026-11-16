# M02 · 「同一个 `.blend` 两种动画」的修法

缺陷：产物工程带 `point_cache.is_baked = true && is_outdated = true`。默认消费路径（打开 + `frame_set`）
走**回放**，任何触发重算的路径走**另一条轨迹**——`B_from_blend1.blend` 上两者差下摆 **0.9087 m**、
全刚体 **1.5867 m**（P7 已判定：默认路径与 A1 回放逐位相同，与 P0 重算差 0.91 m）。

> **先更正一个前提（P13，2026-11-16）**：`is_baked=true && is_outdated=true` **不是**缺陷证据。
> 真烘焙件保存后重开**也是**这两个值（`J_baked.blend` 冷跳 f109/f240 对 `P0` 逐位 0.000000）。
> 这一对旗标的真实含义是「打开时无法证明缓存与当前设置一致」，它只是**筛选信号**；
> 定性必须靠**行为探针**（冷跳某中间帧 vs 从 `frame_start` 顺序重算同一帧）。详见 §2.7。

## 一、两条修法，现在两条都测得动了

| 修法 | 目标状态 | 实测 |
|---|---|---|
| ① 重算后**重新烘焙并保存**（`bake_all`） | `is_baked=true`（`is_outdated` 重开后仍为 true） | **可行**：P13 exit 0、32.2 s、326 帧、无段错误、冷跳逐位等于重算。需 10 §6 逐场景豁免（已获常驻豁免，四条条件见 §2.8） |
| ② **解烘焙**后保存（不烘焙） | `is_baked=false` | **可行**：`free_bake_all()`，M02 实测十余次无崩溃 |

**D0 13:31 裁定：交付形态取 ①（烘焙）**，理由是 ② 的陷阱对**人**不消失（谁拖时间轴谁看到别的动画）。
② 保留为低成本降级路（正式名 `sequential_delivery`），契约：
（a）handoff 写明「首次 `frame_set` 会从头重算」；
（b）**消费方必须从 `scene.frame_start` 顺序求值**——跳到中间帧再渲染会得到第三条轨迹（P11/P12 实测，
见 §2.5）。适用于渲染整段，不适用于「只渲染中段 / 并行抽帧」。

**①的产物还必须过行为探针才算数**（§2.8 第 4 条）。

## 二、执行步骤（产出侧，bpy 内）

```
open_mainfile(src)
…（建模/物理参数改动）…
bpy.ops.ptcache.free_bake_all()        # 清掉可能被带进来的过期缓存
save_as_mainfile(filepath=dst)         # 保存后 is_baked=false
```

若要按①烘焙（先拷副本，单次）：

```
bpy.ops.ptcache.bake_all(bake=True)    # 32 s/场景（324 刚体，326 帧）
save_as_mainfile(filepath=dst)
# 然后：新进程打开 dst → frame_set(中间帧) → 与顺序重算的同一帧比，写进 sidecar 的 behavior
```

保存后用判据复核（`mmdpipe.cache_state`，纯 Python，可进包、可进 CI）：

```
records = {"dst.blend": {"exists": True, "has_physics": True,
                         "is_baked": False, "is_outdated": None}}
code, report = cache_state.evaluate_many(records)   # 期望 code == 0, verdict == OK_UNBAKED
```

`cache_state.plan()` 给出动作：`SUSPECT_BAKED_OUTDATED → probe_behavior`、`DEFECT_BAKED_OUTDATED → rebake`、
`OK_* → none`、`UNREADABLE → inspect`。（`sequential_delivery` 是 §1 的 ② 的正式名字：**降级交付**，
带 §2.5 的遍历契约；旧名 `unbake` 语义不清已作废。）

## 二·五、P12：为什么「跑一遍再存盘」不是修法

**预注册**：判据由 D0 在运行前给定（2026-11-16 13:24:53，Thread `thread:03241ae8-7140-4882-b230-d33b7aa1500c`）——
「等于 P0 ⇒ 修法定案；不等 ⇒ 才谈 §6」。该消息早于本实验的两次运行（13:24:2x / 13:25:0x），
参数与判据均未在运行后改动。

有人会想：解烘焙 → 从第 1 帧顺序跑到 240（`is_outdated` 变 false）→ 存盘 → 以后任何位置都能跳。
**实测不行**（P12，锁 13:24:2x→13:25:09，`G_base` 前后 sha 不变）：

| 时刻 | is_baked | is_outdated | info |
|---|---|---|---|
| `free_bake_all()` 后 | false | true | `240 frames in memory (2.1 MiB), cache is outdated!` |
| 顺序走完 1→240 | false | **false** | `240 frames in memory (2.1 MiB).` |
| 新进程重开 | false | **true** | `240 frames in memory (2.1 MiB).` |

`use_disk_cache = False` ⇒ **内存 point cache 不写进 `.blend`**，落盘的只有 `info` 那行字符串。
冷跳 f109 对 `P0[109]` 差 `D_max = 1.922861 m`（`272_右足4`），与「只解烘焙、不步进」的
`H_nobake.blend` **完全相同**——存盘这一步没改变任何东西。

同一次跑的另一半是好消息：**顺序求值本身是精确的**——`seq@109` 与 `seq@240` 对 `P0` 逐位
`0.000000 m`（0/324 非零）。所以 ② 的路是「顺序求值」，不是「把缓存搬进文件」。

⇒ **「跑一遍再存盘」进 `cache_state.REJECTED_ACTIONS`（键 `rebake_by_stepping`），`plan()` 永不输出它。**

## 二·六、不要把 `point_cache.info` 当证据

`info` 是可以随 `.blend` 落盘的字符串，帧数据不会。一份重开后实际已无缓存的文件，
`info` 仍写着「240 frames in memory (2.1 MiB)」。**它只当线索，不当证据。**

## 二·七、P13：`bake_all` 一次受控实测（§6 临时豁免）

判据同样先定后跑（D0 13:27:36）：只在副本上、单次不重试、记 `use_disk_cache`、成功也要验冷跳。

| 项 | 实测 |
|---|---|
| `bpy.ops.ptcache.bake_all(bake=True)` | **exit 0，无段错误**，32.2 s（总 33.19 s），**326 帧** |
| `use_disk_cache` | **false** ⇒ 烘焙**不要求**磁盘缓存 |
| 源 / dst | `J_src.blend` sha 前后不变；`J_baked.blend` 11 940 653 B，`e22e03f5…` |
| 同进程烘焙后 | `is_baked=true, is_outdated=false` |
| 新进程重开 | `is_baked=true, is_outdated=**true**` ← **翻回来了** |
| 冷跳 f109 / f240 vs `P0` | **逐位 0.000000 / 0.000000** |
| 整段 240 帧（`A --allow-baked`） | `frames.jsonl` sha 与 `P0` **逐字节相同**（`80819da0…`） |
| 冷跳 vs `A1`（旧回放） | 1.5867 m ⇒ 不是回放 |

**两条结论**：

1. **烘焙可用**，产物对任何跳帧都给正确动画 ⇒ 交付形态取 ①（B）；
2. **旗标不能定性**：`J_baked`（健康）与 `B_from_blend1`（缺陷）**标志位完全相同**。所以判据改成
   「旗标只筛选 + 行为探针定结论」，`DEFECT_BAKED_OUTDATED` 只在**有行为证据且不一致**时给出，
   没有证据判 `SUSPECT_BAKED_OUTDATED`（4，未测 ≠ 不合格）。`cache_gate_inventory_v2.json` 里
   17 个 `.blend`：1 个 `DEFECT`（`B_from_blend1`，唯一有行为证据的）、6 个 `SUSPECT`、10 个 OK。

## 二·八、§6 常驻豁免的四条条件（D0 13:31 裁定）

1. **只在副本上**，绝不存回 `B_from_blend1` / `E_base` / `G_base`（报源 sha256 前后一致）；
2. **每场景单次**，不重试；
3. **崩溃只记退出码、发生时点、最终 `is_baked`/`is_outdated`**，当结果上报；时间线用 JSONL 逐行 flush，
   C 侧崩了也知道崩在哪一步（`m02_s8_p13.py`）；
4. **成功也必须过行为探针**（冷跳 == 顺序重算）才算数——烘了但冷跳仍不等，结论同样是不可用。

「312 刚体 `bake_all` 段错误」记为**今日不可复现**，但**不据此删禁令**：条件保留，规则不删。

## 三、观测侧（Blender 内，取一次 1–2 秒的锁）

`reports/subai/M02/scripts/m02_cache_gate.py`：只读打开一批 `.blend`，输出每份的
`is_baked / is_outdated / 缓存帧范围 / 刚体数`，**判据从 `mmdpipe.cache_state` 借来**（不在本脚本里留第二份，
否则两处判据必然漂——这一版就是为这个改的；`import` 不到就 exit 4 而不是用本地副本顶上）。
退出码按严重度：任一 `DEFECT` ⇒ 3；否则任一 `SUSPECT`/`UNREADABLE` ⇒ 4；否则 0。

`--behavior behaviors.json` 给行为证据（键 = 文件名或绝对路径）：`{cold_jump_frame, cold_jump_vs_recompute_m, tolerance_m}`。

现行盘点 `cache_gate_inventory_v2.json`（`out/` 下 17 个 `.blend`）：
**1 个 `DEFECT`（`B_from_blend1.blend`，唯一有行为证据的）、6 个 `SUSPECT`、10 个 OK**；
其中 `J_baked.blend` 是 `OK_BAKED_VERIFIED`（烘过、行为也对）。
旧盘点 `cache_gate_inventory.json` 里那 6 个「缺陷」是**当时把旗标当结论**的结果，已按 D0 裁定全部降为 `SUSPECT`。

## 四、为什么要把它做成判据而不是注意事项

这条缺陷不会报错、不会崩、渲染也出得来——**只有把两条轨迹并排量一遍才看得见**。
所以判据必须能进产物链：`cache_state` 是纯 Python 判据（已在包内，`628ba3c`），
观测值是 bpy 侧的布尔/数字，两边分开，`stage.py` 侧只需喂一个 dict。
反过来，**只看旗标会把健康件判死**（P13 的 `J_baked` 就是），所以判据必须允许「未验证」这一态，
并把它与非 0 退出码绑在一起——不静默放行，也不冒充结论。

## 五、边界（按 D0 的 A+ 裁定）

- 本笔**不动** `stage.py` / `runner.py`（块 4 的文件），只交判据与判据的调用方式；
- `stage.py` 里那行调用由 4号 在自己下一笔接；
- 重烘焙这条路**已解禁为常驻豁免**（四条条件见 §2.8），不再是「不可行」；§6 的原始禁令不删，
  只是条件化。「312 刚体段错误」记为**今日不可复现**。

