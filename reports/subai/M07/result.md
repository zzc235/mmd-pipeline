# M07 · result（attempt 1）

> **更正（2026-11-16 13:19，attempt 2 时发现）**：本文 §2 "E / F" 里写的「隔离安装（`--factory-startup` + 临时 `BLENDER_USER_SCRIPTS`，不动用户全局配置）」**是错的方案** ——
> `BLENDER_USER_SCRIPTS` 不决定扩展目录，实测那两笔安装都写进了 `%APPDATA%\…\user_default\mmd_pipeline` 与 `userpref.blend`。
> 真隔离用 `BLENDER_USER_EXTENSIONS`；D/E/F 的实测数字与这处事故的完整交代见 `result_attempt2.md`。

> 席位 A4 · 分支 `ai/a4` · 基线 `97e40ba` · 2026-11-16
> 状态：**PARTIAL** —— A/B/C 与 D 的代码全部落地并自测；D 的执行、E（隔离安装 + smoke）、F（12 帧 E2E）还没跑，**因为 Blender 锁排在第四位**（2号 穿透 → 1号 S8 → 1号 重采样 → 我）。没跑的不写成通过。

## 1. 四个提交

| commit | 内容 |
|---|---|
| `066d520` | `status.py`（新，纯 Python）+ `operators.py` 改（进度/完成态走状态层；新增 diagnose / gate / open_dir 三个按钮）+ `tests_bpy/test_status.py`（新，18 条） |
| `571483b` | `params.py` 加 `ZONES/ZONE_OF/by_zone()` + `panels.py` 四区面板 + `tests_bpy/test_zones.py`（新，6 条）+ `smoke.py` 新增四项检查 |
| `a5513bf` | `build_addon.py` 重写（校验失败不打包、只认当前版本 zip、SHA256、资产混入拒绝、版本一致性）+ `run_tool.py`（新，包内 CLI 白名单） |
| `fc48f63` | `coordination/gate.py` 覆盖闸门改三点式 + 1 条测试（M00 收尾，不属于 M07 正文，单独一笔） |

## 2. 逐项对任务书

### A 能力盘点（已完成）→ `capability_audit.md`
`operators.py` 1 个 operator、`properties.py` 从 `PARAMS` 动态生成 22 个字段、`panels.py` 单面板平铺 + 高级折叠、`smoke.py` 4 项、`build_addon.py` 3 步。差距表在 §2：四区没分、无诊断/门禁入口、进度读错路径。

### B 布局与状态测试（已完成）
- 新增 `status.py`：按 state 记的 `paths.work` 解析帧目录；legacy 与 schema 2 迁移态退回 `<out>` 根目录；state 缺失/坏 JSON/非 dict 一律不抛异常。
- 旧实现数 `<out>/frames`，而 isolated（**默认布局**）帧在 `<out>/work/<run>/frames` → 进度恒 0%，115 条测试全绿也照样 0。
- `tests_bpy/test_status.py` **18 条**：isolated/legacy/schema2/缺 state/坏 JSON/非 dict/进度夹取/失败原因取 block 级 code+hint/报告区行。

### C 四区面板（已完成，未在 GUI 里人工看）
- `params.ZONE_OF` 唯一决定字段归属：资产 10 / 物理 6 / 渲染 6 = 22，与 `PARAMS` **双向校验**（漏一个 import 就 raise，宁可不装也不让旋钮消失）。
- 面板四个 box：资产 / 物理 / 渲染 / 报告；高级项仍折叠；报告区读 `status.summary()`；三个按钮在缺模块时置灰并写明原因，不点出 Traceback。
- `tests_bpy/test_zones.py` 6 条（纯 Python）：全归区、不重复、顺序随声明、高级项不丢、未知区报错、三个常用旋钮在资产区。
- **未验证**：面板在 GUI 里的实际排版与点击（无头覆盖不到，列人工项）。

### D 构建脚本（代码完成，**执行未做**）
- 校验失败 → 返回 2 且**不产生候选包**；只认 `mmd_pipeline-<version>.zip`；打印 SHA256；暂存目录扫到 `.pmx/.vmd/.blend/.mp4/图片` 直接拒绝；manifest 与 `bl_info` 版本不一致拒绝打包；暂存排除 `__pycache__`。
- 已跑（不开 Blender 的部分）：`read_version()` = 1.3.0；`stage()` = 42 个文件、无 `.pyc`、无资产混入。
- **未做**：`extension validate` / `build`（要 Blender）。

### E / F（未开始）
- E：隔离安装（`--factory-startup` + 临时 `BLENDER_USER_SCRIPTS`，不动用户全局配置）+ bpy smoke。
- F：12 帧 isolated E2E + ffprobe 核对 + 受控失败路径。
- 两项都要锁；按总控定的顺序排在第四位。

## 3. 接口接线口径（只吃 JSON / CLI，不 import 内部函数）

| 接口 | 面板怎么用 | 照死的两条 |
|---|---|---|
| `diagnose/1` | 诊断按钮 → `run_tool.py diagnose --pmx … --out <out>/diagnose/diagnosis.json`；退出码 **0=无 confirmed、1=有 confirmed**（1 也是有效结果，不报错）、2=用法错、3=输入不可读 | 面板只读 JSON；不 import `judge()` |
| `physics_gate/1` | 门禁按钮 → `run_tool.py physics_gate --measurement <out>/measurement.json --profile 包内 presets/physics_gate/exploratory_v0.json --out <out>/gate/gate.json` | **`ERROR` 不是 status 取值**：退出码 2 且不产出 JSON，面板只据此报错；`OUT_OF_SCOPE` 聚合前排除；`UNKNOWN` 单列不装 PASS |
| `chain/...@1` | 报告区暂只显示 state 的 S3_chain metrics；完整 junctions/pose_diff 展示留到 D/F 之后 | `junctions[].pose_diff` 是**完整 45 条**，不是 top-3；`roots` 键恒在 |
| `action_library/manifest@2` | 本轮不接（资产库在 `E:\flowhmr-test`，插件不打包资产） | — |
| `pmx_patch/joint_limit@1` | 本轮不接（属 M01/M02 实验面） | — |

## 4. 测试（A4 树内实跑）

```
python -m unittest discover -s tests     → Ran 228 tests, OK (skipped=15)
python -m unittest tests.test_coordination → Ran 37 tests, OK
python tests_bpy/test_status.py          → Ran 18 tests, OK   （纯 Python）
python tests_bpy/test_zones.py           → Ran 6 tests, OK    （纯 Python）
python -c "import build_addon as b; b.stage()" → 版本 1.3.0 / 42 个文件 / 无 .pyc / 无资产
```

`skipped=15` 是既有 `reports/` 依赖（干净克隆会跳过，设计如此）。

## 5. 已知限制（不许当 PASS）

1. 面板排版、按钮点击、进度条可见性：**只能人工看**，无头覆盖不到；
2. `extension validate/build`、隔离安装、bpy smoke、12 帧 E2E：**未执行**（等锁）；
3. `physics_gate` 的 `penetration` 与 `frozen` 阈值仍是 `exploratory`（M04 自己标的 UNVERIFIED），面板只显示"探索性"，不宣称已标定；
4. `build_addon.py` 的资产混入扫描按后缀，**不查内容**；模型改后缀混入不会被抓；
5. 诊断按钮只跑 `--pmx` 静态归因；带 `--ab` 的双场景比对没接（等有真实 A/B 样本）。

## 6. 下一步

拿锁后按 D → E → F 顺序跑：`build_addon.py`（validate 通过才谈包）→ 隔离安装 + `tests_bpy/smoke.py`（8 项检查）→ 12 帧 isolated E2E + ffprobe + 一次受控失败。
