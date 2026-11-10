# MMD 流水线（mmdpipe / MMD Pipeline 插件）· 交接文档

> 生成时间：2026-11-10 22:20
> 适用目录：`E:/dsh pr/woker2`
> **本仓库没有 git 历史**（`git log` → `not a git repository`）。
> 所以下面每一条改动都标注了**可核对的位置**（文件 + 函数/段），而不是"第几次提交"。
> 数字与结论均取自代码注释、`CHANGELOG.md`、`pipeline_state.json` 和本次运行的实测日志；
> 没有把握的地方会明确写"未验证"。

---

## 0. 这份文档怎么用

- 想**跑起来**：看 §2 环境、§7 命令
- 想**改代码**：先看 §4 架构与决策（每条都有"为什么"和数据），再看 §5 改动清单
- 想**避免重踩**：看 §9 失败记录（42 条，按主题分组）
- 想**知道还差什么**：看 §8 已知限制

---

## 1. 项目定位与边界

**做的一件事**：把「PMX 模型 + VMD 动作 → 带物理的动画成片」稳定复现，并在每一步能失败的地方设断言。

**刻意不做**（避免范围膨胀）：
- GUI 视窗（Blender 内 orbit viewer）
- IK/FK 手动控制层
- 场景美术 / 音乐 / 运镜的自动生成

**安全约定**：源 PMX / VMD 全程只读，任何改动落在 `--out` 的副本上，首尾各算一次 sha256。

---

## 2. 环境与依赖

| 项 | 值 | 验证方式 |
|---|---|---|
| Blender | 5.2.2 LTS（`E:/code/Blender/blender-5.2.2-windows-x64/blender.exe`） | `blender --version` |
| mmd_tools | 4.5.14，扩展 ID `bl_ext.user_default.mmd_tools` | 读 `blender_manifest.toml` |
| HSR 材质插件 | `jinfengling_hsr_addon`（`scripts/addons/`），11 个 `jflhsr.*` operator | 读 `__init__.py` |
| ffmpeg | `C:/Users/zzc/ffmpeg/bin/ffmpeg.exe` | 联络表生成成功 |
| Python（纯逻辑层） | `C:/Users/zzc/.dsh/.../python/python.exe`，**无 pytest**，有 numpy/PIL | `import pytest` 失败 |
| 本插件 | `mmd_pipeline` 1.2.0，安装于 `%APPDATA%/Blender Foundation/Blender/5.2/extensions/user_default/mmd_pipeline` | `--command extension install-file` 返回 Reinstalled |

**扩展的模块名是 `bl_ext.user_default.mmd_pipeline`，不是短名 `mmd_pipeline`。**
用短名 `addon_utils.enable()` 会报 `No module named 'mmd_pipeline'`（实测）。

---

## 3. 目录结构与职责

### 3.1 纯 Python 层（不 import bpy，可单测）

| 文件 | 行数 | 职责 |
|---|---|---|
| `mmdpipe/pmx.py` | 577 | PMX 解析 + 按字节偏移回写（不重新序列化；拒绝覆盖源文件） |
| `mmdpipe/vmd.py` | 424 | VMD 解析（骨骼/表情/相机/灯光/阴影/IK 全轨道）+ `concat` / `merge` |
| `mmdpipe/params.py` | 172 | **参数唯一声明源**（21 字段） |
| `mmdpipe/physics.py` | 330 | 物理资格分类（结构判定，不看名字）+ 物理单元识别 |
| `mmdpipe/clearance.py` | 415 | 初始穿透检测与外移修复 |
| `mmdpipe/chainplan.py` | 353 | 拼接 dry-run（**只有局部量与姿态差，没有世界位移**） |
| `mmdpipe/align.py` | 260 | 对齐 plan 结构 + 判定规则 + 注入（测量在 Blender 侧） |
| `mmdpipe/match.py` | 138 | VMD × PMX 覆盖率体检 |
| `mmdpipe/verify_pmx.py` | 138 | PMX 结构校验 C1–C8 |
| `mmdpipe/preset.py` | 128 | 预设与默认值 |
| `mmdpipe/report.py` | 78 | `StageResult` / `Issue` 契约 |
| `mmdpipe/preflight.py` | 88 | 导入前只读体检 CLI |
| `mmdpipe/concatvmd.py` | 106 | 多动作拼接 CLI |
| `mmdpipe/mergevmd.py` | 83 | 表情合并 CLI |

### 3.2 Blender 层（需要 bpy）

| 文件 | 行数 | 职责 |
|---|---|---|
| `mmdpipe/stage.py` | 1220 | 各阶段：导入/建链/物理策略/动作/外观/道具/相机/渲染/验收 + 取景检查 + 三点光 + 单元阻尼 |
| `mmdpipe/runner.py` | 687 | 编排 S0..S8、state 写入、命令行入口 |
| `mmdpipe/chain_nla.py` | 270 | NLA 路线：分层 → 世界空间对齐 → 淡化 → 烘焙 → 官方导出 |
| `mmdpipe/measure_align.py` | 161 | 独立的世界空间对齐测量脚本 |

### 3.3 插件壳（Blender 扩展）

| 文件 | 行数 | 职责 |
|---|---|---|
| `addon/mmd_pipeline/__init__.py` | 39 | 只做注册（`bl_info` + register 三个模块） |
| `addon/mmd_pipeline/properties.py` | 28 | 从 `params.PARAMS` **动态生成** PropertyGroup |
| `addon/mmd_pipeline/operators.py` | 158 | 子进程 + modal timer：进度、ESC 取消、日志落盘、argv 生成 |
| `addon/mmd_pipeline/panels.py` | 45 | 主参数平铺，`advanced=True` 的进"高级"折叠区 |
| `addon/mmd_pipeline/blender_manifest.toml` | 25 | 扩展清单，`version = "1.2.0"` |

### 3.4 测试

| 文件 | 行数 | 内容 |
|---|---|---|
| `tests/test_params.py` | 71 | 声明源 ↔ argparse 一致性、空格路径、可重复列表 |
| `tests/test_vmd.py` | 100 | 解析、拼接可重复性（sha 一致）、记录数守恒、表情偏移、空格路径 |
| `tests/test_align.py` | 53 | 判定规则 7 条（噪声/姿态差/真位移/边界/朝向/大位移提示 keep/plan 往返） |
| `tests/test_physics.py` | 52 | 卡芙卡两只袖筒识别、宵宫解析、模式匹配、`off` 策略 |
| `tests_bpy/smoke.py` | 88 | 包内导入、参数同源、argv 生成、无预设取景契约 |

### 3.5 其他

| 文件 | 职责 |
|---|---|
| `run_pipeline.py` | Blender 入口（13 行）：`sys.path` + `mmdpipe.runner.main()` |
| `build_addon.py` | 把 `mmdpipe/` + `presets/` + `run_pipeline.py` 复制进暂存目录，调用官方 `--command extension build` |
| `make_report.py` | 生成任务报告与快照到 `桌面/ai用/dsh use/` |
| `AGENTS.md` | **项目工作规则**（先找现成方案再写代码等 5 条） |
| `presets/*.json` | `feiying` / `kafuka_v2_camera` / `kafuka_hsr_look` / `kaf_phys_nodamp` / `xiaogong_hsr` |

---

## 4. 架构与关键决策（每条都有理由和证据）

### 4.1 参数唯一声明源（`mmdpipe/params.py`）

**决定**：21 个参数只在 `PARAMS` 声明一次；`add_arguments(ap)` 生成 CLI，`blender_properties(bpy)` 生成面板 PropertyGroup。

**理由**：之前面板 12 个字段 vs CLI 21 个参数，逐个补齐必然再次漂移。评审原话是"面板追 CLI 是典型的返工陷阱"。

**证据**：面板实测 21 字段，`面板缺: []`（`tests_bpy/smoke.py` 断言）。

### 4.2 插件分层（仿本机 mmd_tools）

**决定**：`__init__` 只注册；`properties/operators/panels` 分开；长任务用**子进程 + modal timer**。

**理由**：`bpy.data` 只能主线程访问，线程方案是死路；而流水线本身已是 CLI，子进程跑它最稳，且 UI 不卡、可 ESC 取消。

**未验证**：进度条与 ESC 取消的 UI 行为需要 GUI 点一次（无头模式验不了 modal 循环）。

### 4.3 多段拼接两条路

| `--chain-mode` | 实现 | 代价（实测） |
|---|---|---|
| `splice` | 字节拼接，只改帧号 | 4.7 MB / 665 曲线 / 导入 1.8 s |
| `nla` | `use_nla` 分层 → 淡化 → `bpy.ops.nla.bake` → 官方 `export_vmd` | 22 MB / 1722 曲线 / 导入 15.0 s |

**理由**：字节层只能搬关键帧，混合与对齐需要"求值后的姿态"。NLA 全部用官方能力，不碰二进制。

### 4.4 世界位移只能在 Blender 里测

**决定**：`chainplan`（纯 Python）只输出 `local_root_pos_delta`，明确标注"不是世界位移"；真正的世界测量在 `chain_nla._measure_and_align`。

**证据**：同一对动作，chainplan 报"124.6 mm"，Blender 实测 `センター` 只有 **30.5 mm**（脚部 19 mm）。

### 4.5 对齐判定用比例，不用绝对阈值

**决定**：`align.decide` 用 `根位移 / 脚位移 < 0.30` 判"姿态差"，而不是"脚位移 < 30 mm"。

**证据**：

| 样本 | 根位移 | 脚位移 | 比例 | 判定 |
|---|---|---|---|---|
| 原神摇+活着dj | 30.5 mm | 351.5 mm | 9% | none |
| 爱乐之城+和刻晴睡觉 | 1202 mm | 276.8 mm | 4.35 | match（真换站位） |

绝对阈值会把所有交接都判成"需要搬"，因为两段姿态本来就不同。

### 4.6 过约束单元默认关物理（袖口翻折的解法）

**决定**：`physics.suspect_units = "static"`（默认）；判据 `刚体≥8 且 闭环≥3 且 焊接比≥0.35 且 无 mode2`。

**证据**（卡芙卡两只袖筒：25 刚体 / 24 闭环 / 焊接比 0.5，配 LaLaLand 高速手臂）：

| 方案 | 袖刚体逐帧最大转角突变 | >45°/帧 | 画面 |
|---|---|---|---|
| 原始 10/20 | 46.8°（f47） | 1 | 甩成硬纸板 |
| 提高求解预算 20/60 | 37.5° | 0 | **仍是硬片** |
| 关组碰撞 | 48.9°（f96） | 1 | 无效（峰值转移） |
| 只加阻尼 | 38.8° | 0 | **仍是硬片** |
| 静音约束 48 条 | — | — | **仍是硬片**（刚体仍在解算） |
| **骨级静态** | — | — | **干净** |

### 4.7 取景检查的口径

**决定**：S6 用形变骨投 NDC 报构图质心；S8 用**渲染像素**判出框与漂移（`G9`）。

**证据**（同一帧）：

| 口径 | 结果 | 问题 |
|---|---|---|
| 骨点 | NDC y = **-0.23** | `つま先ＩＫ.L` 贴地、`つま先.L` 伸出网格 |
| 网格包围盒 | NDC y = **-0.38** | 轴对齐 + 基于静止姿态，估得更大 |
| **渲染像素** | 质心 0.32→0.65 | 与观众看到的一致 |

833 帧实测：质心跨度 **0.331**（触发 G9）、最窄边距 **0.158**（f821）、未出框。

### 4.8 外观路线 `hsr | native | auto`

**决定**：`auto` 先试 HSR 六步，角色材质失败则回退，只丢角色专属的 `MAT/SDF/OUTLINE`，保留场景级 `ENV/LIGHT/REFENV`。

**证据**：宵宫（原神角色）跑 HSR 材质报"星铁适配：未找到对应角色"；HSR 角色库（`character_library.json`）里查不到 宵宫/Yoimiya/原神/Genshin。

### 4.9 帧率口径 30fps

**决定**：默认 `fps = 30`，非 30 时 `S3_motion` 报 WARN 并给两种 fps 的时长对照。

**证据**：833 帧 @30fps = 27.766667 s，@24fps = 34.708333 s（慢 25%）；不重采样只改 fps 等于变速。

---

## 5. 改动清单（按版本，含落点）

> 版本号来自 `CHANGELOG.md`（8 个版本：v1.0.0 → v1.2.0）。
> "落点"给到文件 + 函数；"验证"写实际跑过的命令或测试。

### v1.0.0（基线，2026-11-08）
- 纯 Python 解析 + Blender 阶段编排的初始版本。
- 落点：`mmdpipe/pmx.py`、`vmd.py`、`physics.py`、`clearance.py`、`stage.py`、`runner.py`。

### v1.1.0 — Blender 扩展 + 多段拼接双路线
| 改动 | 落点 | 为什么 |
|---|---|---|
| 扩展包与构建脚本 | `addon/mmd_pipeline/*`、`build_addon.py` | 交付形态要是可安装插件 |
| 字节拼接 | `vmd.concat`、`concatvmd.py` | 同骨架硬切要无损 |
| NLA 路线 | `chain_nla.concat_via_nla` | 需要过渡与对齐时用求值后姿态 |
| 保留全部轨道 | `vmd._parse_tail`、`concat` | 原先丢相机/灯光/阴影/**IK 开关表**；实测 `爱乐之城`/`和刻晴睡觉` 各带 1 条 IK 记录 |
| fps 默认 30 | `preset.py` | VMD 以 30fps 为基准 |
| dry-run 体检 | `chainplan.plan` | 先报后写 |

### v1.1.1 — 取景检查
| 改动 | 落点 | 为什么 |
|---|---|---|
| S6 构图质心 | `stage.check_framing` | 冻结机位不跟拍会漂 |
| G9 像素门禁 | `stage._framing_from_images` | 骨点/包围盒都会误报 |
| `_fit_camera` 抽取 | `stage._fit_camera` | 冻结机位不覆盖时回退 |

### v1.1.2 — 测量口径统一 + 对齐接线
| 改动 | 落点 | 为什么 |
|---|---|---|
| chainplan 改名 | `chainplan.plan` 的 `local_root_pos_delta` | 原 `root_shift` 被当成世界位移（124.6 vs 实际 30.5） |
| runner 不再报"瞬移" | `runner.run` 的 dryrun metrics | 同上 |
| 对齐接线 | `chain_nla._measure_and_align` | `align.py` 写好了但只有独立脚本引用 |
| 比例判定 | `align.decide` | 绝对阈值在交接处失效 |
| 模块地图 | `mmdpipe/__init__.py` | 可读性 |

### v1.1.3 — 官方后期处理
| 改动 | 落点 | 为什么 |
|---|---|---|
| `look.post_processing` | `stage.stage_look` | HSR 插件自带 `jflhsr.import_post_processing`（11 个 operator 里当时只用了 6 个） |
| `look.hsr` 滑杆 | `stage.stage_look`、`HSR_LOOK_KEYS` | `morningstar_hsr_*` 之前从没碰过 |

实测同帧：亮度 0.4945 → 0.5177，4.4% 像素变化。

### v1.1.4 — 确认门 + 回归修复
| 改动 | 落点 | 为什么 |
|---|---|---|
| 过渡确认门 | `runner.run`（`E-16` BLOCK） | 95.9° 压在 7 帧里必须拦，不能只 warn |
| 补回返回路径 | `stage.stage_camera` 末尾 `return _fit_camera(...)` | 抽函数时带走最后一条路径，无 `--camera` 时返回 None |

验证：gap=6 → `PIPELINE_EXIT=2`；gap=20 → 通过。

### v1.1.5 — 联络表
| 改动 | 落点 | 为什么 |
|---|---|---|
| 自动联络表 | `stage.stage_verify` 末尾调用 ffmpeg | 验收先看一张图；**用现成 `tile` 滤镜，零自研代码** |

命令：`ffmpeg -vf "select='not(mod(n\,10))',scale=320:-1,tile=4x3"`，产出 `contact_sheet.png`（12 帧 / 4×3）。

### v1.1.6 — 换模型不再崩
| 改动 | 落点 | 为什么 |
|---|---|---|
| `route = hsr/native/auto` | `stage.stage_look` | `look.route` 原是死配置，`stage_look` 永远走 HSR 六步 |
| native 三点光 | `stage._setup_three_point` | native 场景**一盏灯都没有**，只有 0.6 世界背景 |
| 能量倍率 | `preset.look.light_scale` | 技能公式按 Cycles 算，EEVEE 实测要缩到 0.05 |
| 单元阻尼 | `stage.apply_unit_damping` | 阻尼原来只按 `is_skirt` 名字施加，袖/发/挂件覆盖不到 |

三点光标定（同一帧，主体亮度/过曝）：×1.0 → 0.845/79%；×0.35 → 0.746/59%；×0.10 → 0.586/30%；**×0.05 → 0.475/2.2%**。

### v1.2.0 — 参数声明层 + 测试护栏 + 插件重构
| 改动 | 落点 | 为什么 |
|---|---|---|
| 参数声明源 | `mmdpipe/params.py`（`PARAMS`/`add_arguments`/`blender_properties`） | 面板/CLI/测试/续跑四处各写各的，会一直漂移 |
| runner 去手写 | `runner._parse_args` 改为调 `params.add_arguments` | 同上 |
| 插件分层 | `addon/mmd_pipeline/{properties,operators,panels}.py` | 仿 mmd_tools 的分法 |
| 子进程 + modal | `operators.MMDP_OT_run` | bpy 只能主线程，线程是死路 |
| 可选数值不覆盖预设 | `operators._argv_from` | 面板上 `clearance_margin` 显示 0，会被当成"已设置" |
| state 契约 | `runner.run` 的 `state["schema"]=2` + `env` | 字段还在加，旧 state 必须显式处理 |
| unittest | `tests/*.py`（27 断言） | 这轮三个事故都是人工撞出来的 |
| bpy 冒烟 | `tests_bpy/smoke.py`（4 项） | 扩展包内导入 / 参数同源 / 无预设路径 |

---

## 6. 当前能力

### 6.1 阶段（15 个，实测顺序）

```
S0_env → S1_census → S1_physics → S1_suspect_static → S3_match
→ S2_import → S2_build → S2_damping → S2_policy → S3_motion
→ S5_look → S6_props → S6_camera → S7_render → S8_verify
```
（`S3_chain` 在有 `--motions` 时出现；`S3_expression` 在有 `--expression` 时出现；`S1_declared` 在有 `force_static/physics` 时出现。）

### 6.2 门禁（17 个）

`E-00 E-05 E-07 E-10 E-14 E-15 E-16 E-17 E-21` + `G1 G2 G3 G4 G5 G6 G7 G8 G9`

### 6.3 参数（21 个，`mmdpipe/params.py`）

```
pmx vmd motions expression preset camera out frames fps
physics_policy force_static force_physics probe
chain_mode chain_gap chain_blend align
clearance clearance_margin prop force
```

### 6.4 对外命令

```bash
# 命令行
blender -b -P run_pipeline.py -- --pmx M.pmx --vmd A.vmd --out 输出 --frames 360

# 面板 / 脚本
bpy.ops.mmd_pipeline.run()

# 纯逻辑
python -m mmdpipe.preflight 模型.pmx 动作.vmd --json 报告.json
python -m mmdpipe.chainplan a.vmd b.vmd --pmx 模型.pmx --gap 6
```

---

## 7. 测试与验证

```bash
# 纯 Python 层（27 断言，约 1.5 s）—— 实测 OK
python -m unittest discover -s tests

# bpy 层冒烟（4 项）—— 实测 SMOKE RESULT OK (0 failed)
blender -b -P tests_bpy/smoke.py

# 插件安装
python build_addon.py
blender --command extension install-file -r user_default -e dist/mmd_pipeline-1.2.0.zip
```

---

## 8. 已知限制与未做项

**已验证可用**
- PMX/VMD 解析（卡芙卡 246 骨/145 刚体/14825 顶点；宵宫 324/218/20193）
- 字节拼接可重复（两次 sha 一致）、表情偏移跟随段偏移
- 过约束单元识别（卡芙卡两只袖筒各 25 刚体 / 24 闭环）
- 取景检查、联络表、参数同源、扩展包导入

**已实现但未在本环境验证**
- modal 进度条与 ESC 取消（需要 GUI 实际点一次）

**未做**
- 产物隔离（`work/` 与 `final/` 分开、按 run id 存、清理命令）
- N 段 NLA（现只支持 2 段；第 3 段起只 warn）
- Y 轴旋转注入（`align.py` 里 `NotImplementedError`；两对样本朝向差仅 -0.4°，无需求驱动）
- 错误信息的"下一步动作"链接（目前只给 `blocked_by` + 日志路径）
- state 的旧版本迁移（只写了 `schema: 2`，没有迁移函数）

**已知风险**
- 物理跨进程不可复现（同一 .blend 两次测量包围盒不同），所以相机必须冻结
- Blender IK 与 MMD IK 解算存在差异（mmd_tools README 的 Known Issues），腿脚姿态不完全一致

---

## 9. 失败记录索引

完整条目在 `make_report.py` 的失败记录段与桌面报告里。**共 41 条**（编号到 42，其中 21 缺号）。
下面是逐条真实标题，未做归类：

```
 1. PMX 骨骼 flag 写反
 2. 面段计数字段含义
 3. 材质变形每条多 1 字节
 4. 表示枠条目宽度
 5. 权重索引宽度用错
 6. 单位口径
 7. 胶囊互叠误报
 8. mode0 纯碰撞体误报
 9. "无关节刚体会掉"是假警报
10. `bones_for_policy` 不认 `report`
11. `compare_psnr.py` 格式串参数错位
12. 插件壳留了空引用
13. 贴图相对路径断裂
14. 赛飞儿两只兜帽无法外移
15. 表情合并时目录未建
16. 误判表情没生效
17. 道具对象识别错
18. 骨父级空间里用世界位移
19. 检查脚本选错骨架
20. 拼接后 IK 缺口暴露
22. 多动作拼接只做到字节级，姿态没接上
23. 帧率口径错了（影响所有成片）
24. 根链用并集算
25. 变量名遮蔽
26. 拼接丢全轨道
27. 转义链塌陷写坏源文件
28. 自动选切点无效
29. mmd_tools 导入起点是 scene.frame_current
30. 扩展包里绝对导入失效
31. NLA 两条轨道都设 REPLACE+HOLD
32. G4 在短片段上误报
33. 取景检查口径连错两次
34. 能力写了没接线
35. 两个测量模块给相反结论
36. 对齐判据用绝对阈值
37. refactor 带走返回路径
38. 先写代码后盘点能力
39. `look.route` 是死配置
40. native 路线没有灯
41. 面板/CLI/测试/续跑四处各写各的
42. 扩展包内只能用包内路径
```

其中最容易再犯的三条：
1. **`mmd_tools.import_vmd` 以 `scene.frame_current` 为起点** —— 残留帧位会把整条动作平移（实测变成 `[454,1286]`）
2. **扩展包内只能用包内路径** —— `from mmdpipe import ...` 在 `bl_ext` 包里会失败
3. **判"出框"只能看渲染像素** —— 骨点与网格包围盒都会误报

## 10. 下一步建议（按收益/成本）

1. **GUI 点一次渲染**，确认进度条与 ESC 取消（唯一没自动验的路径）
2. **产物隔离**：`out/work/`（可删中间产物）与 `out/final/`（全流程 ok 才落地），run id 用 `state.started_at`
3. **state 迁移函数**：`schema < 2` 时明确拒绝并给提示，而不是静默续跑
4. N 段 NLA（把两层 strip 泛化成链式排布，相邻对各自报告 junction）
5. 旋转注入（等出现朝向差 > 5° 的样本再做）

---

## 11. 复现一次完整运行

```bash
# 1) 环境自检
blender -b -P run_pipeline.py -- --pmx <model.pmx> --vmd <motion.vmd> --out /tmp/probe --frames 12

# 2) 多段拼接 + 对齐 + 物理
blender -b -P run_pipeline.py -- \
  --pmx  "E:/blender模型/.../卡芙卡3.0.pmx" \
  --motions "A.vmd;B.vmd" \
  --chain-mode nla --chain-gap 20 --chain-blend 20 --align auto \
  --physics-policy strict --clearance \
  --preset presets/kafuka_v2_camera.json \
  --out out/run_$(date +%H%M) --frames 240

# 3) 看结果
#   out/.../result.mp4           成片
#   out/.../contact_sheet.png    12 帧联络表（先看这张）
#   out/.../pipeline_state.json  每阶段 metrics / issues / artifacts
#   out/.../run.log              本次命令行执行日志（插件面板启动时）
```
