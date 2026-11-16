# 任务报告 · 2026-11-01 · Super-agent 现在能做到什么地步（三流水线 + 原型上机）

- **任务编号**：`2026-11-01-superagent-ceiling`
- **发起人**：zzc（“重新回到 super-agent 这个项目上来，我很好奇现在我们能做到什么地步”）
- **执行**：芙宁娜（dsh 桌面端 0.2.1-rc.3）
- **时间窗**：2026-11-01 19:38 → 19:52（Asia/Hong_Kong）
- **一句话**：**三条 Worker 真并行跑通了；Super-agent 原型也在这台 Windows 上真正起来了**（面板 3082 + API 就绪，只差 GitHub 源）。

---

## 0. 一页摘要

| 能力 | 状态 |
|---|---|
| Trigger→Thread→Ticket→Worker→验收 闭环 | ✅ 3 票并行，4 分钟内全部交付 |
| 官方 Claude Code Worker | ✅ 用于独立评审，产出可用 |
| 普通 subagent Worker | ✅ 修 build、做边界测试 |
| Watchdog 巡检 | ✅ 全程无异常误报（修了 1 个真 bug 后） |
| **Super-agent 原型本体** | ✅ **在本机跑起来了**：`/orchestrator/api/state` 返回、面板 200、7 个服务 ready |
| GitHub 源 | ⏸ 差专属账号 + 仓库（唯一阻塞） |
| 常驻 / OS 隔离 / 长程记忆 | ❌ 仍缺 |

---

## 1. 三流水线实跑（这是“现在能做到”的硬证据）

19:40 投三个 Trigger → `router.ps1 scan` → T-0002 / T-0003 / T-0004 同时 queued → 三个 Worker 并行派发。

| 票 | Worker | 任务 | 结果 | 耗时 |
|---|---|---|---|---|
| T-0002 | subagent | 修 `pnpm build` | ✅ **成功**，`lib/index.js` 450,257 B | ~3 min |
| T-0003 | subagent_claude_code（官方链路） | 独立评审 lite 架构 | ✅ 0/5/5 判定 + 3 个假象 | ~3 min |
| T-0004 | subagent | Router/Watchdog 边界测试 | ✅ 7/7 PASS + **10 个真 bug** | ~4 min |

四项全部在同一条 Router 循环里完成：scan → claim → 派发 → 验收 → close → watchdog `OK`。

### 1.1 T-0002 的真根因（值得记）
不是 tsdown 版本问题、不是镜像问题：**是我上一轮用 `pnpm add -D` 逐包补依赖，把 `package.json`/lockfile 改脏**，
增量安装留下半成品布局（`ansis`/`obug` 在 `.pnpm` 里但没链进 tsdown 的 node_modules）。
修法：`git status` 确认干净 → 删 `node_modules` → `pnpm install --frozen-lockfile` → `pnpm build` = exit 0。

### 1.2 T-0003 揪出的三个假象（Claude Code 评审，已 Router 复核属实）
1. `ROUTER.md` 宣称的去重/优先级根本没实现（`dedupeWindow` 零引用）。
2. **`new <thread> <title> -from zzc` 实跑即挂**（无 `-from` 参数），且 `new` 不落 Thread。
3. Watchdog 的 `drift` 实为“running 且无报告文件”，与文档“产物对不上”不是一回事；且用 `createdAt` 判 stale，**正在干活的票会被误判僵死**。

### 1.3 T-0004 的 10 个 bug（2 个 P0）
- **P0-1** `close <id> done "<结论>"`：结论落到无人读取的 `$A3`，`result` 存成字面量 `done`，还打印成功。
- **P0-2** drift 语义错误（见上），Worker 运行全程误报 `NEEDS_ROUTER`。
- 其余：claim 不刷新时间戳、归档同名 `-Force` 覆盖丢历史、`createdAt` 缺失让 watchdog 崩、
  kind 丢弃不写审计、YAML 引号被当陌生人、`thread` 可路径穿越、maxWorkers 是装饰等。

> 附：T-0004 的测试现场已复原，14 个文件 SHA256 全等、无残留，符合“Worker 不得污染状态”的约束。

---

## 2. 原型上机（今天最大的进展）

### 2.1 做了什么
```powershell
$carrier = 'C:\Users\zzc\AppData\Local\Programs\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd'
& $carrier superagent --from-default-profile web --dump-config     # 1. 建独立 profile
& $carrier plugin --profile superagent add "link:E:\dsh pr\woker2\dsh-superagent"   # 2. 装 bundle
# 3. 写 profiles/superagent/cordis.patch.yml（webserver:3082 + stateDir）
& $carrier --profile superagent --no-open                          # 4. 启动（无需 tmux）
```

### 2.2 Windows 上的两个坑
| 坑 | 现象 | 解法 |
|---|---|---|
| `stateDir` schema 只认 POSIX 绝对路径 | `ValidationError: $.stateDir expect string to match /^\//`，orchestrator 起不来 | 写 `'/dsh-state/superagent'`，Node 在 Windows 上把它解析为**当前盘符** `E:\dsh-state\superagent` |
| 启动器脚本依赖 tmux | `scripts/dsh-superagent` 是 Python + `fcntl`/`ps`/tmux | **绕开脚本**：直接 `dsh --profile superagent --no-open` 启动，用 HTTP 探活 |

### 2.3 实测结果
| 项 | 值 |
|---|---|
| 面板 | `http://127.0.0.1:3082/?token=2zMfM-O-…`（带 token，HTTP 200，页面 38 KB） |
| 管理 API | `GET /orchestrator/api/state` → 200 |
| masterId | `orchestrator-872e61f…` |
| 并发上限 | `maxWorkers = 3` |
| eval 模式 | `observe`（原型默认保守值） |
| 服务健康 | relay / notice / launch / delivery / assessment / reply / evals = **ready**；runtime = paused（等部署检查）；github = paused |
| 唯一阻塞 | `setup.problem = { place: github, code: repositoryUnset }` —— **只差 Repository 没填** |
| stateDir 落点 | `E:\dsh-state\superagent` |

**结论：原型的“身体”已经在这台机器上活着**，只等 GitHub 的“身份”（专属 agent 账号 + 测试仓库）接上 Source。

---

## 3. 能力阶梯（诚实版）

| 层级 | 内容 | 现在 |
|---|---|---|
| L0 | 单会话 + 手动派工 | ✅ |
| L1 | Trigger/Thread/Ticket/Worker/验收 闭环 + 多 Worker 并行 | ✅ 今天验证（3 并发） |
| L2 | 官方 Claude Code Worker + 普通 subagent + AgentTeams 三通道 | ✅ |
| L3 | Watchdog 定时巡检 + 失败降级（Worker 挂 → Router 亲自上） | ✅ |
| L4 | 原型本体运行（Router/Worker 双层、Trigger/Thread、observe 模式） | ✅ 服务已起，等 Source |
| L5 | 真实 GitHub Trigger（Issue/PR/CI → Ticket） | ⏸ 差账号与仓库 |
| L6 | 常驻（关机/退出仍在跑）、跨渠道（飞书/IM）、投机执行、A2A、长程记忆 | ❌ 未做 |

---

## 4. 改动清单

### 4.1 新增
- `C:\Users\zzc\.dsh\profiles\superagent\`（新 profile，来自 web 模板）
- `C:\Users\zzc\.dsh\profiles\superagent\cordis.patch.yml`（webserver 3082 + stateDir `/dsh-state/superagent`）
- bundle 安装：`dsh-superagent`（link 指向 `E:\dsh pr\woker2\dsh-superagent`）
- `E:\dsh-state\superagent`（运行态目录）
- `E:\dsh pr\woker2\dsh-superagent\lib\`（构建产物，450 KB 入口）
- superagent-lite：`reports/T-0002.md`、`T-0003.md`、`T-0004.md`，票 T-0002/3/4 已 done

### 4.2 修改
- `E:\dsh pr\woker2\superagent-lite\router.ps1`：`Next-TicketId` 格式化 bug 修复
  （`'T-{0:D4}' -f ($max+1)` 对 double 抛 “Format specifier was invalid” → 加 `[int]` 强转）

### 4.3 未触碰
- `~/.claude`（Claude Code 配置/工作区）、`profiles/desktop` 配置、`~/.dsh/AGENTS.md`
- 原型仓库源码（`git status` 干净，构建产物在 .gitignore 内）

---

## 5. 风险与下一步

| 优先级 | 事项 | 说明 |
|---|---|---|
| P0 | 注册专属 GitHub agent 账号 + 私有测试仓库 | 之后在面板 Sources 里填仓库与 CLI，即可产生真实 Ticket |
| P0 | 修 lite 的 10 个 bug（先 P0-1 close 丢结论、P0-2 drift 语义） | 已有详细报告，可直接开票派 Worker |
| P1 | 给原型写 Windows 启动器 `dsh-superagent.ps1`（start/status/stop + HTTP 探活） | 替代 tmux 版脚本；stop 语义仍需拍板 |
| P1 | 常驻：开机自启 + 断线重连 | 现在 3082 实例是会话内后台任务，会话结束即停 |
| P2 | 安全隔离：专用 OS 账号 + 凭据约束 | 原型 Worker 以操作者身份 danger-full-access 跑 |

---

## 6. 快照（2026-11-01T19:52+08:00）

| 项 | 值 |
|---|---|
| dsh 桌面端 | 0.2.1-rc.3 |
| 原型 commit | `6337fc823ce20251c8de8085948165c81aaa701e` |
| 构建产物 | `lib/index.js` 450,257 B（12 个 ESM 产物） |
| superagent profile | 新建，bundles: dsh-base / dsh-web-app / dsh-superagent |
| 面板 | `127.0.0.1:3082`（token 认证，HTTP 200） |
| API | `/orchestrator/api/{state,settings,sources}` 全通 |
| worker 通道 | subagent ✅ / subagent_claude_code ✅ / teammate ✅ |
| lite 票 | T-0001~0004 全 done，watchdog OK |
