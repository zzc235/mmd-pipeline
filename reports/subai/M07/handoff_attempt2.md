# M07 · handoff → M08（总验收）· attempt 2

> 写给 M08 与 D0 读的交接：M07 现在能主张什么、不能主张什么、M08 要跑什么、有哪些坑已经踩过。

## 1. 现在可以主张的（有实测撑着）

| 断言 | 证据 |
|---|---|
| 包能打出来，且校验失败不产包 | `build_addon.py` exit 0，144742 B / `981ce1a3…`；坏清单 exit 1、零 zip |
| 包内容与 HEAD 逐字节一致 | 42/42 条 `sha256` 相同，`PACKAGE_CONTENT_DIGEST 47288fd5…` |
| 包能装进干净仓库 | `BLENDER_USER_EXTENSIONS=<temp>` + `install-file --no-prefs` → `STATUS Installed`，1.19 s |
| 装完插件自检通过 | `tests_bpy/smoke.py` **8/8 PASS** |
| 包内入口能跑完整流水线 | 装好的包里的 `run_pipeline.py` → 12 帧、9 阶段全 PASS、exit 0、`720×576/30fps/0.4s` |
| 失败路径可信 | 缺 VMD → 进程 exit **1**（修复前恒 0）、不产 `final/`、不产 state |

## 2. 不能主张的（写清楚，别被 D1/D2 的说法带过去）

1. **没在 GUI 里点过**：面板四区排版、按钮置灰、进度条百分比都只有无头证据（`test_status.py`/`test_zones.py`/`smoke.py` 的逻辑层）。M08 若要"人看得见、点得动"，必须人工一次。
2. **本机 `mmd_tools` 未启用** ⇒ 面板"运行"在这台机器上仍会 `S2_import` 失败。E2E 靠 `tests_bpy/run_e2e.py` 脚手架（会话内启用、不写偏好）。启用它是配置变更，需 D0 + Owner。
3. **全局扩展被写了两笔**（`%APPDATA%\…\user_default\mmd_pipeline` = 本次 1.3.0；`userpref.blend` 13:14:26 被 `-e` 写）。处置待批，见 `result_attempt2.md` §3.2。
4. **产物字节不可复现**：同入口两次 PNG 摘要与 mp4 字节都不同。M08 的回归判据必须是判据/帧数/分辨率/时长，不是字节。

## 3. M08 需要最小重跑的一套（约 20 s 锁 + 16 s 纯 Python）

```powershell
python -m unittest discover -s tests -t tests -p "test_*.py"        # 242 passed / 15 skipped
python build_addon.py                                              # 看 SHA256 与体积
blender --factory-startup -b --command extension validate build\mmd_pipeline
$env:BLENDER_USER_EXTENSIONS = "$env:TEMP\m08_ext"; New-Item -ItemType Directory -Force $env:BLENDER_USER_EXTENSIONS
blender --factory-startup -b --command extension install-file -r user_default --no-prefs dist\mmd_pipeline-1.3.0.zip
blender --factory-startup -b -P tests_bpy\smoke.py                  # 8/8
blender -b -P tests_bpy\run_e2e.py -- --pmx <卡芙卡> --vmd <原神摇> --out <新目录> --frames 12 --layout isolated --preset presets\kafuka_hsr_look.json
```

判据（照抄，不要加严也不要放宽）：

- `smoke` 输出 `SMOKE RESULT OK (0 failed)` 且 8 行全 `PASS`；
- E2E `PIPELINE_EXIT=0`、进程 exit 0、`status.py` 显示 `ok True` / `stage S8_verify` / `frames 12`；
- ffprobe `nb_read_frames=12`、`r_frame_rate=30/1`、`duration=0.400000`、`720×576`；
- 受控失败：`--vmd X:\nope\missing.vmd` → 进程 exit **1**，且 `final/`、`pipeline_state.json` 都不存在。

## 4. 踩过的坑（别再踩）

1. **`BLENDER_USER_SCRIPTS` 不隔离扩展目录** —— 用 `BLENDER_USER_EXTENSIONS`；`--factory-startup` 也不拦 `install-file` 写全局。
2. **`-e` 会写 `userpref.blend`**（enable_on_install），要干净就别带 `-e`，再配 `--no-prefs`。
3. **把扩展仓库指到临时目录 ⇒ `mmd_tools` 一起消失**（同一个 `user_default` 仓库），于是 E2E 会以 exit 2 卡在 `S2_import`。F 段的 E2E 必须在"能看到 mmd_tools 的真实 repo"下跑。
4. **`bpy.types` 里没有 operator 类**，判注册要看 `bpy.ops.mmd_pipeline.<op>` 与 `is_registered`。
5. **退出码必须以进程退出码为准**：Blender 里脚本 `print` 完不 `raise SystemExit`，进程照样退 0。
6. **PowerShell 5.1 脚本带中文必须 UTF-8 with BOM**，否则 `ParserError: 字符串缺少终止符`。
7. **12 帧 E2E 只用新建工程**：`out/subai/M02/blend/` 下那批带缓存的老 `.blend` 是另一套东西（两具骨架 / 540 mesh / 324 刚体），拿它当 E2E 输入会同时测两件事。

## 5. 接口面（本轮没改契约，只复用）

`diagnose/1`（exit 0 无 confirmed、1 有、2 用法、3 输入）、`physics_gate/1`（`PASS=0/FAIL=1/ERROR=2 无 JSON/UNKNOWN=3`、`OUT_OF_SCOPE` 聚合前排除）、`chain/*@1`（`junctions[].pose_diff` 全 45 条、`roots` 恒在）、`action_library/manifest@2`、`pmx_patch/joint_limit@1`。面板只吃 JSON/退出码，不 import 内部函数。
