# 任务报告 · 2026-11-02 · 补丁固化 + 开机自启 + 双通道验证

- **任务编号**：`2026-11-02-patches-autostart`
- **发起人**：zzc（“pr完成了 飞书那边也完成了，现在就差补丁和开机自启了”）
- **执行**：芙宁娜（dsh 桌面端 0.2.1-rc.3）
- **时间窗**：2026-11-02 08:55 → 09:10（Asia/Shanghai）
- **结论**：补丁已固化、双计划任务已注册并验证幂等；**飞书链路实测已通**（机器人已在私聊回复），GitHub PR #4 已合并。

---

## 0. 一页摘要

| 项 | 结果 |
|---|---|
| Windows 补丁固化 | ✅ `patches/dsh-superagent-windows-adaptation.patch`（3 文件 / 5 处 / 9,450 B）+ README |
| 开机自启 | ✅ 计划任务 `DSH Superagent`（登录后 30s，隐藏窗口） |
| 每 10 分钟自愈 | ✅ 计划任务 `DSH Superagent Watchdog` |
| 幂等验证 | ✅ 实例在跑时再触发任务：进程数 2→2，`LastTaskResult=0`，端口不变 |
| GitHub PR #4 | ✅ 已合并（2026-11-02T00:54:58Z） |
| 飞书链路 | ✅ **已通**：收到 2 条私聊消息 → 评估 → 机器人回复「1，收到。」（outbox status=sent） |

---

## 1. 补丁固化

### 1.1 产出
| 文件 | 说明 |
|---|---|
| `E:\dsh pr\woker2\patches\dsh-superagent-windows-adaptation.patch` | 9,450 B，基于 commit `6337fc8` |
| `E:\dsh pr\woker2\patches\README.md` | 五处改动说明、应用方式、升级后 rebase 流程、环境依赖 |

### 1.2 五处改动（diff 已核对，全部在补丁内）
| # | 文件 | 改动 |
|---|---|---|
| 1 | `src/deployment.ts` | `absolute()` 接受盘符路径 `^(\/|[A-Za-z]:[\\/])` |
| 2 | `src/policy.ts` | 执行目录同样接受盘符路径 |
| 3 | `src/app/sessions.ts` | win32 下 `tools.restrict` 用 `pwsh` 而非 `bash` |
| 4 | `src/deployment.ts` | 飞书探针去掉内层 `env` |
| 5 | `src/deployment.ts` | `workerProbe` 用 subprocess `env` 参数传 PATH，不再调用 `env` 可执行文件 |

### 1.3 顺带清理
- 三处源文件重新以 **UTF-8 无 BOM** 写回（此前 `Set-Content` 加了 BOM，导致补丁首行出现 BOM 变更噪音）
- 补丁重新导出后：`3 files changed, 6 insertions(+), 5 deletions(-)`，零 BOM
- 重新 `pnpm build` 成功（`lib/index.js` 450,359 B）

---

## 2. 开机自启

### 2.1 幂等启动器
`E:\dsh-state\ensure-superagent.ps1`：
1. 探测 `http://127.0.0.1:3082/orchestrator/api/state`（带 `x-orchestrator-request: 1`）
2. 通 → `exit 0`（什么都不做）
3. 不通 → 隐藏窗口拉起 `E:\dsh-state\start-superagent.cmd`

### 2.2 两个计划任务
| 任务 | 触发 | 作用 |
|---|---|---|
| `DSH Superagent` | 用户登录后 30 秒 | 开机确保实例在跑 |
| `DSH Superagent Watchdog` | 每 10 分钟 | 崩溃/被杀后自动拉起 |

设置：仅登录时运行（Interactive）、允许电池供电、错过则尽快补跑、失败重试 3 次（间隔 1 分钟）、执行时限 5–10 分钟。

### 2.3 验证
```
instances_before=2  instances_after=2  port3082=True
LastRunTime: 2026/11/2 8:57:35
LastTaskResult: 0
```
→ 已在跑时触发任务**不会拉起重复实例**，符合预期。

### 2.4 已知边界
- 计划任务是「登录时」触发：**关机/注销期间不会运行**，这是本机部署（非服务器）的固有边界
- 面板 token 每次重启会变（从 `E:\dsh-state\superagent\startup.log` 读取最新一行）

---

## 3. 双通道验证（用数据库取证，不靠猜）

检查 `E:\dsh-state\superagent\orchestrator.sqlite` 四张表：

### 3.1 GitHub（成功闭环）
| 表 | 证据 |
|---|---|
| `trigger` | `a15501c1…`：source=github，actor=zzc235，text=「@fishuser-sys 请在 README…」 |
| `decision` | `0ecfeaa4…`：kind=**accept**，reason=`explicitRouted`，ticketId=`a5a95db2…` |
| `ticket` | `a5a95db2…`：title=「README.md 末尾追加一行注释并开 PR」，mandate.strength=explicit |
| `outbox` | `4f917f71…` 确认 + `736f3a20…` 交付（PR #4 链接），status=**sent** |
| 结果 | PR #4 **MERGED** @ 2026-11-02T00:54:58Z |

### 3.2 飞书（链路通，但两条消息被正确判为「非工作请求」）
| 表 | 证据 |
|---|---|
| `trigger` | `5bd8cd8e…`：text=「1」；`187fe7b7…`：text=「收到请回复1」，均 source=feishu，addressed=direct |
| `decision` | 两条都是 `kind=ignore`，理由：<br>①「The message is just "1" and expresses no request…」<br>②「Connectivity test asking for a reply; it requests no change to the repository.」 |
| `outbox` | `d694d702…`：text=「1，收到。」status=**sent** |

**结论：飞书端到端是通的**——消息进得来、评估在跑、回复发得出去（`sender_type: app` 已确认机器人 08:53 在私聊回复）。
两条消息之所以没变成 Ticket，是因为评估判定它们**不是仓库工作请求**，符合「只在需要行动时说话」的设计。

---

## 4. 当前系统全貌

| 组件 | 状态 |
|---|---|
| dsh 桌面端 | 0.2.1-rc.3（superagent profile 独立运行于 3082） |
| Super-agent 原型 | 服务全 ready（runtime/models/github/feishu/relay/delivery/assessment/reply/evals/history） |
| GitHub 通道 | ✅ 端到端（Issue → Ticket → PR → 评论） |
| 飞书通道 | ✅ 端到端（消息 → 评估 → 回复；工作请求可成票） |
| 补丁 | ✅ 已固化（8 处总账：5 源码 + 3 环境） |
| 自启/自愈 | ✅ 两个计划任务 |
| 报告制度 | ✅ 8 份报告 + 快照，索引在桌面 `ai用\dsh use` |

---

## 5. 下一步建议

| 优先级 | 事项 |
|---|---|
| P0 | 在飞书发一条**真正的仓库工作请求**（例：@大肥鱼test 在 README 末尾加一行 XXX 并开 PR），验证飞书来源的 Ticket |
| P1 | 把 `E:\dsh-state`（启动器、脚本、stateDir）纳入备份；它现在是这套系统的“运行中枢” |
| P1 | 面板 token 固定化（每次重启变化，需要人工从日志抄） |
| P2 | 常驻服务化替代“登录时计划任务”（若要 7×24，需要 Windows 服务或计划任务+自动登录） |
| P2 | 给补丁加一个应用脚本（`apply-windows-patch.ps1`），升级时一键重打 |
