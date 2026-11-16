# M07 · result（attempt 2）：D / E / F 三段跑完，修掉两条产品路径缺陷，报一处环境越界

> 席位 A4 · 分支 `ai/a4` · HEAD `d059a7f` · 基线 = 生成证据时的 main 尖端 `35b31b87`（写报告的过程中 main 从 `4d033e4a` 前进到它；三点式差集恒为 5 文件）· 2026-11-16 13:19
>
> **状态：PASS（D/E/F 全绿）**。两件必须由 D0 / Owner 定的事：① 全局扩展目录与 `userpref.blend` 被我写了两笔（§3.3）；② 本机 `mmd_tools` 仍未启用，产品路径的"运行"按钮在这台机器上会卡在 `S2_import`（§4.4）。

## 0. 三条结论先行

1. **D**：`extension validate` 通过（`Success parsing TOML`）+ 打包出 **144742 B** 的 `mmd_pipeline-1.3.0.zip`（`sha256 981ce1a3…`）；拒绝例（清单 TOML 未闭合引号）exit **1**、零产物。
2. **E**：**真隔离**安装（`BLENDER_USER_EXTENSIONS` 指到临时目录）+ bpy smoke **8/8 PASS**；全局目录与 `userpref.blend` 的时间戳/哈希**事后不变**（这是本轮的漏子修完之后的证据，见 §3）。
3. **F**：12 帧 E2E 用**装进临时仓库的那份包**里的 `run_pipeline.py` 跑通 —— exit **0**、12 帧、`720×576 / 30fps / 0.4 s`、9 个阶段全 `[PASS]`；受控失败（缺 VMD）exit **1** 且**不产** `final/` 与 `pipeline_state.json`。

## 1. 修掉的两条真缺陷（都是产品路径，不是测试问题）

| # | 缺陷 | 为什么是产品路径 | 修复与证据 |
|---|---|---|---|
| 1 | `run_pipeline.py` 打印 `PIPELINE_EXIT=n` 却没有 `raise SystemExit(n)`，**Blender 进程恒以 0 退出** | `build_addon.py` L67 把 `run_pipeline.py` 一起打进包，`operators.py` L16 的 `PIPELINE` 指向的就是**包内这份副本**，`_finish()` 用 `self._proc.returncode` 判成败 ⇒ **BLOCK 会被面板显示成"完成"**，CI/批处理同理 | 加 `raise SystemExit(code)`；实测缺 VMD 时：修复前日志 `PIPELINE_EXIT=1` 而进程 **0**，修复后 `FAIL_EXIT=1`、`final/` 与 state 都不生成 |
| 2 | `tests_bpy/smoke.py` 用 `hasattr(bpy.types, "MMDP_OT_*")` 判注册 | Blender **不把 operator 类挂到 `bpy.types`**（实测 `dir(bpy.types)` 里只有 `MMDP_PT_main`）⇒ 注册成功也判失败，这条测试会永久红 | 改判 `bpy.ops.mmd_pipeline.<op>` 存在 + `CLASSES` 每个类 `is_registered`；隔离安装后 **8/8 PASS** |

## 2. D 段：validate + build（数字都在最终源码上重跑）

| 步骤 | 命令 | exit | 关键输出 | 耗时 |
|---|---|---:|---|---:|
| 打包 | `python build_addon.py` | 0 | `Success parsing TOML` / `暂存 42 个文件` / `created …/mmd_pipeline-1.3.0.zip, 144742` / `SHA256 981ce1a38229ab2878bb087c9e7b6c9f8aa1700ce5b0d09fb8f501f3d5a7d21f` | **2.24 s** |
| 拒绝例 | `blender -b --command extension validate <坏清单副本>` | **1** | `Error parsing TOML` / `Invalid statement (at line 1, column 1)` | 0.99 s |
| 拒绝例产物 | 同上 | — | 目录里 `*.zip` 数量 **0**（校验失败不产候选包） | — |

**包内容 == HEAD**：42 个条目逐一与工作树比 `sha256`，**42/42 相同**；把它们按 `名字+内容哈希` 折成 `PACKAGE_CONTENT_DIGEST = 47288fd51fb9154d2b64d78300322d8250f6c309786c277e8ea01abaeb28a883`。

**一个必须记下来的时序事实**：13:08 第一次打出的包是 **144495 B / `1a6d6f80…`**，那是**退出码修复之前**的源码；13:14 在 HEAD 上重打才得到 144742 B / `981ce1a3…`。E/F 全部用后者。**只改测试文件或入口脚本也会改变包体积**，所以"包哈希对不上"先看源码有没有漂。

## 3. E 段：我先"以为"隔离了，实测**没有**——这条按事故写

### 3.1 attempt 1 里写的做法不成立

`attempt 1` 的计划写的是「`--factory-startup` + 临时 `BLENDER_USER_SCRIPTS`，不动用户全局配置」。**实测这是错的**：`BLENDER_USER_SCRIPTS` 不决定扩展目录，`--command extension install-file -r user_default` 仍然装进 **`%APPDATA%\Blender Foundation\Blender\5.2\extensions\user_default\`**。

### 3.2 已经发生在你机器上的两笔写入（如实报）

| 时间 | 动作 | 后果 |
|---|---|---|
| 13:09:52 | `install-file -r user_default -e <zip>` + `BLENDER_USER_SCRIPTS=临时` | 装进**全局** `user_default\mmd_pipeline`（`STATUS Reinstalled` ⇒ 那之前这里已有一份）；`-e` = 装完即启用 ⇒ Blender **写 `userpref.blend`** |
| 13:14:26 | 同上（新包） | 全局那份被覆盖成本次 **1.3.0 / 981ce1a3** 包；`userpref.blend` 再写一次（mtime `13:14:26`） |

现在这台机器的状态（只读核对，未再改动）：

- `%APPDATA%\…\user_default\mmd_pipeline` = 本次 1.3.0 包，`run_pipeline.py` = `973c531a…`（含退出码修复）；
- `userpref.blend` 里 `bl_ext.user_default.mmd_pipeline` 出现 **1 次**（启用列表），`mmd_tools` **0 次**（仍未启用）。

**这是对"全局安装要 D0 + Owner 双批"那条的越界，我认。** 三个选项我不替你选：
**(a) 保留**（就是本次 1.3.0 包，M08 反正要装最终版；我倾向这个）、**(b) `--command extension remove mmd_pipeline` 卸掉**、**(c) 回退到 `E:\dsh pr\woker2\dist\mmd_pipeline-1.2.0.zip`**（11-10 那份）。默认 (a)，你不说话我就不动。

### 3.3 真隔离的做法（已实测，可复制）

```powershell
$env:BLENDER_USER_EXTENSIONS = "$env:TEMP\m07_ext"          # 扩展仓库根，不是 SCRIPTS
blender --factory-startup -b --command extension install-file -r user_default --no-prefs <zip>
blender --factory-startup -b -P tests_bpy/smoke.py          # 同一环境变量下跑
```

- 探针实测 `bpy.utils.user_resource('EXTENSIONS')` 就返回这个临时目录（`EXT_RESOURCE …\m07_ext`）；
- `--no-prefs` 且**不带** `-e`：安装后 `userpref.blend` mtime 与全局目录 `run_pipeline.py` 哈希**都没变**（13:15:43 与 13:17:46 两次窗口各验一遍）；
- 首次装 `STATUS Installed "mmd_pipeline"`、**1.19 s**；`smoke` **8/8 PASS**、1.17 s。

## 4. F 段：12 帧 E2E（新建工程：卡芙卡 + `原神摇.vmd` + 冻结机位）

### 4.1 前置坑：`mmd_tools` 装了没启用

扩展已在位但**未启用**，它的 `wheels/opencc*.whl` 只在启用时解包 ⇒ 直接 import 报 `No module named 'opencc'` ⇒ `bpy.ops.mmd_tools.import_model` 不存在 ⇒ `S2_import` 失败。会话内 `addon_utils.enable(..., default_set=False, persistent=False)` 之后导入与 operator 都正常（**不写偏好**）。

所以把脚手架 `tests_bpy/run_e2e.py` 落进仓库（本轮新增的唯一文件）：先启用 mmd_tools，再把参数交给 `mmdpipe.runner.main()`，退出码与 `run_pipeline.py` 一致。实测打印 `E2E_SCAFFOLD mmd_tools 已在本会话启用（不写偏好），import_model=True`。

### 4.2 两次 E2E 都全绿

| 入口 | 时间 | exit | 耗时 | 阶段 |
|---|---|---:|---:|---|
| 仓库脚手架 `tests_bpy/run_e2e.py` | 13:16:56 | **0** | 16.51 s | 15 项全 `[PASS]`（`S2_import 1.5s`、`S7_render 6.5s`、`S8_verify 1.3s`） |
| **包内** `…\m07_repo_e\user_default\mmd_pipeline\run_pipeline.py` | 13:18:30 | **0** | 16.10 s | 15 项全 `[PASS]`（`S2_import 1.6s`、`S7_render 6.2s`、`S8_verify 1.4s`） |

产物（两次一致）：`ok True` / `stage S8_verify` / `blocked_by []` / `frames 12` / **PNG 12 帧** / mp4 `720×576`、`r_frame_rate 30/1`、`duration 0.400000`、`nb_read_frames 12`。

源数据只读：PMX `287a5556…`、VMD `a2e5f978…`（首尾一致，没写回）。

### 4.3 受控失败（两个入口各一次）

缺 VMD：`读不到输入文件：[Errno 2] … 'X:\nope\missing.vmd'` → `PIPELINE_EXIT=1`、**进程退出码 1**、`final/` 不存在、`pipeline_state.json` 不存在。修复前这一格是"日志 1 / 进程 0"。

### 4.4 反直觉发现：E 的隔离会让 `mmd_tools` 消失

把 `BLENDER_USER_EXTENSIONS` 指到临时仓库后，`user_default` 仓库里**只有** mmd_pipeline（临时目录是空的），于是 `bl_ext.user_default.mmd_tools` 不存在、`addon_utils.enable` 静默失败，包内入口 E2E 在 13:17:49 **exit 2 / `S2_import` 失败 / 0 帧 / 无 mp4**。

⇒ **E（扩展仓库隔离）与 F（需要真实 repo 里的 mmd_tools）在同一个 repo 里不可兼得。** 所以 F 是在"能看到 mmd_tools 的真实 repo"下跑的（13:18:28），代价是这轮 F 不能用临时仓库遮住用户扩展——但**没有写偏好**（`userpref.blend` mtime 全程 `13:14:26` 未变）。

### 4.5 产物字节不可复现（M08 必须知道）

同一个入口跑两次：PNG 清单摘要 `f05f2d94…` vs `2a8dbff6…`，mp4 **27600 B vs 27675 B**。渲染有随机成分（采样/时间抖动）。

⇒ **回归判据不能是"产物字节"**，只能是：阶段序列与 `[PASS]` 集合、帧数 12、`720×576`、`30/1`、`0.4 s`、以及 `S8_verify` 的判据结论。

## 5. 验证（全部在最终 HEAD `d059a7f` 上量的）

| cmd | exit | passed | failed | skipped | 耗时 |
|---|---:|---:|---:|---:|---:|
| `python -m unittest discover -s tests -t tests -p "test_*.py"` | 0 | **242** | 0 | 15 | 16.37 s |
| `python build_addon.py`（内含 validate） | 0 | — | — | — | 2.24 s |
| `blender -b --command extension validate <坏清单>` | 1 | — | — | — | 0.99 s |
| `blender --factory-startup -b --command extension install-file … --no-prefs <zip>` | 0 | — | — | — | 1.19 s |
| `blender --factory-startup -b -P tests_bpy/smoke.py` | 0 | 8 | 0 | 0 | 1.17 s |
| `blender -b -P <包内>/run_pipeline.py -- … --frames 12` | 0 | — | — | — | 16.10 s |
| 受控失败（缺 VMD，两个入口） | 1 | — | — | — | <1 s |

锁（`out/subai/locks/blender.lock`，每次取到就跑、跑完即放，全部自持自放）：13:14:08→13:14:10（2.5 s，D 重打包）、13:14:25→13:14:28（2.6 s，E 首次）、13:15:43→13:15:47（3.6 s，E 真隔离）、13:16:06→13:16:08（1.3 s，D 拒绝例）、13:16:54→13:17:12（17.8 s，F 仓库入口 + 受控失败）、13:17:46→13:17:51（4.8 s，E+F 连跑，F 因 §4.4 失败）、13:18:28→13:18:45（16.6 s，F 包内入口）。**合计约 49 s。**

## 6. 已知限制（不许当 PASS）

1. **面板 GUI 的排版、按钮可点性、进度条可见性仍只能人工看**，无头覆盖不到；
2. **全局扩展那两笔写入（§3.2）未回退**，等 D0/Owner；
3. **本机 `mmd_tools` 未启用** ⇒ 产品路径（面板"运行"）在这台机器上仍会 `S2_import` 失败；启用它是配置变更，需 D0 + Owner；E2E 目前靠 `tests_bpy/run_e2e.py` 脚手架；
4. 产物字节不可复现（§4.5），回归只能比判据；
5. `physics_gate` 的 `penetration`/`frozen` 阈值仍是 `exploratory`（M04 自标 UNVERIFIED），面板只显示"探索性"；
6. 资产混入扫描只按后缀，不查内容；
7. 单场景、单机位、单动作、12 帧，不外推到长片。

## 7. 交给 M08 的三条

1. **D1/D2 现在可以主张**：包能装（隔离仓库 exit 0）、能跑（12 帧全 PASS、包内入口 exit 0）、失败有非 0 退出码且不产产物。
2. **回归基准用判据不用字节**（§4.5）。
3. **"全局安装"仍是单独待批项**：M08 若要在"用户真装（GUI 里看得见、点得动）"上验收，得先批 §3.2 的处置与 `mmd_tools` 启用。
