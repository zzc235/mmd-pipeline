# S6 Blender build / 隔离安装 / smoke 执行回执

## 结论

STATE=PASS（S6 build、隔离 install、9 项 smoke 全过；全局配置零变化；生产仍未放行）

- 执行者：zzc（Human 自己敲命令）
- 工作树：`E:\code\mmdpipe-ai\A4`（branch `ai/a4`，clean，HEAD `6520b1a5186cae325926c690193a9da818a2cecf`）
- Blender：`E:\code\Blender\blender-5.2.2-windows-x64\blender.exe`，Blender 5.2.2 LTS（hash `d13f752e3b9c`，built 2026-09-15 01:37:04）
- 授权：用户 2026-11-18 13:14「推进，我同意了」+ 13:17 选路 A（改 smoke 脚手架）+ 给 blender 路径；写进本报告留证。
- 终端：PowerShell

---

## 0. 【重点】全局配置基线的变更（本次执行的关键决策）

本轮 S6 的"全局零变化"判据**不能用最初抓取的基线**，原因是执行前发现基线本身漂移，已确认与 S6 无关。段必须重点记录，否则后续复核会误判。

### 0.1 事件经过

| 时点 | 全局扩展目录文件数 | userpref sha | 说明 |
|---|---:|---|---|
| 最初基线（13:46 抓取，`s6_global_baseline.json`） | 365 | fc5bda34… | 含 `extensions/.local/lib/python3.13/site-packages/opencc/` 39 个文件 |
| build 后对账（13:47） | 329 | fc5bda34… | opencc/ 整目录 39 文件消失，`compat.dat` hash/mtime 变化，共 37 处差异 |
| 确认稳定（间隔 3 秒两次快照） | 329 | fc5bda34… | A/B 快照零差异，变化已停止 |

### 0.2 原因判定（用户确认）

- 用户明确：`blender-mcp.exe` 是**其他 agent 之前在用的**，用户"打开任务的时候重新启动了 MCP"。
- `opencc/` 清理发生在取基线之后、build 前后，是 **blender-mcp 重启时触发的 Blender 扩展依赖缓存清理**，与 S6 的 build/install/smoke 无关。
- 证据：build_addon.py 是纯 Python 打包，不触碰全局扩展；userpref 全程 sha 未变；变化一次性稳定，非持续写入。
- 探针阶段（隔离 install + 两次 blender 启动）与正式 S6 阶段，相对新基线均零变化（见 §3、§4）。

### 0.3 结论与采用值

- **旧基线 365 文件作废**（它的漂移非 S6 造成，不能拿来给 S6 判罪）。
- **正式基线 = 329 文件**，抓取于 13:52，存 `C:\Users\zzc\AppData\Local\Temp\s6_baseline_final.json`，userpref sha `fc5bda34cdecadd42f794a0f52670c8fbe1a901430263809956802c7c384028e`。
- S6 全部步骤的"全局零变化"判据，均以这份 **329 文件新基线**为准。
- 后续若再看到 opencc/ 不存在，属已知环境状态，不是 S6 副作用。

---

## 1. 前置

- smoke 偏好副作用已按手册 §9.2 路 A 处理：`tests_bpy/smoke.py` 的 `addon_utils.enable(FULL, default_set=False, persistent=False)`（提交 `6520b1a`），代码层 `persistent=True` 清零，9 项 check 未变，全量 960 OK。
- lock status：空闲；全程 `coordination.lock guard`，`--owner "模块负责4|A4"`，不带 `--allow-dirty`、不带 `-e`。
- blender.exe 绝对路径由用户提供（不在 PATH）。

### 隔离加载探针（正式执行前）

担心隔离目录刚装的扩展 smoke 里加载不到，先在**另一个**临时目录探针验证：

- `PROBE_ENABLE OK` / `PROBE_IMPORT OK`（路径指向隔离目录）/ `PROBE_STAGE OK`
- 探针全程全局零变化（329 文件、userpref 未变）
- 结论：`FULL = "bl_ext.user_default.mmd_pipeline"` 与隔离目录 `user_default/mmd_pipeline` 对得上，可进正式执行。

## 2. 执行与结果

### 2.1 build（lock guard 内）

| 判据 | 结果 |
|---|---|
| build_addon.py validate | ✓ rc=0 |
| 产物 | `dist/mmd_pipeline-1.3.0.zip`，200922 B |
| SHA256 | `1b8611a6502c238e381b502187e38cd7bae3528e873ac9f10d584edd58563c22` |
| 包内容 | 46 文件，零 PMX/VMD/BLEND/MP4/图片 |
| lock_lost | none |

### 2.2 隔离 install（lock guard 内）

- 隔离目录：`C:\Users\zzc\AppData\Local\Temp\mmd_ext_s6_20261118_135446`（新建，不删旧目录）
- `BLENDER_USER_EXTENSIONS=$ext`，`--factory-startup -b --command extension install-file -r user_default --no-prefs dist\mmd_pipeline-1.3.0.zip`
- 结果：`STATUS Installed "mmd_pipeline"`
- 未用 `-e`；未用 `BLENDER_USER_SCRIPTS`；`--factory-startup` 只是辅助，隔离靠 `BLENDER_USER_EXTENSIONS`

### 2.3 smoke（lock guard 内，同一隔离目录）

```
SMOKE START
PASS 包内导入
PASS 参数同源
PASS 插件启用闸门
PASS argv 生成
PASS 四区分区
PASS 面板与按钮注册
PASS 报告区状态层
PASS 工具入口白名单
PASS 无预设取景
SMOKE RESULT OK (0 failed)
GUARD_DONE rc=0 heartbeats=0 lock_lost=none
```

三行 `Add-on not loaded: "bl_ext.user_default.mmd_tools" / "mmd_tools" / "definitely_missing_addon"` 是 `t_addon_gate` 故意喂不存在插件的**预期输出**（用例②明确构造 `definitely_missing_addon`），不是失败；最终判据是 `SMOKE RESULT OK (0 failed)`。

## 3. 六条判据核对

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 9 项全 PASS | 9/9 PASS | ✓ |
| 2 | SMOKE RESULT OK (0 failed) | 是 | ✓ |
| 3 | exit 0 | GUARD_DONE rc=0 | ✓ |
| 4 | lock_lost 为空 | none | ✓ |
| 5 | 全局配置零变化（vs 329 新基线） | 329/329，changed=0，userpref fc5bda34… 未变 | ✓ |
| 6 | lock 释放、无残留 Blender | lock status 空闲；仅 blender-mcp.exe 常驻（非本轮） | ✓ |

## 4. 边界（照抄执行约束 §7 + 手册 §9，不省）

1. 全程 lock guard；锁被持有/残缺/不可读即停；不 release/reclaim 别人的锁。
2. 即使 board resource=none 也不无锁启动 Blender。
3. 不用 `-e` 安装；`BLENDER_USER_SCRIPTS` 不是扩展隔离；`--factory-startup` 单独不能保证隔离。
4. smoke.py 的 `persistent=True` 已改（路 A），未对全局环境写偏好。
5. 全局 userpref/扩展目录前后 hash/mtime 不变（以 §0 的 329 新基线为准）。
6. build 只认当前版本 zip（1.3.0），不拿 dist 旧包冒充；包内无资产。
7. smoke 在无头环境跑，**不证明 GUI 排版、点击、进度条、ESC**。
8. 生产未放行；S6 通过不替代 S7；进 S7 需 PMX/VMD 由 Human/owner 提供并单独授权。

## 5. 不能主张

- 未跑 12 帧 E2E（S7）；未启动真实生产；未 claim/start 真实任务。
- 未验证 GUI 层（无头 smoke 的固有边界）。
- 未修改任何生产代码、参数、board、main；本轮唯一代码改动是 S6 前的 smoke.py 修复（已在提交 6520b1a，属上一阶段）。
- 旧基线 365 文件不作废于"数据丢失"意义——opencc/ 删除是 blender-mcp 重启清理的环境态，非本轮产物删除。

## 6. 下一步

S6 封口。S7（12 帧 E2E）需 Human 明确授权，且输入 PMX/VMD 由 Human/owner 提供、输入前后 SHA 相同、新 run_id、全程 lock guard、脚手架只在会话内启用 mmd_tools。不自行进入。
