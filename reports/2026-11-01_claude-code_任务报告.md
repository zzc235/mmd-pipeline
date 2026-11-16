# 任务报告 · 2026-11-01 · Claude Code 接入核查

- **任务编号**：`2026-11-01-claude-code`
- **发起人**：zzc（“你是不是可以接 Claude Code 了，我记得是 dsh 更新后官方推出的”）
- **执行**：芙宁娜（dsh 桌面端 0.2.1-rc.3）
- **时间窗**：2026-11-01 19:08 → 19:20（Asia/Hong_Kong）
- **结论一句话**：**官方插件装了、CLI 也活着，但被 `dsh-subagent-default-model` 的 `agentOptions` 注入挡住了；已提供直调 Worker 绕开，实测可用。**

---

## 0. 一页摘要

| 问题 | 结论 |
|---|---|
| dsh 有官方 Claude Code 子代理插件吗？ | 有，且已装在 desktop profile（`@deepseek-ai/dsh-subagent-claude-code@0.2.1-rc.3`） |
| 本机有 claude CLI 吗？ | 有，`C:\Users\zzc\.local\bin\claude.exe` v2.1.251，实测可用（2.7s 返回） |
| 官方工具 `subagent_claude_code` 能调吗？ | **不能**，一调即报 `does not support the "agentOptions" capability` |
| 根因 | `dsh-subagent-default-model@2.1.8` 对所有缺 `agentOptions` 的派发**无条件注入**默认路由；claude-code 提供方声明 `NO_START_CAPABILITIES`，宿主直接拒绝 |
| 现在能接吗？ | **能**——已交付 `tools/claude-worker.ps1` 直调版，实测 4.6s 返回 `WORKER-OK` |
| 副作用提醒 | 本机 Claude Code 被指向 DeepSeek 的 Anthropic 兼容端点，**实际跑的是 deepseek-v4-flash** |

---

## 1. 背景

用户记得 dsh 更新后官方推出了 Claude Code 接入。核查目标：
1. 插件与 CLI 是否就位；
2. 官方链路为何失败；
3. 给出可用的替代/修复路径。

---

## 2. 证据链

### 2.1 环境就位
| 项 | 值 |
|---|---|
| 插件包 | `@deepseek-ai/dsh-subagent-claude-code@0.2.1-rc.3`（node_modules 内） |
| 插件自带 patch | 注册 `subagent-claude-code`（provider）+ `tool-subagent-claude-code`（tool，provider=claude-code, maxDepth=provider-managed） |
| 加载状态 | `include:subagent-claude-code`，status=schema（已挂载） |
| claude CLI | v2.1.251（Claude Code），`~/.local/bin/claude.exe` |
| 探针 | `claude -p "只回复两个字：可用"` → 2.7s，exit 0，输出“可用” |

### 2.2 失败根因（双证据）

**插件侧**：`dsh-subagent-default-model/lib/index.js`
```js
// L235-241
function applyDefaultModel(state, request) {
  if (request === void 0 || request === null) return request;
  if (request.agentOptions !== void 0) return request;
  const model = defaultModel(state);          // ← 配置里三条免费路由
  if (model === void 0) return request;
  return { ...request, agentOptions: model }; // ← 无条件注入
}
```
README 亦自述：「插件包装宿主 `ctx.subagents` 服务……覆盖所有派发路径——内置的 `subagent`/`subagent_fork` 工具、agent-team 的 `spawn_teammate`，以及**任何调用该服务但未提供 `agentOptions` 的自定义工具**」。

**宿主侧**：`app.asar`（两处相同逻辑）
```js
for (const { when, cap } of needs)
  if (when && !provider.capabilities[cap])
    throw new SubagentError(`subagent provider "${provider.name}" does not support the "${cap}" capability`, 'UNSUPPORTED_CAPABILITY');
```
claude-code 插件 `lib/index.js:506`：`capabilities = NO_START_CAPABILITIES;` — 即它不接受 `agentOptions`。

**链路**：`subagent_claude_code` → 宿主 `subagents.startActivation()` → default-model 中间件塞入 `agentOptions: {provider:'our-free-model', model:'mimo-v2.6-flash-free'}` → 宿主校验 `agentOptions` 能力 → claude-code 未声明 → 抛 `UNSUPPORTED_CAPABILITY`。

### 2.3 直调验证（绕开插件链路）
```
tools/claude-worker.ps1 → claude -p（stdin 喂 prompt，UTF-8 字节写入）
结果：ok=true, exitCode=0, elapsedMs=4587, stdout="…\nWORKER-OK\n"
stderr: [claude-code:unrecognized_model] {"model":"deepseek-v4-flash","query_source":"generate_session_title"}
```

### 2.4 模型真相
`~/.claude/settings.json`：
```json
"env": {
  "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
  "ANTHROPIC_AUTH_TOKEN": "sk-3663…（DeepSeek key）",
  "ANTHROPIC_MODEL": "deepseek-v4-flash",
  ...
  "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
}
```
→ **Claude Code 只是壳，模型是 DeepSeek**。所以“接 Claude Code”没有额外模型成本，换来的是它的工具编排/子代理/团队机制。

---

## 3. 交付物

| 路径 | 说明 |
|---|---|
| `E:\dsh pr\woker2\tools\claude-worker.ps1` | 直调 Worker：`claude -p` + stdin UTF-8 + 超时 + JSON 结果；支持 `-Cwd / -AllowedTools / -AppendSystemPrompt / -Model / -OutputFormat / -TimeoutSec / -Stdin` |
| `E:\dsh pr\woker2\reports\2026-11-01_claude-code_任务报告.md` | 本报告 |

### 用法
```powershell
.\tools\claude-worker.ps1 -Prompt "审一下 X 文件，三行结论" -Cwd "E:\dsh pr\woker2" -TimeoutSec 300 -Json
Get-Content task.md -Raw | .\tools\claude-worker.ps1 -Stdin -AllowedTools "Read Grep"
```

---

## 4. 官方链路的三种修法（均未执行，需你点头）

| 方案 | 做法 | 代价 | 风险 |
|---|---|---|---|
| A. 清空 default-model 的路由 | 改 `cordis.patch.yml`，删掉 `models` 三条 + `model` | 所有子代理改回继承父路由（deepseek-flash），失去免费模型池与跨供应商故障转移 | 低；改回即恢复 |
| B. 升级插件到 2.1.12 | `dsh plugin add dsh-subagent-default-model@2.1.12` | 未知能否修复；2.1.11 起插件开始读 provider 能力（`inheritsParentContext`），但**只针对 fork** | 中；插件升级需重启宿主 |
| C. 给上游提 issue | 请求「provider 未声明 agentOptions 能力时跳过注入」 | 等待 | 无 |

> 本机教训复用：`dsh-subagent-default-model` 一旦改配置会立刻影响**下一次派发**（热重载），
> 但改 `cordis.patch.yml` 的条目结构可能需要重启宿主——会中断当前会话，故不在对话中途执行。

---

## 5. 环境快照（2026-11-01T19:20+08:00）

| 项 | 值 |
|---|---|
| dsh 桌面端 | 0.2.1-rc.3 |
| claude CLI | 2.1.251（native 安装，`autoUpdates:false`） |
| Claude 模型端点 | `https://api.deepseek.com/anthropic` / deepseek-v4-flash |
| 插件版本 | `dsh-subagent-default-model@2.1.8`（npm 最新 2.1.12） |
| claude-code 插件 | `@deepseek-ai/dsh-subagent-claude-code@0.2.1-rc.3` |
| 宿主能力校验 | `app.asar` L1918889 / L1921744（`UNSUPPORTED_CAPABILITY`） |
| PowerShell | 5.1（`.NET Framework`，无 `ProcessStartInfo.ArgumentList`/`StandardInputEncoding`） |

### 本报告新增的坑（值得记住）
1. `subagent_claude_code` 的错误信息只有一句 capability，**真正原因在另一个插件的注入逻辑里**——两插件冲突的典型形态。
2. PS 5.1 的 `ProcessStartInfo` 缺两个 .NET Core 属性，喂中文 prompt 必须走 `BaseStream.Write(bytes)`。
3. claude CLI 的 `unrecognized_model` 只是警告（DeepSeek 端点），不影响执行。

---

## 6. 未完成 / 风险

1. 官方链路**仍未打通**（需重启宿主，未获授权）。
2. 直调 Worker 与官方工具的行为差异：无 dsh 侧的完成事件、用量统计、会话身份；但换来了立刻可用。
3. `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` 已开——Claude Code 自己的团队机制可用，与本机 dsh AgentTeams 是**两套独立系统**，别混用同一任务。
4. 未验证 claude 在**长任务 / 大仓库**下的稳定性与超时表现。

---

## 7. 复现

```powershell
# 1. 确认官方链路失败（应报 UNSUPPORTED_CAPABILITY）
#    调 tools/subagent_claude_code 一次即可复现
# 2. 直调可用
.\tools\claude-worker.ps1 -Prompt "回复 WORKER-OK" -Json
# 3. 查看注入逻辑
Get-Content "$env:USERPROFILE\.dsh\profiles\desktop\node_modules\dsh-subagent-default-model\lib\index.js" |
  Select-Object -Skip 234 -First 8
```
