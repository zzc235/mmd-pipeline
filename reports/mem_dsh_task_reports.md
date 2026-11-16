---
name: dsh-task-reports
description: 任务报告归档制度——每次任务完成后在 桌面\ai用\dsh use 留一份「修改详情+当时快照」的报告，作为系统扩张基线
metadata:
  node_type: memory
  type: instruction
---

# 任务报告归档制度（2026-11-01 志诚定）

## 规则
**每次任务完成后**，必须在 `C:\Users\zzc\Desktop\ai用\dsh use\` 留一份报告：

- 报告：`<YYYY-MM-DD>_<任务简称>_任务报告.md`
- 快照：`snapshot-<YYYY-MM-DDTHHmm>.json`（机器可读，方便以后 diff）
- 模板：同目录 `_模板_任务报告.md`
- 目的：**为后续扩张这个系统提供基线**——六个月后能靠它还原“当时是什么样、为什么那么改”。

## 报告必须包含
1. 一页摘要（做了什么 / 结果如何 / 还差什么）
2. 交付物清单（路径 + 大小 + SHA256 前 16 位 + 作用）
3. 逐文件修改详情：新增 / 修改 / 删除 分类，改前→改后 + 原因，**并显式声明本次未触碰的高风险文件**（`~/.dsh/AGENTS.md`、`profiles/*/cordis.patch.yml` 等）
4. 关键决策记录（决策 / 理由 / 被否决方案）
5. 实测证据（命令、数据、耗时；**失败记录必须写全**：哪条路、什么错、试几次、为什么停）
6. 环境快照（主机与运行时版本矩阵、profile bundles、`cordis.patch.yml` SHA256、交付物哈希、缺口清单）
7. 后续扩张建议（优先级 / 依赖 / 预计）+ 未完成与风险 + 复现步骤

## 已有报告
- `2026-11-01_superagent-lite_任务报告.md` — Super-agent 本机版落地 + 原型摸底 + GitHub 通道诊断

## 惯例
- 报告写完在对话里给一句“报告已归档到 …”，不要贴全文。
- 报告属于交付物，不算“额外流程”，做完任务立刻写，别攒着。

相关：[[deepseek_harness]]、[[dsh_multiagent]]
