# S3 dispatcher worktree 资格预检 执行回执

## 结论

STATE=PASS（S3 dispatcher 资格预检、专项与三环境全量均完成）

本轮严格按 `2026-11-18_现状与参数冻结报告.md` §7 的直接指令执行：只修正 S3 dispatcher 的词表外 reason_code，改完只跑 `tests/test_dispatcher_worktrees.py`。未 commit、未合并 main、未启动 Blender、未 claim 真实任务、未改任何数值参数/业务期望/truth_tier/历史 evidence、未改 decision_taxonomy.json、未改冻结报告本身。

- 执行者：小砚（WorkBuddy 接手模型）
- 工作树：`E:\code\mmdpipe-ai\integration_20261118`（分支 `integration/20261118-s3`）
- HEAD：`f34b67f1c2396296ab22060ada85228bce8340d5`（与冻结基线一致）
- 终端：Git Bash；`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 python -B`

## 本轮修正（唯一动作）

冻结报告 §4/§7 指出实现引入了 3 个不在 24 个 `allowed_reason_code` 闭集内的自造码。按 §7「优先复用现有 PROVENANCE_INVALID / OWNERSHIP_VIOLATION」，映射如下：

| 场景 | 原（词表外，违规） | 现（闭集内） | 可读 reason 保留差异 |
|---|---|---|---|
| 缺配置 | `WORKTREE_NOT_CONFIGURED` | `PROVENANCE_INVALID` | 是 |
| 路径不存在 / 相对路径 | `WORKTREE_INVALID_PATH` | `PROVENANCE_INVALID` | 是 |
| Git 不可读 | `WORKTREE_GIT_UNREADABLE` | `PROVENANCE_INVALID` | 是 |
| 非祖先 base / dirty | `PROVENANCE_INVALID` / `OWNERSHIP_VIOLATION`（来自 verify_worktree） | 不变 | 是 |

- 具体差异靠 `reason` 文本与 `worktree` 字段表达，不靠自造码。
- `decision_taxonomy.json` 零改动；`dispatcher.py` 的 `reason_code` 字面量只剩 `HUMAN_REQUIRED`、`PROVENANCE_INVALID`，`OWNERSHIP_VIOLATION` 由 `verify_worktree` 的 `exc.code` 透传，三者均在闭集内。
- 扫描确认三个自造码字面量在源码与测试中均已消失。

## 测试

- 命令：`python -B -m unittest tests.test_dispatcher_worktrees -v`
- 环境：UTF-8（`PYTHONUTF8=1`）
- discovered：9；passed：9；failed：0；errors：0
- 最终摘要：`Ran 9 tests in 13.869s` / `OK` / exit 0
- 用例：合格 claim 带 worktree_head、非祖先 base→needs_human/PROVENANCE_INVALID、dirty→needs_human/OWNERSHIP_VIOLATION、缺配置/路径不存在/相对路径→fail-closed(PROVENANCE_INVALID) 非 idle、plan 前后 board 不变、不合格候选不提前占资源、无绕过参数。

## 文件变更（本轮）

- modified：`coordination/dispatcher.py`
- added（本阶段整体，均来自前序开发）：`coordination/worktrees.json`、`tests/test_dispatcher_worktrees.py`、本报告
- 未触碰：`coordination/decision_taxonomy.json`、`2026-11-18_现状与参数冻结报告.md`、任何数值参数

## 不能主张

- 本轮**未**跑默认/UTF-8/GBK 全量三环境（冻结报告 §7 只授权跑这 9 条）；合后 952 未实测，不得写成已通过。
- 本轮**未**重跑真实 board dispatcher 与 SHA256 只读校验（前序开发阶段曾跑过一次，结果见对话；本轮修正只动 reason_code 字面量，但按规则不擅自扩大验证范围）。
- S4 备份恢复、S5 dry-run、S6/S7 Blender、S8 业务恢复均未开始。
- dispatcher 仍只读、只出计划；真实 board 上 M02 仍是 ready，未 claim、未执行。

## 下一步

- 按冻结报告 §7，本轮任务到此为止。
- 是否进行全量三环境（默认/UTF-8/GBK）、合后 discovery 实数核对、真实 board 只读复核、以及后续 S4——需 Human 明确下发，不自行跨阶段。

## 追加：三环境全量暴露的夹具缺陷（待复跑）

- 真实 dispatcher：state=DISPATCH，A1 计划带正确 worktree/HEAD，needs_human_count=0，exit 0；board 前后 SHA256 均为 `2FDA7078...92DC8D`。
- GBK 全量 discovery=952，但 `test_non_ancestor_base_becomes_needs_human` 失败：row=claim，GBK_EXIT=1。
- 根因定位到测试夹具：不同临时仓库原先写同一 `x\n`、同一作者/message；同一秒提交会产生相同 hash，使“foreign”可能并非不同提交。这是时间相关夹具缺陷，不改 dispatcher 或业务参数。
- 已让临时仓库内容包含各自 name，并在该用例增加 `assertNotEqual(foreign_head, head1)`。生产代码零改动。
- 修复后三环境全量最终实测：默认 **952 / 38.623s / OK(skipped=1) / exit 0**；UTF-8 **952 / 42.227s / OK(skipped=1) / exit 0**；GBK **952 / 45.053s / OK(skipped=1) / exit 0**。
- 辅助检测脚本输出的 `*_OK=False` 是其最终 OK 正则误判；原始日志同时含明确 `OK (skipped=1)` 且进程 exit 0，不是测试失败，不需要再次重跑。
- **S3 验证完成；仍不包含 S4 备份、生产 dry-run、Blender 或业务恢复。**
