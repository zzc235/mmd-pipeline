# 任务报告 · 2026-11-01 · 禁用 dsh-subagent-default-model（并意外修复 Worker 通道）

- **任务编号**：`2026-11-01-disable-default-model`
- **发起人**：zzc（“暂时禁用这个插件吧 cordis.patch.yml；另外不要乱动 Claude Code 的工作区”）
- **执行**：芙宁娜（dsh 桌面端 0.2.1-rc.3）
- **时间窗**：2026-11-01 19:21 → 19:30（Asia/Hong_Kong）
- **一句话**：按要求禁用插件 → 热重载即生效（无需重启）→ **官方 `subagent_claude_code` 打通（WORKER-OK）**，顺带**普通 `subagent` 通道也复活（SUBAGENT-OK）**。

---

## 0. 一页摘要

| 项 | 结果 |
|---|---|
| 禁用方式 | `cordis.patch.yml` 补丁行加 `disabled: true`（配置段原样保留，一行可恢复） |
| 是否需重启 | **否**，热重载生效：`plugin_manager` 显示 `enabled: false / fiberPhase: null` |
| 官方 Claude Code 链路 | ✅ 打通，探针返回 `WORKER-OK` |
| 普通 Worker 通道 | ✅ **意外修复**，探针返回 `SUBAGENT-OK` |
| Claude Code 工作区 | ✅ **未触碰**（仅只读看过 `~/.claude/settings.json` 做诊断，零修改） |

---

## 1. 改动详情

### 1.1 唯一改动文件：`C:\Users\zzc\.dsh\profiles\desktop\cordis.patch.yml`

- 备份：`cordis.patch.yml.bak_20261101_disable_defaultmodel`（11,239 B）
- 改动前 → 改动后：`dsh-subagent-default-model` 条目新增一行 `disabled: true`
- 同时新增 7 行中文注释，写清：禁用原因、影响、恢复方法
- 配置段（三条 free 路由 / round-robin / failover）**原样保留**，恢复时只删 `disabled: true` 一行
- 文件大小 11,239 → 11,963 B；SHA256：`94F68AA6B476A73E679FB6FAA287FB0634DD6A3B9A0C8CA06386236A0CA3C095`

```yaml
- id: dsh-subagent-default-model
  name: "dsh-subagent-default-model"
  disabled: true          # ← 新增，唯一功能性改动
  config:
    models: [...]         # 原样保留
```

### 1.2 未触碰（显式声明）
- ❌ 未改 `~/.claude/` 下任何文件（settings.json / .claude.json 均只读）
- ❌ 未改 Claude Code 工作区、会话、CLAUDE.md
- ❌ 未改 `~/.dsh/AGENTS.md`、其他插件条目、任何 profile 的 `package.json`
- ✅ 仅清理了自己创建的临时探针目录 `tmp/cc-probe`（空目录）

---

## 2. 验证证据

### 2.1 热重载生效（`plugin_manager list_plugins`）
```json
{ "entryId": "include:dsh-subagent-default-model",
  "moduleName": "dsh-subagent-default-model",
  "enabled": false, "fiberPhase": null,
  "patchId": "dsh-subagent-default-model" }
```

### 2.2 官方 Claude Code 链路
```
subagent_claude_code(cwd=E:\dsh pr\woker2\tmp\cc-probe,
                     prompt="只做一件事：回复 WORKER-OK")
→ 子代理 bf87fe04… 完成，closing message: "WORKER-OK"
```
禁用前同一调用立即抛 `subagent provider "claude-code" does not support the "agentOptions" capability`。

### 2.3 普通 Worker 通道（意外收获）
```
subagent("只回复一行：SUBAGENT-OK")
→ 子代理 d2cddb16… 回报 "SUBAGENT-OK"
```
**推论**：上午 Worker 三连失败的根因不是 subagent 本身，而是 default-model 把子代理路由到了
`our-free-model / workbuddy / minimax` 这些当时不可用的免费渠道。禁用后子代理继承父路由
（`deepseek-account / deepseek-flash`），立刻恢复。

---

## 3. 决策与影响

| 项 | 说明 |
|---|---|
| 为什么用 `disabled: true` 而不是卸载 | 可逆、一行恢复；卸载会丢 `dsh.profile.bundles` 配置 |
| 热重载为何能生效 | Cordis Loader 监听 patch 层，disabled 在每次 mount 决策时求值 |
| 失去什么 | 免费模型池轮转 + 跨供应商故障转移（原 3 条路由）、fork 缓存优化相关逻辑 |
| 得到什么 | 官方 Claude Code 工具可用；普通子代理恢复可用 |
| 新风险 | 子代理现在与父会话同路由：父路由一挂，子代理一起挂，无跨供应商兜底 |
| 回滚 | 删掉 `disabled: true` 一行即可，配置段已完整保留 |

---

## 4. 环境快照（2026-11-01T19:30+08:00）

| 项 | 值 |
|---|---|
| dsh 桌面端 | 0.2.1-rc.3 |
| `cordis.patch.yml` | 11,963 B / SHA256 `94F68AA6…C095` |
| `dsh-subagent-default-model` | enabled=false, fiberPhase=null（插件仍在 node_modules，仅未挂载） |
| `@deepseek-ai/dsh-subagent-claude-code` | enabled=true, active |
| claude CLI | v2.1.251（`~/.local/bin/claude.exe`） |
| 子代理默认路由 | 继承父会话：deepseek-account / deepseek-flash |
| 备份 | `cordis.patch.yml.bak_20261101_disable_defaultmodel` |

---

## 5. 未完成 / 后续

1. **本神写的 `tools/claude-worker.ps1` 仍然保留**——官方工具是一对一委派，直调版适合批量/后台并行，两者并存不冲突。
2. 免费渠道池（our-free-model / workbuddy / minimax）的可用性未复核；将来想恢复 default-model，
   必须先跑通三条免费路由的探针，否则会回到“子代理全灭”的状态。
3. 若要两者兼得（既保留免费池又让 claude-code 可用），需要上游给插件加“provider 不支持
   `agentOptions` 时跳过注入”的判断，可提 issue（报告的上一份里有完整证据链）。
4. 官方链路的成本/用量未观测：claude-code 走的是 DeepSeek 端点，成本记在同一个 key 上。

---

## 6. 复现 / 回滚

```powershell
# 查看当前状态
#   plugin_manager list_plugins → 搜 dsh-subagent-default-model → enabled=false

# 回滚（恢复免费模型池 + 故障转移）
#   编辑 C:\Users\zzc\.dsh\profiles\desktop\cordis.patch.yml
#   删除 "  disabled: true" 这一行，保存即热重载

# 完整还原到改动前
Copy-Item 'C:\Users\zzc\.dsh\profiles\desktop\cordis.patch.yml.bak_20261101_disable_defaultmodel' `
          'C:\Users\zzc\.dsh\profiles\desktop\cordis.patch.yml' -Force
```
