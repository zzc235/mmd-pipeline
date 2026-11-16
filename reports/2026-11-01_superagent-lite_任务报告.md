# 任务报告 · 2026-11-01 · Super-agent 本机版落地

- **任务编号**：`2026-11-01-superagent-lite`
- **发起人**：zzc
- **执行**：芙宁娜（dsh 桌面端 0.2.1-rc.3，Lead + 降级执行）
- **时间窗**：2026-11-01 17:59 → 19:06（Asia/Hong_Kong）
- **关联文章**：《Super-agent 设计探索：迈向更自主的 Agent 系统》（DeepSeek Harness 团队，2026-10-31）
- **关联原型**：[dsh-superagent-prototype](https://github.com/deepseek-ai/dsh-superagent-prototype) commit `6337fc8`

---

## 0. 一页摘要

本次任务把文章里最值钱的那部分——**Trigger → Thread → Ticket → Worker → 验收** 的闭环——在本机用现有能力复刻，
不依赖原型仓库、不需要新账号，产出可运行骨架 `superagent-lite`，并**实测跑通一次完整闭环**。

同时把原型仓库摸清并落地源码，发现一个**所有人都没说过的坑**：`scripts/dsh-superagent` 不是 shell，
是 Python，且硬依赖 `fcntl` / `ps` / `tmux` / `SIGINT` 四处 POSIX —— **Windows 装 tmux 也跑不起来**。

最终状态：**骨架 ✅ 可用 / 原型 ⏸ 等账号 & 构建修复 / 一个决策待拍板（stop 语义）**。

---

## 1. 任务背景与结论

### 1.1 用户问题
1. 《Super-agent 设计探索》怎么看？
2. 本机还缺什么？
3. “试试看吧”（落地），随后问 GitHub 链接不稳定的方案。

### 1.2 核心判断
- 文章真正的判断句是「瓶颈从模型能力变成人的注意力」；最关键的工程约束是「**Worker 不直接对用户说话**」（对外单写入口，避免 N 个会话各自喊话的噪音）。
- Inline & Spill + 链式召回 = 对上下文窗口的工程回答（不塞记忆，建索引）。
- 文章最诚实的是未解问题清单：Router 扩缩、跨月记忆、脱离 Session 的协作、A2A、安全隐私（BYOM 接本地 = 提示词注入 + 凭据外泄）。
- 实验（p50 12.4min / p95 15.7min vs 单会话 p95 29.5min；Router 1→40 trigger/min，batch 1.0→2.8）只能当方向性证据：合成负载、300 条里 20 条工作请求、1/4 缩放。

---

## 2. 交付物清单

| # | 路径 | 大小 | SHA256(前16) | 作用 |
|---|---|---|---|---|
| 1 | `E:\dsh pr\woker2\superagent-lite\router.ps1` | 7,913 B | `EC70B70F86F85996` | Router 程序层：扫描/建票/状态机/引用链 |
| 2 | `…\superagent-lite\watchdog.ps1` | 1,882 B | `8F69FA1D14ABB6EB` | Watchdog：stale / drift / untouched 判定 |
| 3 | `…\superagent-lite\POLICY.json` | 312 B | `5691605E3776C0D2` | 策略：白名单、observe/act、超时阈值 |
| 4 | `…\superagent-lite\ROUTER.md` | 1,874 B | `BF9EDC89FCC9A356` | Router 行为契约（每轮循环 + 硬规则） |
| 5 | `…\superagent-lite\README.md` | 2,493 B | `28B0F013D8AF0FAF` | 架构映射、用法、与原型差距 |
| 6 | `…\superagent-lite\GITHUB-ONBOARDING.md` | 5,901 B | `FBBDA884FCA54669` | 账号注册后的接入清单 + 网络实测 |
| 7 | `…\superagent-lite\scan.cmd` / `status.cmd` / `watchdog.cmd` | 157/130/158 B | — | 绕开 Restricted 执行策略的入口 |
| 8 | `…\superagent-lite\reports\T-0001.md` | 7,809 B | `9A3B8D2E8F7E3F3E` | Ticket 产物：Windows 适配方案 + POSIX 取证 |
| 9 | `…\superagent-lite\tickets\T-0001.json` | 1,697 B | `4F63B2444E02C834` | 工作项（done，含降级记录） |
| 10 | `…\superagent-lite\threads\superagent-win.json` | 1,334 B | `7AF16B940ED69132` | Thread：Trigger 原文 + Ticket 引用链 |
| 11 | `E:\dsh pr\woker2\tools\fetch-github-repo.mjs` | — | — | 无 git 取码器（216/216 实测） |
| 12 | `E:\dsh pr\woker2\dsh-superagent\` | 216 文件 | commit `6337fc8` | 原型源码落地（git 干净） |

---

## 3. 修改详情（逐项）

> 全程**未修改**：`~/.dsh/AGENTS.md`、`profiles/desktop/cordis.patch.yml`、任何已装插件配置。
> 本次只做**新增**，不覆盖既有资产。

### 3.1 新增：superagent-lite 目录（E:\dsh pr\woker2\superagent-lite\）
- `inbox/` `threads/` `tickets/` `archive/` `reports/` 五个子目录
- 核心脚本 3 个（router / watchdog / 3 个 .cmd 入口）
- 文档 3 份（README / ROUTER / GITHUB-ONBOARDING）
- 数据 3 份（POLICY.json / T-0001.json / superagent-win.json）
- `archive/_refs/dsh-superagent.sh`：原型启动器 251 行全文备份（取证用）

### 3.2 新增：tools/fetch-github-repo.mjs
- GitHub Trees API 列文件 → raw / jsDelivr 并发下载（8 并发，每文件 3 次退避重试）
- 实测：216 文件 / 11.8s / 0 失败

### 3.3 新增：dsh-superagent 源码树
- 获取方式：`git -c http.sslBackend=openssl clone --depth 1 --single-branch`（2.4s）
- 仓库内 `git config http.sslBackend openssl`（repo-local，未动全局）
- `pnpm install` ✅ 通过（11.3s，npmmirror）
- `pnpm build` ❌ 失败（详见第 6 节）
- 收尾：`package.json` / `pnpm-lock.yaml` 已 `git checkout` 还原，`git status` 干净

### 3.4 新增：定时任务
- id：`schedule-9d7e874f-acd4-4676-be53-de48a827c1ed`
- cron：`0 * * * *`（Asia/Hong_Kong），标题「superagent-lite Watchdog 巡检」
- 已于 19:00 首次触发，输出 `OK`（无异常只回一行）

### 3.5 已删除
- `E:\dsh pr\woker2\dsh-superagent` 的空白占位目录（首次克隆失败残留）
- `_clone_trial`、`dsh-superagent-test` 临时目录

---

## 4. 关键决策记录

| # | 决策 | 理由 | 被否决方案 |
|---|---|---|---|
| D1 | 先做「六成版」而非直接装原型 | 原型要专属 GitHub agent 账号；且 Windows 适配未解 | 直接 `git clone` + 装 bundle（卡在账号与 tmux） |
| D2 | Worker 派发失败 3 次后中止，改 Router 降级执行 | 渠道铁律：不通即止，禁止原地空转 | 继续重试 subagent / 换模型再试 |
| D3 | 脚本保持 ASCII-only + 显式 `-Encoding UTF8` | PowerShell 5.1 把无 BOM UTF-8 当 ANSI，中文注释会炸 | 直接写中文注释 |
| D4 | 提供 `.cmd` 包装器 | 本机执行策略 Restricted，且无 `pwsh`（只有 powershell.exe 5.1） | 要求用户改执行策略 |
| D5 | 不擅自写全局 `http.sslBackend` | 写 `~/.gitconfig` 超出会话沙箱，需用户授权 | 直接改全局配置 |
| D6 | stop 语义不替用户拍板 | 强杀会丢 Executor 步骤，属产品级取舍 | 自动选 `-Force` |

---

## 5. 实测证据

### 5.1 闭环实跑
```
Trigger  archive/20261101-1802-win-adapt.md
  → router.ps1 scan → ticketed T-0001 (thread: superagent-win)
  → claim T-0001 → running
  → Worker 派发失败 ×3 → fail（原因入库）
  → Router 降级产出 reports/T-0001.md → claim/close(done)
  → THREAD superagent-win settled
  → watchdog.ps1 → verdict: OK
```

### 5.2 Worker 通道失败记录（重要）
| 路由 | 结果 |
|---|---|
| `subagent` #1 | 起后失败，无产出无回报 |
| `subagent` #2 | 同上 |
| `spawn_teammate worker-win` | 转 inactive，报告零字节 |
| `subagent_claude_code` | 后端不支持 `agentOptions`，无法启动 |

**结论：本机 Worker 层当前不可用**；这是文章里 Watchdog 存在的直接理由（“在跑”≠“在推进”）。

### 5.3 GitHub 通道实测（2026-11-01）
| 通道 | 结果 |
|---|---|
| `git clone` + schannel（默认） | **必失败** `SEC_E_NO_CREDENTIALS`（0.3s） |
| `git clone` + openssl + `--depth 1` | **3/3 成功**（2.4 / 2.3 / 2.4s） |
| `gh api` | 稳定（678ms） |
| raw.githubusercontent / jsDelivr | 时快时慢（747ms / 843ms → 复测双超时） |
| TCP 443（6 个域名） | 全 OPEN |
| SSH over 443（ssh.github.com） | 通（0.7s，publickey 拒绝＝缺 key） |

### 5.4 原型启动器 POSIX 依赖取证（`scripts/dsh-superagent`，251 行 Python）
| 行 | 代码 | 后果 |
|---|---|---|
| L10 | `import fcntl` | Windows 启动即 ImportError |
| L59 | `ps -ww -o pid=,ucomm=,args=` | 无 POSIX ps |
| L166-181 | `tmux has-session / new-session / new-window` | 进程托管全押 tmux |
| L141 | `os.kill(pid, SIGINT)` | Windows 上等价强杀 |
| L226 | `os.umask(0o077)` | Windows 无 umask |

---

## 6. 环境快照（2026-11-01T19:06:12+08:00）

### 6.1 主机与运行时
| 项 | 值 |
|---|---|
| 主机 | DESKTOP-UI4EH47 / 用户 zzc |
| OS | Windows 10.0.26200 |
| dsh 桌面端 | 0.2.1-rc.3 |
| Node | v24.15.0 |
| pnpm | 11.20.0（仓库内按 packageManager 用 11.7.0） |
| git | 2.54.0.windows.1 |
| gh | 2.100.0（登录 zzc235，含 repo/workflow scope） |
| PowerShell | 5.1.26100（**无 `pwsh`**，执行策略 Restricted） |

### 6.2 dsh profile（desktop）
- bundles 11 个：dsh-base / dsh-web-app / our-free-model / subagent-default-model / experimental-agent-team-profile / tool-worktree / plugin-market-bundle / subagent-claude-code / voice-input-bundle / plugin-open-app / pinned-sessions
- dependencies 11 个
- `cordis.patch.yml` SHA256：`4C4E214AB10557DABB386A402FC5301C8A1E1E9DA1A45EF5BA4149B8E86FA488`

### 6.3 当前缺口（快照时的“还缺什么”）
- ❌ 专属 GitHub Agent 账号（只有操作者本人）
- ❌ Worker 通道（subagent / teammate 均不可用）
- ❌ 常驻：无自启、无服务、无计划任务（Watchdog 只在会话活着时触发）
- ❌ tmux / lark-cli / jq
- ❌ `superagent` profile（需写 `~/.dsh/profiles`，沙箱外）
- ❌ `pnpm build` 未通过
- ⚠️ 安全基线：RocksVPN 服务在跑、历史 LNK 木马复发

### 6.4 文件级快照
见同目录 `snapshot-2026-11-01T1906.json`（含全部交付物哈希、仓库 commit、调度器与票据状态）。

---

## 7. 后续扩张建议（Roadmap）

| 优先级 | 事项 | 依赖 | 预计 |
|---|---|---|---|
| P0 | 拍板 stop 语义（A 只发 taskkill / B `-Force` / C 等上游 shutdown API） | 用户决策 | 即时 |
| P0 | 注册专属 GitHub Agent 账号 + `gh-agent` 隔离配置 | 用户 | 20 min |
| P0 | 修 `pnpm build`（候选：Node 22 / npm 装 / `pnpm install --force`） | 无 | 30 min |
| P1 | 写 `scripts/dsh-superagent.ps1`（Windows 启动器，先只做 status） | P0 前三项 | 2 h |
| P1 | 恢复 Worker 通道（排查 subagent 后端），否则 Router 永远只能降级跑 | 渠道 | 1 h |
| P1 | 全局 `git config http.sslBackend openssl` | 用户授权 | 1 min |
| P2 | 常驻化：开机自启 / 服务化 / 断线重连 | P0 | 半日 |
| P2 | Trigger 源扩展：飞书（lark-cli）、本地文件 watcher、邮件 | 原型落地 | 1–2 日 |
| P3 | 长程记忆：Chain of Recall 索引层（Thread 引用链已有雏形） | — | 数日 |

---

## 8. 未完成与风险

1. **Worker 层不可用** —— 本次全靠 Router 降级执行，与文章设计意图不符；恢复前不要指望并发。
2. **`pnpm build` 失败** —— tsdown 在 Node 24 下解析不到自身传递依赖（`obug` 2.1.4 vs 3.0.0 双版本冲突 + pnpm 布局）；原型 `lib/` 尚未生成。
3. **无隔离** —— 原型 Worker 以操作者身份 `danger-full-access` 跑；本机未建专用系统账号。
4. **安全基线未过** —— 云端触发接本机前必须先处理 RocksVPN / 启动项。
5. **stop 语义未定** —— Windows 无 SIGINT 投递，这是移植最大风险点。
6. **定时器非守护** —— 会话关闭即停，不是真正的“持久在线”。

---

## 9. 复现步骤

```powershell
# 1. 闭环骨架
Set-Location 'E:\dsh pr\woker2\superagent-lite'
.\scan.cmd        # 扫 inbox → Ticket
.\status.cmd      # 票据看板
.\watchdog.cmd    # 健康检查（OK / NEEDS_ROUTER）

# 2. 投一个 Trigger
#    在 inbox\ 新建 .md，头部 --- from: zzc / kind: request / thread: <id> / title: ... ---

# 3. 取原型源码（任选）
git -c http.sslBackend=openssl clone --depth 1 --single-branch https://github.com/deepseek-ai/dsh-superagent-prototype.git <dir>
node "E:\dsh pr\woker2\tools\fetch-github-repo.mjs" deepseek-ai/dsh-superagent-prototype main <dir> --token (gh auth token)

# 4. 安装依赖
cd <dir>; pnpm install --registry=https://registry.npmmirror.com
```

---

## 10. 附录：对象映射（文章 ↔ 本机实现）

| 文章对象 | 本机实现 | 落盘 |
|---|---|---|
| Trigger | `inbox/*.md`（front-matter） | `archive/` 归档 |
| 程序层过滤 | `router.ps1 scan`（白名单/kind） | `archive/dropped.log` |
| 语义层判断 | Router 模型判断 | — |
| Thread | `threads/<id>.json`（trigger 原文 + ticket 引用） | ✅ |
| Ticket | `tickets/T-xxxx.json`（state/worker/attempts/result） | ✅ |
| Worker Session | subagent / teammate（**当前失败**，降级为 Router 亲执行） | — |
| Router | 主会话 + `ROUTER.md` 契约 | ✅ |
| Watchdog | `watchdog.ps1` + cron `0 * * * *` | ✅ |
| Chain of Recall | Ticket → Thread → triggers[] 引用回读 | ✅ 雏形 |
| Inline & Spill | 未实现 | ❌ |
| 投机执行 | 未实现 | ❌ |
| A2A | 未实现 | ❌ |
