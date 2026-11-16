# 任务报告 · 2026-11-02 · Super-agent 首次端到端打通（GitHub）

- **任务编号**：`2026-11-02-first-e2e-github`
- **发起人**：zzc（“改完了顺便 GitHub 账号也注册好了”）
- **执行**：芙宁娜（dsh 桌面端 0.2.1-rc.3）
- **时间窗**：2026-11-02 08:31 → 08:42（Asia/Shanghai）
- **结论**：**Super-agent 原型首次跑通真实 Trigger → Ticket → Worker → 交付**（GitHub Issue → PR + 评论），耗时 1 分 45 秒。

---

## 0. 一页摘要

| 环节 | 结果 |
|---|---|
| 新 GitHub Agent 账号 | `fishuser-sys`（gh 独立配置 `~/.config/gh-agent`） |
| 仓库授权 | 邀请为 collaborator，`permissions.push = true` |
| 原型 GitHub Source | `ready`，收到 2 条 Trigger |
| Ticket | ✅ 创建，Worker 运行 1m45s |
| 交付物 | ✅ **PR #4**（1 行新增，内容完全符合要求） |
| 对话回复 | ✅ Worker 在 Issue #3 下用中文回报（“已就绪，待评审，合并需由人完成”） |
| 飞书 | Source ready、事件消费者在线，但 `received=0`（待验事件订阅） |

---

## 1. 端到端证据链

```
08:38  操作者(zzc235) 在仓库开 Issue #3，正文 @fishuser-sys
        ↓ （GitHub 通知 → 新号通知通道）
08:39  Source 轮询到通知，received=2
        ↓
08:39  Ticket 创建，Worker 启动（load.running=1）
        ↓ 1m45s
08:41  Worker 完成：
        ├─ 分支 agent/readme-footer-comment-a5a95db2ee70
        ├─ 提交 b5e03a9
        ├─ PR #4 "docs: append triggered-by marker to README"（+1/-0）
        └─ Issue #3 评论回报（中文，说明“合并需由人来完成”）
```

### PR 实际 diff（一字不多、一字不少）
```diff
 # superagent-playground
 dsh-superagent 测试仓库（仅测试用，勿用于生产）
+<!-- triggered-by: feishu-github-test -->
```

### Worker 在 Issue 下的回报（原文）
> 收到：在 README.md 末尾追加一行 `<!-- triggered-by: feishu-github-test -->` 并开 PR，只改这一处。
> This is by an automated agent, not a human.
> [PR #4](…) 已就绪：README.md 末尾追加了 …，只改这一处，待评审；合并需由人来完成。

**这正好符合文章的设计：Worker 不直接对人喊话，交付回原始 Thread；且自动合并关闭（默认安全值）。**

---

## 2. GitHub 账号接入过程

| 步骤 | 操作 | 结果 |
|---|---|---|
| 1 | 用户浏览器登录新号 | ✅ |
| 2 | `gh auth login`（`GH_CONFIG_DIR=~/.config/gh-agent`，device flow 码 `796E-2746`） | ✅ 登录为 `fishuser-sys` |
| 3 | 用 zzc235 邀请 collaborator（write） | 邀请 id 340936091 |
| 4 | 新号 `PATCH /user/repository_invitations/340936091` | ✅ 接受 |
| 5 | 验证 `repos/zzc235/superagent-playground` | `push=True, admin=False` ✅ |
| 6 | 启动器注入 `GH_CONFIG_DIR` → 重启 profile | Source `ready` |

> 关键设计：**两个号分工**——zzc235 发请求，fishuser-sys 干活。自己 @ 自己不会产生通知，这一点已实测验证过。

---

## 3. Windows 适配补丁汇总（原型源码，5 处）

| # | 文件 | 改动 | 解决什么 |
|---|---|---|---|
| 1 | `src/deployment.ts` | `absolute` 正则接受盘符路径 | `stateDir` 只认 POSIX 绝对路径 |
| 2 | `src/policy.ts` | 执行目录同样接受盘符路径 | 同上 |
| 3 | `src/app/sessions.ts` | win32 下 restrict 用 `pwsh` 而非 `bash` | Windows 无 bash 工具，会话创建失败 |
| 4 | `src/deployment.ts` | 去掉飞书探针里的内层 `env` | 嵌套 `env` 在 msys 下不可解析 |
| 5 | `src/deployment.ts` | `workerProbe` 改用 subprocess `env` 参数而非 `env` 可执行文件 | msys `env` 会污染 lark-cli 的 API 调用（auth 通、API 404） |

环境侧配套：
- `start-superagent.cmd`：`cd /d E:\` + PATH（git usr/bin）+ `LARKSUITE_CLI_CONFIG_DIR` + `GH_CONFIG_DIR`
- `restart-superagent.ps1`：kill → 等 40s 锁过期 → start
- 所有配置通过管理 API 写入，不手改 SQLite

---

## 4. 飞书状态（未完成项）

| 项 | 状态 |
|---|---|
| 应用 `cli_aa6dfed5cd385c02`（大肥鱼test） | ✅ 可用（bot 身份、strict-mode bot、权限已开） |
| Source | ✅ `ready`，事件消费者 `event consume im.message.receive_v1` 在线 |
| 事件到达 | ❌ `RECEIVED = 0`（群里 @ 了两次都没推到） |
| 判断 | 事件订阅/长连接配置尚未生效，或事件未加入已发布版本 |

**下一步**：在开放平台「事件与回调」确认订阅方式为**长连接**、事件 `im.message.receive_v1` 已加入、并重新发版；然后用 `lark-cli event status` 看 RECEIVED 是否 > 0。

---

## 5. 改动清单

### 5.1 新增
- GitHub 账号 `fishuser-sys` 的独立 gh 配置：`C:\Users\zzc\.config\gh-agent`
- 仓库协作关系：`fishuser-sys` → `zzc235/superagent-playground`（write）
- 分支 `agent/readme-footer-comment-a5a95db2ee70`、PR #4、Issue #3
- 报告与快照（本文件 + `snapshot-2026-11-02T0842.json`）

### 5.2 修改
- `E:\dsh-state\start-superagent.cmd`：新增 `GH_CONFIG_DIR`
- `dsh-superagent\src\{deployment,policy,app/sessions}.ts` 第 4/5 处补丁 + 重建
- profile：GitHub Source 配置确认（repository + gh.exe）

### 5.3 未触碰
- 操作者账号 zzc235 的 gh 登录（仍在默认配置目录，未动）
- 用户其他 GitHub 仓库
- `~/.claude`、`~/.dsh/AGENTS.md`

---

## 6. 快照（2026-11-02T08:42+08:00）

| 项 | 值 |
|---|---|
| 面板 | `127.0.0.1:3082`（token 见 startup.log） |
| 服务健康 | runtime/models/github/feishu/relay/notice/launch/delivery/assessment/reply/evals 全 ready |
| GitHub Source | repo `zzc235/superagent-playground`，cli `gh.exe`，收到 2 条 Trigger |
| 飞书 Source | cli `lark-cli.exe`，chats=[]，otherChats=mentions，received=0 |
| 策略 | github allowed=[zzc235]；feishu allowed=[ou_dd21bb87…（张先生）] |
| Worker 通道 | subagent ✅ / claude-code ✅ / teammate ✅ |
| 新号 | fishuser-sys（push 权限） |

---

## 7. 下一步

| 优先级 | 事项 |
|---|---|
| P0 | 飞书事件订阅验证（长连接 + 事件入版本 + 发版） |
| P0 | 由人评审合并 PR #4（自动化不自动合并，这是设计） |
| P1 | 把 5 处 Windows 补丁整理成 patch 文件，避免 `git pull` 冲突 |
| P1 | 常驻化：开机自启服务，而不是 WMI 拉起的 detached 进程 |
| P2 | 飞书与 GitHub 双源并行跑一轮，观察 Router 合并/并发表现 |
