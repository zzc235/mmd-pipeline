# 任务报告 · 2026-11-02 · 事故复盘：桌面端崩溃 + 弹窗根治

- **任务编号**：`2026-11-02-incident-silent-run`
- **发起人**：zzc（“它这个窗口老是跳出来，能不能后台静默运行” → “开始自检，刚刚怎么出现崩溃了”）
- **执行**：芙宁娜（dsh 桌面端 0.2.1-rc.3）
- **时间窗**：2026-11-02 12:30 → 12:52（Asia/Shanghai）
- **结论**：弹窗根因已根治（重复启动）；**桌面端崩溃是我按 PID 误杀子进程导致，已恢复**；实例恢复为静默后台运行。

---

## 0. 一页摘要

| 项 | 结果 |
|---|---|
| 弹窗根因 | 旧自愈脚本**没有进程存在保护**：API 短暂抖动 → 再拉一个实例 → 撞锁 → 弹窗报错退出 |
| 崩溃根因 | **本神按 PID 直接杀了两个 `DeepSeek Harness.exe`**，其中包含桌面端自身的子进程 → 桌面端崩溃并自动重启（12:43） |
| 次生问题 | 第一版 `ensure-superagent.ps1` 含中文注释，PowerShell 5.1 按 ANSI 解析**语法报错**，导致那段时间自愈失效 |
| 修复 | 脚本改 ASCII-only + 加进程守护 + 计划任务改走 `wscript` 隐藏 + 新增一键恢复脚本 |
| 验证 | 服务全 ready；实例窗口 `visible=False`；任务幂等（`already running; nothing to do`） |

---

## 1. 事故时间线

| 时间 | 事件 |
|---|---|
| 12:30 | 用户报告“窗口老是跳出来” |
| 12:31 | 本神改写 `ensure-superagent.ps1`（含中文注释）+ 注册 VBS 隐藏任务 |
| 12:33~12:35 | 为测试静默启动，`Stop-Process -Id 4508 / 15672` —— **这两个是桌面端进程树里的进程，不是 superagent 实例** |
| 12:43 | 桌面端崩溃后自动重启（新主进程 30676），用户看到“无法使用/崩溃” |
| 12:44 | 发现第一版 ensure 脚本解析失败（`Unexpected token '}'`），自愈实际从未生效 |
| 12:45 | 清理过期锁 → 实例能启动但 API 不响应（多实例混战） |
| 12:48 | 新增 `recover-superagent.ps1`：清进程 → 等锁过期 → 单实例启动 |
| 12:49 | 恢复成功（api_ok=True） |
| 12:50 | 幂等验证通过：再次触发任务不产生新实例，窗口保持隐藏 |

---

## 2. 三个根因与修法

### 2.1 弹窗：重复启动（已修）
旧 ensure 只探 API：API 在“内部重启/settings 保存”时会短暂不可达 → 脚本误判为挂了 → 再拉一个实例 → 第二个实例抢锁失败 → **Electron 弹出带报错的窗口**再退出。

修法：
```powershell
# 先看进程：只要存在 profile superagent 的进程，就直接退出
$procs = @(Get-CimInstance Win32_Process -Filter "Name='DeepSeek Harness.exe'" |
  Where-Object { $_.CommandLine -match 'profile superagent' })
if ($procs.Count -gt 0) { Write-Log 'already running; nothing to do'; exit 0 }
```
日志证据：`12:50:31 instance already running (pids: 29000,23856); nothing to do`

### 2.2 崩溃：按 PID 误杀（我的责任）
桌面端的 GPU/utility/renderer 子进程**也叫 `DeepSeek Harness.exe`**。本神为了停掉 superagent 实例，直接 `Stop-Process -Id` 杀了两个 PID，其中命中了桌面端进程树 → 桌面端崩了。

**今后铁律**：停实例只按命令行匹配 `profile superagent`，永不按裸 PID。

### 2.3 自愈失效：脚本编码
第一版脚本用了中文注释。PowerShell 5.1 会把**无 BOM 的 UTF-8 当 ANSI 解析**，导致语法错误；而任务用隐藏方式跑，错误不可见，表现为“任务成功但什么都没做”。

修法：脚本全文 **ASCII-only**（这条教训之前就记过，本次复发，已写进报告固化）。

---

## 3. 修改清单

| 文件 | 改动 |
|---|---|
| `E:\dsh-state\ensure-superagent.ps1` | 重写：ASCII-only + 进程守护 + API 探测 + 60s 窗口隐藏循环 + 日志 |
| `E:\dsh-state\run-hidden.vbs` | 新增：`wscript` 隐藏运行 PS 脚本，避免闪黑框 |
| `E:\dsh-state\recover-superagent.ps1` | 新增：一键恢复（清进程→清锁→单实例启动→验证） |
| 计划任务 `DSH Superagent` / `DSH Superagent Watchdog` | 动作改为 `wscript.exe //B //Nologo run-hidden.vbs` |
| `E:\dsh-state\ensure.log` / `recover.log` | 新增运行日志，便于事后取证 |

---

## 4. 验证结果（12:52）

```
health = runtime:ready, models:ready, github:ready, feishu:ready,
         relay/notice/launch/delivery/assessment/reply/evals/history 全 ready
setup.problem = null
sources: feishu ready / github ready
实例窗口: pid=29000 visible=False, pid=23856 visible=False   ← 静默
任务幂等: LastTaskResult=0, ensure.log="already running; nothing to do"
桌面端 GUI: 进程 30676, 窗口标题正常（已自动重启恢复）
```

---

## 5. 待用户确认

1. 桌面端界面是否已恢复正常？（进程已自愈重启，但界面状态需要你目视确认；若异常，重启一次桌面端即可）
2. 观察 10 分钟，确认弹窗是否彻底消失。

## 6. 教训（固化）

1. **杀进程只按命令行匹配**，绝不按裸 PID；`DeepSeek Harness.exe` 可能是桌面端子进程。
2. **PS 5.1 脚本一律 ASCII-only**（无 BOM UTF-8 会被当 ANSI）。
3. **改启动器/计划任务后必须实测**：看日志、看进程数、看窗口可见性，不能只看任务“成功”。
