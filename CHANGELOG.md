# v1.0.0 — 2026-11-08

第一次定版。目标只有一件：**把「PMX + VMD → 成片」稳定复现**，并在导入前判断物理资格、修初始穿透。

## 两条安全约定

1. **源文件只读。** PMX / VMD 全程不改，任何改动落在 `--out` 下的副本上；流程首尾各算一次 sha256，不一致直接 block（`S0_readonly`）。
2. **写回不做重序列化。** `patch_save` 只按字节偏移改位置浮点数，其余字节原样保留；`dst` 与源路径相同直接拒绝。

## 帧率口径：默认改为 30fps（2026-11-10）

**这是一条会改变所有成片速度的修正。**

VMD 的帧号以 **30fps** 为基准。此前预设里写的是 24fps（随手填的默认值），后果是：

- 同样的帧数，24fps 比 30fps **多播 25% 的时长** → 动作整体慢放四分之一
- 不重采样只改 fps，帧号不变、时长变，所以是"变速"而不是"换帧率"

实例：833 帧的拼接成片，30fps 下 27.77 s，24fps 下 34.71 s。

历史样片的时间口径因此都是错的（慢 25%）。例如绯英 360 帧 @24fps = 15 s，而那段动作 447 帧在 30fps 下本来就是 14.9 s——等于只渲了 80% 的动作又拉长成 100% 时长。

现在默认 `fps: 30`，非 30 时 `S3_motion` 会给 WARN 并列出两种 fps 下的时长对照。

## 新增模块

| 模块 | 作用 | 依赖 |
|---|---|---|
| `pmx` | PMX 2.0 解析、字节偏移、`patch_save` | 无 |
| `vmd` | VMD 解析（骨骼/表情轨） | 无 |
| `match` | VMD × PMX 命名匹配覆盖率 | 无 |
| `physics` | 物理资格判断（三档） | 无 |
| `clearance` | 净空检测 + 外移修复 + 关节同步 | 无 |
| `verify_pmx` | C1–C8 验证套件 | 无 |
| `preset` / `report` / `preflight` | 预设、数据契约、命令行预检 | 无 |
| `stage` / `runner` | Blender 侧阶段与编排 | bpy |

## 实测证据（摘要）

- 解析：10/10 PMX、6/6 VMD 全过，字节全对齐
- 物理资格：四模型零误报；卡芙卡袖子自动静音 48 骨 / 48 约束 / 0 遗漏
- 自动修复 vs 手工：480 帧 PSNR **71.82 dB**、SSIM **0.99999**
- 净空修复：3 个刚体、7/7 验证、与手工 `fixH.pmx` **位置 0 差异**
- 三特性叠加（strict + clearance + `force_static Hair`）vs 手工 v4：PSNR **60.03 dB**、SSIM **0.99986**
- 复现：360 帧冻结相机 vs 原片，平均差 0.436/255

## 强制声明（force_static / force_physics）

判断器只做"能从结构判断的"；像"这个模型的头发就是要刚性"这种取舍，用预设声明：

```json
"physics": {
  "policy": "strict",
  "force_static": ["Hair"],      // 强制不做物理（刚体名/骨名子串）
  "force_physics": []
}
```

声明优先于推断：`force_static` 并进静音名单，`force_physics` 从中剔除。这样 v4 那种决定变成可复现的声明，而不是每次让算法猜。

## 道具挂接

道具是独立的单骨 PMX（`刀.pmx` / `枪白.pmx` / `枪黑.pmx` / `子弹.pmx`），建模在自己的局部空间，
离角色很远（刀的包围盒 Y≈5.7、Z 跨 17.7 PMX 单位）。挂接流程：

```
导入道具 → root 父级设为角色骨（parent_type=BONE）→ 用 matrix_world 把道具那根骨对准目标骨 head
        → 可选 loc/rot 偏移 → 校验偏差
```

```bash
--prop "刀.pmx@右手首" --prop "枪白.pmx@左手首"
```

骨名带**别名解析**：`右手首` → `手首.R`（这个模型的实测骨名），也支持唯一子串匹配。

实测（卡芙卡 + 爱乐之城）：

| 道具 | 目标骨 | 解析 | 偏差 | 位移 |
|---|---|---|---|---|
| 刀 | 手首.R | 别名 右手首→手首.R | 0.000 mm | 0.513 m |
| 枪白 | 手首.L | 别名 左手首→手首.L | 0.000 mm | 0.438 m |
| 子弹 | 手首.R | 别名 右手首→手首.R | 0.000 mm | 0.435 m |

跨帧跟随（f1 / 60 / 200 / 360）手与道具骨距离 **全部 0.0000 m**——不脱手。

道具在**取景之前**挂上，所以 G7 的包围盒会把武器算进去，不会被裁掉。

## 表情 VMD 合并

独立的表情文件（`表情.vmd`）和动作是两份 VMD。合并**不重新编码任何帧数据**，只做字节拼接：

```
头部 + 骨骼段(来自动作) + 表情段(来自表情文件) + 尾部(相机/灯光/阴影/IK，来自动作)
```

```bash
python -m mmdpipe.mergevmd 动作.vmd 表情.vmd --out 合并.vmd --pmx 模型.pmx
# 或走流水线
--expression 表情.vmd
```

实测（活着dj + 表情 → 绯英）：

| 项 | 结果 |
|---|---|
| 骨骼段 | 252 轨 / 20718 帧，**与源文件逐字节一致** |
| 表情段 | 41 轨 / 200 帧，**与源文件逐字节一致** |
| 表情对模型覆盖 | 97.6%（40/41，缺的是一条空名占位轨） |
| Blender 导入 | `morph animations: 41`，`まばたき` 随帧 0→0.041→0.126 真在动 |

注意：表情文件里大量轨道是**全 0 占位**（41 条只有 4 条权重非零），选一条不动的表情去验证会误判成"没生效"。

## 多动作拼接

几段 VMD 首尾接成一条时间轴，同样**只改帧号字段，不动其余字节**。

```bash
python -m mmdpipe.concatvmd a.vmd b.vmd --out 拼接.vmd --gap 6 [--offsets 0,300] [--expression 表情.vmd]
# 或走流水线
--motions "a.vmd;b.vmd" --chain-gap 6
```

实测（原神摇 + 活着dj，gap 6）：

| 段 | 源区间 | offset | 时间轴 |
|---|---|---|---|
| 原神摇 | 0..446 | 0 | 0..446 |
| 活着dj | 0..379 | 453 | 453..832 |

- 合计 43962 条骨帧，**逐条（名字 + 帧号 + 其余 96 字节）与源文件完全一致**
- Blender 导入：`action chain_bone`，范围 **1..833**，665 条曲线
- 两段姿态确实不同：`上半身` 在 f460 / f600 / f800 的旋转互不相同
- 拼接后若时间轴重叠，`S3_chain` 直接 BLOCK

**表情必须跟着段走。** 多段拼接后合并表情时要给 `offset`，否则表情会落到第一段：
`活着dj/表情.vmd`（0..402）配 offset 453 → 落在 **453..855**。流水线会自动判断——
表情文件与哪段动作同目录，就用那段的 offset（实测 `expression_segment: 1`）。

全特性组合实测（拼接 + 表情 + 净空 + 物理策略 + 道具）一次跑通，16 个阶段全 PASS。

## 版本控制（2026-11-10 起）

仓库：`https://github.com/zzc235/mmd-pipeline`（私有）
首提交 `67b2297`「初始提交：MMD 流水线 v1.2.0」，102 文件 / 542 KB。

`.gitignore` 采用**白名单**：工作区里有大量 200–600 MB 渲染产物（`addon_full/` 431 MB、
`skills_probe/` 660 MB、`kafuka_*` 各 200+ MB），用排除清单迟早误提交，只放行源码与文档。

从这条起，改动以提交历史为准。

## v1.2.0 — 参数声明层 + 测试护栏 + 插件重构

评审指出根因不是"缺字段"，而是**面板、CLI、测试、续跑四处各写各的**。
按这个思路重做，而不是逐个补。

### 1. 参数唯一声明源 `mmdpipe/params.py`

21 个字段声明一次，`argparse` 和 Blender PropertyGroup 都从它生成：

```python
Param("chain_gap", "int", default=0, label="段间空帧",
      help="两段之间的空帧数；太小会看到明显甩动")
```

- `params.add_arguments(ap)` → runner 的 CLI（不再手写 add_argument）
- `params.blender_properties(bpy)` → 面板 PropertyGroup（动态生成类）

实测面板 21 字段 = 声明 21 字段，`面板缺: []`。**结构上不可能再漂移。**

### 2. 插件按成熟插件的分法重构（参考本机 mmd_tools）

```
addon/mmd_pipeline/
  __init__.py      只做注册
  properties.py    参数 → PropertyGroup（与 CLI 同源）
  operators.py     子进程 + modal：进度、ESC 取消、日志落盘
  panels.py        主参数平铺，逃生参数进"高级"折叠区
  mmdpipe/         纯逻辑库
```

长任务用**子进程 + timer 轮询**，不用线程（bpy.data 只能主线程访问）。

### 3. state 契约

```json
{"schema": 2, "env": {"blender": "5.2.2", "mmdpipe": "1.2.0"}, ...}
```

字段还在加（framing 就是后加的），旧 state 必须显式迁移或拒绝，否则续跑会静默用错语义。

### 4. 测试护栏

| 层 | 跑法 | 覆盖 |
|---|---|---|
| 纯 Python | `python -m unittest discover -s tests` | 27 个断言：参数同源、VMD 拼接字节一致、表情偏移、对齐判定、物理单元识别 |
| bpy 层 | `blender -b -P tests_bpy/smoke.py` | 包内导入、参数同源、argv 生成、无预设取景 |

测试夹具**必须带空格**（`E:\dsh pr` 本身就在踩这个坑）。这轮撞出的三个事故各有一条对应用例：
函数契约（`stage_camera` 必须返回二元组）、配置路由（预设 path）、扩展包内导入。

## v1.1.6 — 换模型不再崩：外观路线 + native 三点光

用 `宵宫.pmx`（原神角色）跑，暴露两个问题：

**1. `look.route` 是死配置。** `stage_look` 从来没按它分支，永远走 HSR 六步。
HSR 材质只认星铁角色库，宵宫直接报"未找到对应角色"，整条流程 E-07 BLOCK。

现在：
- `hsr`：星铁角色（材质/SDF/描边/后期）
- `native`：保留模型自带的 MMD 材质，只配灯光与世界
- `auto`（新默认）：先试 hsr，材质那步失败就回退 native，记一条 WARN 不阻断

实测宵宫：`route_requested=hsr → route_effective=native`，流程通过。

**2. native 路线下一盏灯都没有。** 场景只有 0.6 强度的世界背景，渲出来发闷。
补上社区 `blender-lighting` Recipe 0b 的三点光（profile=skin，4:1:1）。

能量要缩：技能公式 `100 * (dist/1.5)^2` 是按 Cycles + 1 m 主体算的，EEVEE 下实测：

| 倍率 | 主体亮度 | 过曝 |
|---|---|---|
| ×1.00 | 0.845 | 79% |
| ×0.35 | 0.746 | 59% |
| ×0.10 | 0.586 | 30% |
| **×0.05** | **0.475** | **2.2%** |

默认 `look.light_scale = 0.05`。

## v1.1.5 — 联络表（用 ffmpeg，不自己拼图）

按项目规则第一条：先找现成的。联络表不需要写拼图代码，ffmpeg 自带 `tile` 滤镜，而我们本来就依赖它。

每次运行自动产出 `contact_sheet.png`（4×3，12 张采样帧，间距 `总帧数 // 12`），
记进 `S8_verify.metrics.contact_sheet`，作为验收时"先看一张图"的入口。

```bash
ffmpeg -y -start_number 1 -i frames/s_%04d.png \
       -vf "select='not(mod(n\,10))',scale=320:-1,tile=4x3" -frames:v 1 contact_sheet.png
```

## v1.1.4 — 确认门 + 修一个 refactor 回归

**确认门（P0 的最后一件）。** 过渡明显不成立时不再"报一声就放行"：

```
× E-16  过渡太快：最大骨差 95.9° 压在 7 帧里（13.7°/帧），
        建议 --chain-gap ≥ 19 或 --force 显式放行
```

判据：`最大骨差 > 45° 且 gap < 推荐值`。实测 gap=6 → BLOCK（PIPELINE_EXIT=2），gap=20 → 通过。

**回归修复。** 抽 `_fit_camera` 时把 `stage_camera` 的最后一条返回路径带走了：
不给 `--camera` 预设时函数会返回 `None`，runner 解包报
`TypeError: cannot unpack non-iterable NoneType`。之前的测试都带了 `--camera`，所以没暴露。
现在补回：无冻结机位就走全片包围盒取景。

## v1.1.3 — 用插件自己的后期处理，别自己搭光

**教训先写。** 拆 `blender-lighting` 时我顺手把三点光配方往代码里搬，被拦下：
应该先查这套管线自己有没有现成方案。查完发现 HSR 插件暴露 11 个 operator，我们只用了 6 个，
漏掉的里面就有 `jflhsr.import_post_processing` —— 官方 `HoYoverse - Post Processing` 合成器节点组。

- 三点光是给 PBR 写的，套到 ramp/SDF 的卡通着色上会打架；
- 官方后期处理才是 HSR 观感的正路。

现在 `look.post_processing`（默认 **关**）接进 S5，开启后调用官方 operator。
实测同一帧：平均亮度 0.4945 → 0.5177，4.4% 像素变化（集中在角色）。

另外把 `look.hsr` 暴露出来（`morningstar_hsr_*` 那组明暗/肤色/高光滑杆），默认空 = 全用插件默认。

## v1.1.2 — 修 bug：测量口径统一 + 对齐接线

三处结构性问题，都是"能力写了但没接上"：

**1. 两个测量模块口径打架 —— 删掉假的那个。**
`chainplan` 是纯 Python，没有骨架求值，却输出了一个叫 `root_shift` 的数，被当成"世界位移 124.6 mm"。
实测世界位移只有 30.5 mm（`センター`），脚部 19 mm。现在改名为 `local_root_pos_delta`，
并在文首声明"这不是世界位移"；runner 不再用它报"会瞬移"。

**2. 对齐模块没接线 —— 接到 NLA 烘焙之前。**
`align.py` 写好了却只有独立脚本引用。现在 `chain_nla` 在烘焙前测 A 末 / B 首的世界根位置，
`auto` 判定后直接改 B 的 action（只影响 B 的条带，不可能漏到 A），再烘焙导出。

判定规则也修了：原来用"脚部位移 < 30 mm"当门槛，但交接处两段姿态本来就不同，脚天然差很多
（实测 351 mm），会全判成需要搬。改成看**比例**：根位移 / 脚位移 < 0.30 判为姿态差。

| 样本 | 根位移 | 脚位移 | 比例 | 判定 |
|---|---|---|---|---|
| 原神摇+活着dj | 30.5 mm | 351.5 mm | 9% | none（姿态差） |
| 爱乐之城+和刻晴睡觉 | 1202 mm | 276.8 mm | 4.35 | match（真的换站位） |

**3. 加模块地图。** `mmdpipe/__init__.py` 顶部一张 MODULE MAP：纯 Python / Blender 内 / 打包三圈，
外加三条踩出来的边界（世界位移只能在 Blender 测、导入前必须复位 frame_current、判出框只能看像素）。

## v1.1.1 — 取景检查（衍生自社区技能）

参考 [cc-blender-skill](https://github.com/RobLe3/cc-blender-skill) 的 `blender-cameras` / `animation-quality-gate`
与 [ai-film-skills](https://github.com/62656456/ai-film-skills) 的「起、中、终画框」思路，补上取景这一层：

- **S6 构图质心**：把形变骨投到相机 NDC，量主体横向质心的变化范围；冻结机位不跟拍时提前发现漂移。
- **S8 像素取景门禁（G9）**：在已渲帧上量主体包围盒与质心，判「贴边/出框」与「构图漂移」。

口径是踩出来的：骨点 → 网格包围盒 → 渲染像素，前两者都会误报。

| 口径 | 问题 |
|---|---|
| 骨点 | `つま先ＩＫ.L` 贴地、`つま先.L` 伸出网格，NDC y 到 -0.23，画面里人却是全的 |
| 网格包围盒 | 轴对齐且基于静止姿态，估得更大（-0.38） |
| **渲染像素** | 唯一与观众看到的一致 |

实测（833 帧 NLA 成片）：质心跨度 **0.331** → 触发 G9；最窄边距 0.158（821 帧），未出框。

## v1.1.0 — Blender 扩展 + 多段拼接双路线

### 装成插件

```bash
python build_addon.py
blender --command extension install-file -r user_default -e dist/mmd_pipeline-1.1.0.zip
```

侧栏出现 **MMD Pipeline** 面板，或直接 `bpy.ops.mmd_pipeline.render(pmx=..., vmd=..., out_dir=...)`。
面板与命令行**完全等价**（都调 `runner.run`），库只有工作区一份（`build_addon.py` 复制，不重复维护）。

### 多段拼接两条路

| `--chain-mode` | 实现 | 代价 |
|---|---|---|
| `splice` | 字节拼接，只改帧号 | 4.7 MB / 665 曲线 / 1.8 s |
| `nla` | `use_nla` 分层 → `strip.blend_in` 交叉淡化 → `bpy.ops.nla.bake` → `mmd_tools.export_vmd` | 22 MB / 1722 曲线 / 15 s |

`nla` 全用官方能力，不碰二进制。两个必需配置：下层条带 `HOLD`、上层 `NOTHING`；
要淡化则把上层条带向前延伸 gap 帧并同步 `action_frame_start/end`。

### 修掉一个会平移整条动作的坑

`mmd_tools.ImportVmd` 把动作落在 `scene.frame_current + 1` 起。NLA 拼接结束时残留 `frame_current=453`，
导致后续导入的 action 变成 `[454, 1286]`，前半段全空——渲染出来是站桩。
现在 `S3_motion` 导入前强制 `frame_current = 1`，`chain_nla` 结束时也复位。

## 拼接前置检查（dry-run，只报不改）

```bash
python -m mmdpipe.chainplan a.vmd b.vmd --pmx 模型.pmx --gap 6 [--json 计划.json]
```

输出四块：每段的全轨道占用、骨集差（含具体骨名）、交接姿态差（按 error/warn/info 分级）、根链位移差。

实测（原神摇 + 活着dj）：

```
骨集：并集 259，交集 45，段0 缺 207 根，段1 缺 7 根
交接姿态差：共有骨 45，超阈值 23（左ひじ 95.9°、左腕 88.7°、左手首 88.5°…）
位置差最大：グルーブ 1.557（124.6 mm）
根链位移差：[(-1.557,-0.416,-1.385) → (0,0,0)]
各段根链：[['グルーブ'], ['全ての親','操作中心']]
```

**根链必须按段算。** 用并集会出错：`全ての親` 只在 B 段动，并集视角下 `センター` 就被判成"有动画祖先"，而它其实是 A 段的根。

## 拼接保留全部轨道

以前只搬骨骼段和表情段，相机/灯光/阴影/**IK 开关表**全丢。IK 开关不是假设——`爱乐之城`、`和刻晴睡觉`、`和胡桃睡觉` 都有（各 1 条）。丢掉它，作者特意关掉的腿 IK 会在 IK 常开下解算，腿部姿态直接错。

现在四段都搬，帧号跟随段偏移。零尾段的用例输出**字节完全一致**（不改变已有结果，只补回原本会丢的数据）。

## 补键选项（默认 none，待审批）

`vmd.concat(..., fill="none|hold|rest")`，默认 `none`（不改现有行为）。

| 模式 | 实测 |
|---|---|
| `none` | 基准 |
| `hold` | 与 none 在 f100/f600 **逐骨位置完全一致**（零视觉变化，只是显式化） |
| `rest` | A 段 センター 归零（≈1 cm）；B 段 ひざD.R ≈11 cm、足首D.R ≈10 cm |

结论：补键不改变画面，也不消除跳变——它只是数据卫生。真正影响观感的是交接区混合与根链对齐。

## 一个必须记住的坑

**PMX 里的贴图是相对路径。** 把修好的 PMX 写到别的目录而不搬贴图，渲染会变成整片纯色剪影（实测：全紫）。
`--clearance` 现在会把引用的贴图按相对路径一起复制到 `out/pmx/`，缺失的贴图会报 WARN。

## 已知限制

- 物理求解器跨进程不保证位级一致：残余抖动 ≈ 0.18% 像素（180 帧内为 0）
- `head_capsules()` 仍依赖骨名 `頭/头/head`（带回退：半径最大的胶囊）
- 阻尼施加目标仍按 `裙/下擺/skirt` 匹配，匹配不到会显式警告
- 未做表情 VMD 合并、道具并入、多动作拼接

---

# v1.3.0 — 产物隔离 + state 契约（2026-11-11）

这一版只做两件"收尾"的事：让**失败的运行骗不了人**，让**读不懂的 state 拦得住人**。
主流程一个阶段都没动。

## 产物隔离：`--layout isolated`（新默认）

以前所有产物平铺在 `--out` 根目录：帧序列、`scene.blend`、修过的 PMX、拼接 VMD、
成片、联络表、相机参数、state 全混在一起。后果很具体——**渲到一半失败的 `result.mp4`
和跑通的 `result.mp4` 长得一模一样**，只能翻 state 才知道哪张能交。

现在默认：

```
<out>/
  pipeline_state.json          # 最近一次运行的记录（不跟着 run id 走）
  work/<run_id>/               # 中间产物：frames/、scene.blend、pmx/、vmd/、preflight.json
  final/<run_id>/              # 成片：result.mp4、contact_sheet.png、camera.json、scene.blend、pipeline_state.json
```

- `run_id` 由 `started_at` 生成（`2026-11-11 21:07:30` → `20261111_210730`），同一 `--out` 多次运行不互相覆盖
- **只有全流程 ok 才 promote 到 `final/`**：未通过时 `final/` 里一个文件都不出现
- promote 用**复制**不用移动：work 里留原件，删 work 不影响 final，事后比对帧也不用重跑
- `--layout legacy` 保留旧行为（全写根目录），旧脚本/旧习惯随时切回去

## state 契约：schema 2 → 3，读不懂就拒绝

`pipeline_state.json` 是唯一真相，字段一直在加。旧 state 被新代码读到，
最坏不是报错而是**静默用错语义**。规则落成代码（`mmdpipe/statefile.py`）：

| schema | 动作 |
|---|---|
| 缺 / <2 | **改名归档**为 `pipeline_state.schema0.bak`，不覆盖唯一的历史记录 |
| ==2 | 内存迁移（补 `layout=legacy` / `run_id` / `paths`），提示一行后继续 |
| ==3 | 当前，直接用 |
| >3 | **拒绝运行**（退出码 4）：新字段什么意思不知道，覆盖等于销毁证据 |

`python -m mmdpipe.statefile <state...>` 可以单独体检旧产物，不用开 Blender。

## 证据

- 纯 Python 测试 **27 → 48 条**（新增 `tests/test_layout.py` 11 条、`tests/test_statefile.py` 10 条），全绿
- `_guard_state` 四种动作实测（无 state / schema2 / v1 / 更新版）：4/4 PASS
  —— 用假 `bpy` 拉起 runner 单独测，不渲一帧
- `layout.plan` 路径实测：`isolated` 得到 `work/<id>` 与 `final/<id>`，`legacy` 的 `final` 为空串（不凭空造目录）

## 顺手修掉的

- `mmdpipe.__version__` 停在 `1.1.5`、manifest 写 `1.2.0` —— 两处漂移，统一到 `1.3.0`
- `statefile` 的命令行输出原来用 `✓/✗`，GBK 控制台下 `UnicodeEncodeError`，改成 ASCII 记号

## 已知限制

- `final/` 的 `scene.blend` 是复制不是硬链接：833 帧的一次运行会多占一份体积（实测待补，估计两百 MB 级）
- 没有 `--resume`：隔离后每次都是全新 run，中途失败只能整条重跑（这是现状，不是本版引入）

