# M00 · result（attempt 3）：`coordination/status.py` —— 任务级状态派生视图（只读）

> 席位 A4 · 分支 `ai/a4` · 本笔 HEAD `e35253e`（父 `0321505`）· 2026-11-16 13:32
>
> 状态：**PASS**。M00 欠的最后一块：`task_status.json`（权威表）与 `decisions.jsonl`（历史）的对账视图。

## 1. 它是什么

```powershell
python -m coordination.status
# 或指定文件
python -m coordination.status --status <task_status.json> --decisions <decisions.jsonl>
```

**只读**：不写任何文件（有一条测试专门盯这个：跑前跑后目录里所有文件的 `st_mtime_ns` 必须一模一样）。

输出三块：

| 块 | 内容 |
|---|---|
| 表 | `task | status | 最后裁决 id | next`，按任务编号排序 |
| 小计 | `PASS 3 / PARTIAL 5 / BLOCKED 0 / NOT_STARTED 1` |
| 待 Human 批项 | `decisions.jsonl` 里带 `human_approval_required` 且**其后没有针对同一任务的新裁决**的条目 |

## 2. 退出码与「应当被拒的输入」

| 退出码 | 含义 | 应当被拒的输入（都有测试） |
|---:|---|---|
| 0 | 正常 | — |
| 2 | 用法错误 | argparse 自己的退出码 |
| 3 | 表与历史冲突 | ① 状态表里有、裁决历史里没有（**`NOT_STARTED` 除外**）；② 历史里有、状态表没登记；③ `status` 不在 `PASS/PARTIAL/BLOCKED/NOT_STARTED` 里；④ `tasks` 空或不是对象 |
| 4 | 读不到 | 文件不存在 / 不是合法 JSON / 某行不是 JSON / 不是对象 |

**两条自己撞出来的取舍，写在这里比藏在代码里好**：

1. **`NOT_STARTED` 允许没有裁决**。最初按「表里有、历史里没有就报错」实现，拿 main 上的真表一跑，
   `M08` 立刻被判冲突——可 `M08` 就是**还没开工**，没有裁决是对的。所以例外只留给 `NOT_STARTED`。
2. **`task_id` 不是 `Mxx` 形式的裁决不参与对账**。真历史里有 `A3` / `LANE` / `LEASE` /
   `RECORD-CORRECTION` / `SPEC` 五类条目（席位、通道、租约、勘误），它们在表里没有对应任务行。
   视图把它们计数后列出来，不当冲突，也不静默丢弃。

## 3. 拿 main 上的真表跑过（不是只跑 fixture）

| 场景 | 命令 | exit | 输出要点 |
|---|---|---:|---|
| 真表 + 真历史 | `python -m coordination.status --status <main 的 task_status.json> --decisions <main 的 decisions.jsonl>` | **0** | 9 个任务一行一个；`M08 NOT_STARTED （无）`；小计 `PASS 3 / PARTIAL 5 / BLOCKED 0 / NOT_STARTED 1`；「非 Mxx 的 5 类」；**待 Human 批项 1 条（`D-20261116-023`，M06 台账扩容/授权）** |
| 造一个表里有、历史没有的 `M99` | 同上换 `--status` | **3** | `表与历史冲突：状态表里有、裁决历史里没有的任务（且状态不是 NOT_STARTED）：M99` |
| 非法 JSON | 同上换 `--status` | **4** | `读不到：状态表读不成 JSON：…（Expecting property name enclosed in double quotes: line 1 column 3）` |

真表的最后裁决对得上：`M02 → D-20261116-061`、`M04 → D-20261116-062`、`M07 → D-20261116-059`。

## 4. 测试

`tests/test_status_view.py` **13 条**（全部纯 Python、临时目录 `tempfile.mkdtemp`，不动仓库文件）：

- 正常路径；最后裁决取最新一行；表/历史双向冲突；`NOT_STARTED` 免裁决；
- 非法 JSON → 4；文件缺失 → 4；`status` 枚举非法 → 3；`tasks` 空 → 3；
- 非 `Mxx` 的 `task_id` 被忽略而不是报错；`human_approval_required` 被后续裁决清账；
- 渲染含表头/待批项；**只读**（前后 mtime 全等）。

全量：`python -m unittest discover -s tests -t tests -p "test_*.py"` → **264 passed / 0 failed / 15 skipped**（16.4 s，exit 0）。

## 5. 已知限制

1. 默认路径指向**本仓库**的 `coordination/task_status.json`；我的分支还没并 main 那一笔，
   所以本地不传参数跑会 `exit 4（读不到）`——合并后即正常（本轮已验证方式是显式 `--status/--decisions`）；
2. 「待 Human 批项」的判定是**同一任务后续任意裁决即清账**，不区分该裁决是否真的回应了那条待批项（口径够用，但别当审计）；
3. 视图不校验 `updated` 字段的时间格式，也不校验 `reason` 是否为空；
4. 没有接进 `dispatcher`（分流只写 `dispatch.json`，两者互不依赖）。
