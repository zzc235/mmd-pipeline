# M07 · 能力盘点与四区差距表（阶段 A）

> 2026-11-16 · 模块负责4 · 只读盘点 + 本轮已落的改动
> 依据：`addon/mmd_pipeline/` 五个源文件、`mmdpipe/params.py` `layout.py` `statefile.py`、
> `build_addon.py`、`tests_bpy/smoke.py`、`mmdpipe/runner.py`（只读参数/布局/state 段）

## 1. 现有能力（先盘点，不重写）

| 位置 | 能力 | 状态 |
|---|---|---|
| `operators.py` | `mmd_pipeline.run`：子进程 + modal timer 跑 CLI；ESC 终止；日志落 `<out>/run.log` | 在用 |
| `operators.py::_argv_from` | 面板字段 → CLI argv，空格路径保留、list 拆多项、可选数值 0 不覆盖预设 | 在用 |
| `properties.py` | 22 个字段由 `mmdpipe.params.PARAMS` 动态生成 PropertyGroup（面板 = CLI 子集，结构上不可能漂移） | 在用 |
| `panels.py` | 单个面板：15 个主参数平铺 + 7 个高级项折叠 | 在用（未分四区） |
| `blender_manifest.toml` | `version=1.3.0`、`blender_version_min=4.2.0`、files/network 权限声明 | 在用 |
| `build_addon.py` | 暂存（复制 addon + mmdpipe + presets + run_pipeline）→ validate → build | 在用（有缺陷，见 §3） |
| `tests_bpy/smoke.py` | 4 项：包内导入 / 参数同源 / argv / 无预设取景 | 在用 |
| `mmdpipe/layout.py` | isolated（`work/<run>`、`final/<run>`）与 legacy 两种布局的唯一实现 | 复用，不改 |
| `mmdpipe/statefile.py` | schema 2→3 迁移、不可读即拒绝、`summarize()` | 复用，不改 |
| `mmdpipe/report.py` | `StageResult` / `Issue`（code/severity/hint/evidence） | 复用，不改 |

参数面：**22 个**（15 主 + 7 高级），全部来自 `PARAMS`，本轮没有新增字段。

## 2. 四区差距表

| 区 | 已有 | 缺什么 | 依赖 |
|---|---|---|---|
| 资产 | PMX / 单 VMD / 多段 `motions` / 表情 / 预设 / 相机 / 输出目录 / 帧数·帧率 | 面板按区分组；输出目录默认值展示；缺参数时的可读提示 | 无 |
| 物理 | `physics_policy` / `force_static` / `force_physics` / `probe` / `clearance` / `clearance_margin` | 诊断入口（M03 CLI）、门禁结果展示（M04）、UNKNOWN/ERROR 区分 | **M03/M04 接口冻结** |
| 渲染 | `chain_mode` / `chain_gap` / `chain_blend` / `align` + 运行/取消 | 分区归位；对齐与拼接项的联动说明 | 无 |
| 报告 | 结束时报"完成"/"未通过 + blocked_by 阶段名" | 运行状态、退出码、当前阶段、日志/state/联络表路径、block 的 code+hint | 无（本轮已补一半） |

## 3. 实测缺陷（本轮处理）

| # | 缺陷 | 证据 | 处置 |
|---|---|---|---|
| 1 | 进度条数 `<out>/frames`，但 isolated（**默认布局**）把帧放在 `<out>/work/<run>/frames` → 进度恒 0 | `runner.py` L165–175：`out_dir=paths["work"]`、`png_dir=work/frames`；`operators.py::_pct` 旧实现数 `out/frames` | **已修**：新增 `addon/mmd_pipeline/status.py`，按 state 记的 `paths.work` 解析；legacy 与旧 state 退回根目录 |
| 2 | 失败只报阶段名（`blocked_by`），看不到 `E-15` 到底是什么 | `operators.py::_finish` 旧实现 `", ".join(blocked_by)` | **已修**：从 `stages[*].issues` 取 block 级 `code + hint`，warn 不当失败原因 |
| 3 | `build_addon.py` 打包后打印 dist 里**所有** zip（含旧版本），且 validate 失败仍继续 build | 旧 `build()` / `__main__` | **已修**：校验失败返 2 不打包；只认 `mmd_pipeline-<version>.zip`；打印 SHA256；暂存目录扫到 `.pmx/.vmd/.blend/.mp4/图片` 直接拒绝；manifest 与 `bl_info` 版本不一致拒绝打包 |
| 4 | 版本三不一致：源码清单 1.3.0 / 已装副本 1.2.0 / `dist` 只有 1.2.0.zip | 实测 `%APPDATA%\...\mmd_pipeline\blender_manifest.toml` = 1.2.0 | 待阶段 D/E（需 Blender + 安装许可） |
| 5 | 面板未分四区；无诊断/门禁按钮 | `panels.py` 单面板 | 待 C（M03/M04 接口冻结后） |
| 6 | 无 isolated 布局下的状态路径测试 | `tests_bpy/smoke.py` 只有 4 项 | **已补**：`tests_bpy/test_status.py` 14 条 |

## 4. 这次用了哪些现成能力（AGENTS.md 第二条）

| 现成能力 | 用途 | 为什么不自己写 |
|---|---|---|
| `mmdpipe.layout.plan()` 的 `paths` 字典 | 解析 work/final 落点 | 布局规则已在库里有唯一实现，面板侧只需读 state 里记的值 |
| `state["paths"]` / `state["stages"]` / `blocked_by` | 进度、阶段、失败原因的唯一来源 | state 已是整条流水线的真相，另造一套进度文件必然漂移 |
| `bpy.types.Operator` + modal timer（原有） | 运行与取消 | 线程方案会碰 `bpy.data` 主线程限制，原设计正确 |
| `addon_utils.enable` + `bl_ext.user_default.mmd_pipeline` 全名 | smoke 里启用扩展 | 短名 `mmd_pipeline` 在 `bl_ext` 下会 `No module named`（实测过） |
| `shutil.ignore_patterns` | 暂存排除 `__pycache__` | 标准库 |
| Blender 官方 `--command extension validate/build` | 打包与校验 | 不自己写 zip 布局 |

## 5. 本轮改动清单

| 文件 | 性质 |
|---|---|
| `addon/mmd_pipeline/status.py` | 新增，纯 Python（不 import bpy），解析 state → 路径/进度/失败原因 |
| `addon/mmd_pipeline/operators.py` | 改：`_pct` 走 status；`_finish` 报 code+hint；TIMER 一次算一处；删未用的 `json` |
| `build_addon.py` | 改：校验失败不打包、只认当前版本 zip、SHA256、资产混入检查、版本一致性检查 |
| `tests_bpy/test_status.py` | 新增，14 条（纯 Python，可不开 Blender 跑） |

## 6. 未验证项（不许当 PASS）

- `operators.py` 的 modal 进度与 ESC 取消：**只能在 GUI 里看**，无头 Blender 覆盖不到 → 列入人工项。
- 扩展 `validate` / `build` / 隔离安装 / 12 帧 E2E：需 Blender 锁，尚未执行。
- 面板四区与诊断/门禁按钮：等 M03/M04 接口冻结。
