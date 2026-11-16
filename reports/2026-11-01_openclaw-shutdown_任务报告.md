# 任务报告 · 2026-11-01 · OpenClaw 备份并停用

- **任务编号**：`2026-11-01-openclaw-shutdown`
- **发起人**：zzc（“把记忆和工作区单独复制一份到 dsh use\open，然后将 openclaw 关闭；我怀疑每天都在尝试链接手机但一直没启动，白白浪费 token 额度”）
- **执行**：芙宁娜（dsh 桌面端 0.2.1-rc.3）
- **时间窗**：2026-11-01 19:25 → 19:32（Asia/Hong_Kong）
- **一句话**：怀疑**成立**——5 条 cron 每天唤醒 agent 共 5 次、全部长期失败（error 10~12 次），模型调用照烧；已备份 memory/workspace/agents 后整体停用并禁用自启。

---

## 0. 一页摘要

| 项 | 结果 |
|---|---|
| 备份 | `dsh use\open\{memory, workspace, agents}`，共 8,846 文件 / 366.2 MB |
| 停用 | gateway 进程已结束（PID 10828） |
| 自启 | 计划任务 `OpenClaw Gateway` → **Disabled** |
| 验证 | 端口 18789 不再监听；openclaw node 进程 = 0 |
| 原目录 | `~/.openclaw` **未删除**（约 590 MB），随时可恢复 |
| 连带 | 微信↔dsh 桥断开；手机 App 连不上 gateway |

---

## 1. 排查证据（为什么该关）

### 1.1 谁在跑
```
PID 10828  E:\nodejs\node.exe ...\openclaw\dist\index.js gateway --port 18789   今日 07:12:59 启动
计划任务 OpenClaw Gateway → C:\Users\zzc\.openclaw\gateway.vbs（登录触发，Interactive）
监听 0.0.0.0:18789（bind=lan，token 认证）
模型 deepseek/deepseek-chat（fallback deepseek-v4-flash）
```

### 1.2 每天在烧 token 的 cron（`openclaw cron list` 实测）
| 名称 | 计划 | 状态 | 投递 |
|---|---|---|---|
| 晚间复习提醒 | `30 21 * * *` | **error (10x)** | openclaw-weixin |
| 晚安问候 | `0 23 * * *` | **error (10x)** | openclaw-weixin |
| 早安问候 | `0 8 * * *` | **error (12x)** | openclaw-weixin |
| 午饭提醒 | `0 12 * * *` | **error (10x)** | openclaw-weixin |
| 傍晚问候 | `30 18 * * *` | **error (11x)** | openclaw-weixin |

**关键点：失败不省钱。** 每次唤醒都会先跑 isolated 会话（模型调用）再尝试投递，投递挂了记 error，
token 已经花掉了。今天实际产生的会话时间戳（本地 07:17 / 08:03 / 12:00 / 18:30）与之吻合。

### 1.3 不是 heartbeat 的锅
`workspace\HEARTBEAT.md` 是注释态（官方模板要求留空以避免心跳 API 调用），所以烧 token 的是**cron**，不是心跳。

---

## 2. 交付物与操作

### 2.1 备份（复制，未移动、未删除源）
| 目标 | 来源 | 文件数 | 大小 |
|---|---|---|---|
| `dsh use\open\memory\` | workspace 记忆文件 + `workspace\memory\`（→ `daily\`） | 25 | ~0 MB |
| `dsh use\open\workspace\` | `~/.openclaw/workspace` 全量 | 7,499 | 177.5 MB |
| `dsh use\open\agents\main\` | `~/.openclaw/agents/main`（会话历史） | 1,322 | 188.7 MB |
| `dsh use\open\MANIFEST.md` | 清单 + 停用前快照 + 恢复步骤 | — | — |

### 2.2 停用操作
```powershell
Stop-ScheduledTask    -TaskName 'OpenClaw Gateway'
Stop-Process          -Id 10828 -Force     # 按命令行精确匹配 openclaw gateway
Disable-ScheduledTask -TaskName 'OpenClaw Gateway'
```

### 2.3 验证
```
task_state             = Disabled
port 18789 listening   = False
openclaw node procs    = 0
```

---

## 3. 未触碰（显式声明）

- ❌ `~/.openclaw` 原目录**未删除、未移动**（约 590 MB 仍占 C 盘）
- ❌ 未改 `openclaw.json`、`.env`、`gateway.vbs`、`gateway.cmd`
- ❌ 未改 workspace 的 `.git`
- ❌ 未动 dsh 侧任何配置（本轮纯 OpenClaw 侧操作）
- ✅ 仅结束 1 个进程、禁用 1 个计划任务

---

## 4. 影响与恢复

| 影响 | 说明 |
|---|---|
| 微信 ↔ dsh 桥 | 断开（`dsh-bridge/bridge.mjs` 依赖 gateway），手机微信里的分身暂不可用 |
| 5 条问候 cron | 全停（本来就是 error） |
| 手机 App | 无法连 `ws://<本机IP>:18789` |

**恢复**：
```powershell
Enable-ScheduledTask  -TaskName 'OpenClaw Gateway'
Start-ScheduledTask   -TaskName 'OpenClaw Gateway'
openclaw cron list            # 建议先清理/修好那 5 条，再开 gateway
```
整机还原见 `open\MANIFEST.md` 第四节。

---

## 5. 快照（2026-11-01T19:32+08:00）

| 项 | 值 |
|---|---|
| OpenClaw CLI | `C:\Users\zzc\AppData\Roaming\npm\openclaw.ps1`（全局 npm 安装） |
| gateway 入口 | `~/.openclaw/gateway.vbs` → `gateway.cmd` → node |
| 停用前 PID | 10828 |
| 计划任务 | `OpenClaw Gateway` = **Disabled** |
| 端口 18789 | 关闭 |
| 备份根 | `C:\Users\zzc\Desktop\ai用\dsh use\open` |
| 备份规模 | 8,846 文件 / 366.2 MB |
| 源目录保留 | `C:\Users\zzc\.openclaw`（约 590 MB，未动） |

---

## 6. 未完成 / 建议

1. 那 5 条 cron 的失败原因没有深挖（微信投递目标/登录态），**将来要恢复 OpenClaw 必须先修**，
   否则开一天烧一天。
2. 若确认长期不用，可回收 `~/.openclaw` ≈ 590 MB；当前保留是因为备份刚做完、且微信桥随时可能要用。
3. OpenClaw 的 workspace 里有一份 `deepseek-harness` 源码克隆（v0.1.0-rc.5），与 `~/.dsh` 的桌面端无关，
   已在备份中。
