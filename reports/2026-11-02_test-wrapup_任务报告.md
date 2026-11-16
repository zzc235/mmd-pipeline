# 任务报告 · 2026-11-02 · 测试收官：关闭花销点 + 飞书通道确认打通

- **任务编号**：`2026-11-02-test-wrapup`
- **发起人**：zzc（“先关掉吧，测试任务已经完成了”）
- **执行**：芙宁娜（dsh 桌面端 0.2.1-rc.3）
- **时间窗**：2026-11-02 09:10 → 09:20（Asia/Shanghai）
- **结论**：两处花销点已关（`observeIssues` 关、每小时提醒删）；**飞书通道被证实端到端打通**（飞书请求 → Ticket `14a0bec5` → Worker → **PR #5 已合并**）。

---

## 0. 一页摘要

| 项 | 结果 |
|---|---|
| GitHub `observeIssues` | ✅ 已关闭（revision 3，`false`） |
| 每小时 Watchdog 提醒 | ✅ 已删除（`schedule_list` 现在为空） |
| 飞书端到端 | ✅ **实证**：飞书消息 → accept → Ticket `14a0bec5` → PR #5 → **MERGED** |
| 待机消耗 | ✅ 归零（两个 Source 只轮询/长连接，不调模型） |
| 自启/自愈任务 | 保留（登录自启 + 每 10 分钟自愈） |

---

## 1. 关闭的两个花销点

### 1.1 `observeIssues` → false
```json
PUT /orchestrator/api/settings/source:github
{ "value": { "enabled": true,
             "config": { "repository": "zzc235/superagent-playground",
                         "cli": "C:\\Program Files\\GitHub CLI\\gh.exe",
                         "observeIssues": false } },
  "revision": 2 }
→ 200 {"saved":true,"revision":3}
```
效果：仓库里**没有 @fishuser-sys 的新 Issue 不再被拉进来评估**；@ 了它的仍走通知通道触发。

### 1.2 删除每小时 Watchdog 提醒
- 删除 `schedule-9d7e874f-acd4-4676-be53-de48a827c1ed`
- 复核 `schedule_list` → `[]`
- 真实自愈仍由两个 Windows 计划任务承担（`DSH Superagent`、`DSH Superagent Watchdog`）

---

## 2. 飞书通道实证（本报告最重要的发现）

收尾时检查仓库，发现 **PR #5**：

```
PR #5  docs: append feishu-trigger marker to README
author=fishuser-sys  state=MERGED  mergedAt=2026-11-02T01:05:04Z
diff: README.md +1  <!-- feishu-trigger: ... -->
```

数据库佐证：

| 表 | 记录 |
|---|---|
| `decision` | `kind=accept`、`reason=explicitRouted`、thread=`feishu:oc_0246653d…`、ticket=`14a0bec5` |
| `ticket` | `14a0bec5`：title=「README.md 末尾追加一行 feishu-trigger 注释并开 PR」，**mandate.source=feishu**，strength=explicit |

**结论：飞书 → 评估 → Ticket → Worker → PR → 合并，全链路真实跑通。** 这是本项目第一次双通道（GitHub + 飞书）都完成端到端闭环。

---

## 3. 待机消耗结论（已核验）

| 组件 | 待机行为 | token |
|---|---|---|
| 飞书 Source | `event consume` 长连接 | 0 |
| GitHub Source | 每 60s 调 notifications API | 0（不调模型） |
| Worker 队列 | 空 | 0 |
| 自愈计划任务 | PowerShell 探端口 | 0 |

**只有“有消息进来”才会产生模型调用**：每条约 1 次评估；成票的再加 1 次完整 Worker。
今天实测：6 条消息 → 7 次评估 → 2 张票 → 2 个 PR（#4 GitHub 源、#5 飞书源）。

---

## 4. 当前系统状态

| 项 | 状态 |
|---|---|
| 原型实例（3082） | 运行中，全部服务 ready |
| GitHub Source | ready，received=2 |
| 飞书 Source | ready，received=5 |
| 计划任务 | `DSH Superagent` + `DSH Superagent Watchdog`（Ready） |
| dsh 定时提醒 | 已清空（0 条） |
| 补丁 | `patches/dsh-superagent-windows-adaptation.patch` |
| 报告 | 9 份，索引在桌面 `ai用\dsh use` |

---

## 5. 测试残留物（待用户决定是否清理）

| 项 | 状态 | 建议 |
|---|---|---|
| PR #4 / #5 | MERGED | 保留（历史证据） |
| Issue #1 / #2 / #3 | OPEN | 可关闭 |
| 分支 `agent/readme-*` | 已合入 main | 可删除 |
| 仓库 `zzc235/superagent-playground` | private | 保留或转私有归档 |

---

## 6. 若要把整套完全停机（用户需要时才做）

```powershell
# 1. 停自启/自愈
Disable-ScheduledTask -TaskName 'DSH Superagent'
Disable-ScheduledTask -TaskName 'DSH Superagent Watchdog'
# 2. 停实例
Get-CimInstance Win32_Process -Filter "Name='DeepSeek Harness.exe'" |
  Where-Object { $_.CommandLine -match 'profile superagent' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
# 3. 恢复：Enable-ScheduledTask + Start-ScheduledTask 'DSH Superagent'
```
