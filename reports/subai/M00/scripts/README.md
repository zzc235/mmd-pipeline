# M00 / M07 探针脚本（镜像入仓）

## 为什么有这份目录

这些脚本原先只存在于 `out/subai/.../scripts/`，而 **`out/` 是产物树、不进 git**。
后果与 `2号` 的快照、`3号` 的六个控制脚本是同一类：

> **干净 checkout 上这些脚本不存在** —— 报告与消息里引用的「怎么量出来的」在仓库里没有对应物。

`claim_shape_rules.md` 第十三条（快照账本必须在干净 checkout 上可复现，2026-11-16 立）正是冲这个来的。
所以把**方法**（脚本）镜像进仓，**读数**仍留在 `out/` 的产物树里，两者在报告里成对引用。

## 约定

- 本目录的文件是 `out/` 那份的**逐字节副本**，不另行修改。改了就要同时改两处并更新下表的 `sha256`。
- 读数列在 `reports/subai/M00/measurements.json`、`evidence_m00_attempt*.json` 与
  `reports/subai/M07/evidence_m07_attempt*.json` 里；产物（`.json`/`.blend`）在产物树。
- `tests/test_reports_scripts_tracked.py` 盯三件事：**目录里每个文件都在下表里**、
  **下表里每个文件都在仓里**、**每个 sha256 与文件内容一致**。少一个、多一个、改一个字节都会红。

## 清单

| 文件 | sha256 | 干什么 |
|---|---|---|
| `M00/scripts/plan_324_probe.py` | `6141bbd11c10522e…` | 在真 Blender 里跑 `mask.plans()`，产出 `plan_324.json`（`needed/already/to_add/release_pairs/blocked_before`） |
| `M00/scripts/selfcheck_plan_numbers.py` | `7edaacb95144c45f…` | 对 `plan_324.json` 的离线自检（17 条，含「按不存在的键取值会静默成空」那类反控） |
| `M00/scripts/real_bake_probe.py` | `1a704f7b614b7558…` | `stage_bake()` 真机首跑：内存窗口烘焙 + 契约 B 探针 + 件 sha 前后比对 |
| `M00/scripts/preflight_delivery_spec.py` | `5e3abbcf13632e1c…` | preflight 请求生成器：只认显式来源，不从对话里抄数 |
| `M00/scripts/check_taxonomy_fix.py` | `0004ea045f9dd644…` | 裁决词表越界记录（`supersedes`）的只读核验 |
| `M07/scripts/real_addon_probe.py` | `69018cccf520719d…` | 扩展装上 / 没装两态的读数探针（`get_rna_type()` vs `hasattr`） |
| `M07/scripts/run_real_addon_recheck.py` | `829dfaef3854c09c…` | 隔离仓库跑两进程复测，比对全局 `userpref.blend`/`user_default` 摘要 |

> 观察口径笔记不在本目录（它不含读数，只在仓里的 `reports/subai/M07/probe_api_availability.md`）。

## 一处要提醒的边界

镜像的是**当时的**脚本。若 `out/` 下的那一份在之后被改过，本目录不会自动跟上——
这正是上面第三条测试存在的理由：**它盯的是「仓里这份是不是清单说的那份」，不是「它是不是最新」**。
