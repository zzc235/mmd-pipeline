# 协调层 v2 架构（14 号令落地版）

> 目标一句话：**D0 不再靠读叙事判活，只读闸门结果 + 一枚验证令牌，然后给一枚受控裁决
> 或 `NEEDS_HUMAN`。**

改造前的状态（都是实测出来的，不是推测）：

| 症状 | 实测 |
|---|---|
| 状态表自称权威，但没人执行 | `task_status.json` 说 9 个任务，`out/subai/coordination/board.db` 里 0 行 |
| board 有两个文件 | 真库 `out/subai/coordination/board.db` = 90112 B；`coordination/board.db` = **0 B** 空壳 |
| 派工白名单漏了 M00 | `dispatcher.LANES` 里没有 P0 车道，M00 永远不会被派出 |
| 裁决词自由生长 | 162 条裁决 / 23 种 kind / 128 种 reason_code，没有一张表说哪些合法 |
| 待批项会蒸发 | `D-075` 被后来的无关裁决挤掉，无人回答却从视图消失 |
| 假绿两类高发 | 错工作树（`sys.path.insert(0, 另一棵树)`）、旧缓存回放读数当重解 |

---

## 1. 四层

```
L4  视图    status（对账视图） · dispatcher（派工计划） · human_gate list
              ↑ 只读，不持有事实
L3  裁决    decisions.jsonl（append-only） —— 每枚都必须落在 7 个动作词之一
              ↑ 唯一的写入口：coordination.taxonomy.append()
L2  证据    evidence/1 + 快照库 + 闸门（gates） + 开工前置（preflight）
              ↑ 「能不能算过」与「该不该开始」两套机器判据
L1  状态    out/subai/coordination/board.db（sqlite，唯一状态事实源）
              ↑ 由 task_status.json 单向灌入：coordination.sync_board
```

### L1 状态：只有一个库

- 事实源 = `out/subai/coordination/board.db`。它是**四棵树共享的那一个**（跟锁同一个根），
  跟着仓库走就没有互斥/没有共识。
- `coordination/board.db` 是 0 字节空壳，`coordination/board_path.md` 里写明了原因与后果：
  谁把它当库，谁就在读一个空世界，而且**读空库不会报错**。
- `coordination/task_status.json` 不再自称权威：它是**输入**，用
  `python -m coordination.sync_board [--dry-run]` 单向灌进 board（幂等，加
  `legacy_status` / `state_reason` 两列记录来源）。方向永远是一条：json → db。

### L2 证据：闸门挡在入口，前置挡在开工

两套判据，两个入口，一套 reason_code 闭集：

| 模块 | 时机 | 回答的问题 | 失败码 |
|---|---|---|---|
| `coordination/gates.py` | 提交时（`Board.submit`） | 这份证据能不能过 | `GATE_FAILED` / `MISSING_EVIDENCE` / `EVIDENCE_SCOPE_MISMATCH` / `FRESH_SOLVE_REQUIRED` / `PROVENANCE_INVALID` / `SNAPSHOT_INVALID` / `LEASE_EXPIRED` |
| `coordination/preflight.py` | 开工前 | 这份活该不该开始 | `PROVENANCE_INVALID` / `CAP_UNMET` / `GATE_FAILED` / `LEASE_EXPIRED` / `OWNERSHIP_VIOLATION` |

闸门包（`gate`）八条判据、前置五条判据都在各自模块的 docstring 里逐条写明，
**每条都有红样本 + 绿样本测试**（`tests/test_coordination_architecture.py`）。

**产地（provenance）有一个正式出口：`external_roots`。** 起因是实测缺陷：M06 的正本工具与产物
按 `evidence_hash_v1 §4.1` 就在外部树（`E:\flowhmr-test\tools\manifest.py`），而产地判据原来只有
「在 worktree 下」一条路 ⇒ 对 M06 车道**结构性误杀**。现在的规矩（`coordination/provenance.py`，
两个闸门共用一份实现）：

- 默认仍只认 worktree；
- 外部树必须**显式声明** `external_roots`（绝对路径列表），落在其下的路径判过、但在结论里记为
  「外部树种」——可见，不是静默放行；
- 不声明 ⇒ 照旧 `PROVENANCE_INVALID`；
- 外部根是相对路径、或落在 worktree **内** ⇒ `GATE_FAILED`（不许用「外部」给树内路径洗白）；
- `module_provenance` 为空 ⇒ 判红（空对象能过是漏洞）。

向后兼容不是静默放行：老证据（没有 `truth_tier`、没有 `gate`）走 legacy 通道，
并在 board 上记 `gate.legacy_skipped` 事件——「这份提交没有闸门」这个事实必须可见。

### L2b 证据快照：哈希证明「那一刻」，快照保证「还能重算」

`reports/` 曾经不进 git ⇒ 只记 `sha256` 的 artifact 在文件被改名/移走/改写后**永久无法复原**。
（2026-11-16 16:44 Human 定：`reports/` 纳入 git，提交 `e7d9916`。快照规矩**不撤**——
git 保证「提交过的那一版」可复原，快照保证「记录引用的那一版」可复原，两者不是同一件事。）
`known_limits.md` 的 `7ac68dd6…` 已经这样失效过一次。新规：

- 文本类 artifact 必须落原字节副本到 `out/subai/_evidence_store/<sha16>/<文件名>`；
- 记录里写 `path` + `sha256` + `snapshot`；
- 只写不改：目标已存在且字节不同 ⇒ `SNAPSHOT_INVALID`，绝不覆盖。

唯一入口 `coordination/evidence_store.py`；政策全文 `coordination/evidence_store_policy.md`。

### L3 裁决：动作词闭集

`coordination/decision_taxonomy.json` 是唯一词表，`coordination/taxonomy.py` 是唯一执行点：

- `allowed_decision` = 7 个**动作**词（ACCEPT_MERGE / ACCEPT_INTERFACE / RETURN_FIX /
  BLOCK / REASSIGN / NEEDS_HUMAN / CANCEL）。`RULING`、`CORRECTION` 是历史 kind，
  **不在动作集内**——一枚裁决必须能改变状态或明确交给 Human，否则它就只是评论。
- `allowed_reason_code` = 24 个。词表外的 reason_code 不许当正常裁决落库，转
  `NEEDS_HUMAN` + `SCOPE_CHANGE`（加新词是 Human 权限）。
- `legacy_map`：162 条历史逐条有映射，**不改原文**（改历史等于伪造历史）。

### L4 视图：只读，且必须互相对得上

- `coordination/status.py --check`：C1–C8 八条对账，任何一条不过就 exit 3。
  其中 C6 专门核「`status` 聚合出来的待批项」与「`human_gate list` 的清单」
  **逐条相同**——两个出口不许各说一套。
- `coordination/dispatcher.py`：只出计划不启动任何 AI；board 空而状态表非空 ⇒
  `MISCONFIGURED_EMPTY_BOARD`（空库不是"空闲"，是没灌库）。
  P0 车道（M00 协调平台）**必须 D0 显式批准**才派单：board 事件 `p0.approved`
  且 payload 里 `by == "D0"`，或命令行 `--approve-p0`。
- `coordination/human_gate.py list`：待批项的唯一出口（复用 `status.pending_human()`）。

---

## 2. Human gate：只有显式回答才关闭

```
python -m coordination.human_gate list
python -m coordination.human_gate resolve --id D-20261116-017 \
       --decision RETURN_FIX --by Human --note "按 RETURN_FIX 重出"
```

- `--by` 只接受 Human。`by=D0` / `by=总控` / `by=模块负责N` 一律 `NOT_HUMAN` 拒。
- 关闭 = 追加一条新裁决，里面写 `resolves: ["D-20261116-017"]`；
  `pending_human()` 的判据是「后续裁决**显式提到**它」，所以超时不关、
  无关裁决顺带不关、`D-075` 那种被挤掉的情况 structurally 不可能再发生。
- 已关闭再关 ⇒ `ALREADY_CLOSED`；从未打开 ⇒ `NOT_FOUND`；词表外回答 ⇒ `BAD_DECISION`。
- **D0 不代关。** 这条闸门存在的意义就是「谁欠的答复由谁给」。

---

## 3. 真值档（truth_tier）

`evidence/1` 新增可选字段 `truth_tier`（进 canonical，参与哈希）：

| 档 | 含义 | 能干什么 |
|---|---|---|
| `T0` | 单元/合成 | 证明逻辑，不证明场景 |
| `T1` | 真实小场景 | 证明能跑通，不证明尺度 |
| `T2` | 代表性逐帧 | 能出"结论级变化" |
| `T3` | 交付尺度 | **M08 只认这一档** |
| `T_DESCRIPTIVE` | 只作描述 | 不得作为结论依据（`cache_replay` 读数落这一档） |

机器的两条硬规矩：

1. `task_id` 以 `M08` 开头的闸门包，`truth_tier != T3` ⇒ `EVIDENCE_SCOPE_MISMATCH`；
2. `pose_source == cache_replay` 却报 T2/T3 ⇒ `EVIDENCE_SCOPE_MISMATCH`。
   （这是 `D-154` 的教训：A0 v1 判"仪器看不见"其实是缓存回放，读数根本不是碰撞状态的函数。）

老记录不带 `truth_tier`，哈希逐字节不变——**迁移历史等于篡改历史**，不迁移。

---

## 4. D0 现在读什么

改造之后，D0 的每个回合只有三个输入、一个输出：

| 输入 | 命令 | 只看什么 |
|---|---|---|
| 状态对账 | `python -m coordination.status --check` | `state` / `conflicts[]` |
| 闸门结果 | `Board.submit` 的返回或 `gate.legacy_skipped` 事件 | `reason_code` + `checks[]` |
| 待批项 | `python -m coordination.human_gate list` | 7 条，逐条列明谁欠回答 |

| 输出 | 形式 |
|---|---|
| 一枚受控裁决 | 7 个动作词之一 + 24 个 reason_code 之一，走 `taxonomy.append()` |
| 或 `NEEDS_HUMAN` | 词表外概念、Owner 权限、不可逆动作 |

**D0 不再做的事**：不再自己读叙事判断"看起来完成了吗"，不再用自由文本 decision 改状态，
不再替 Human 关闭待批项，不再用 `coordination/board.db` 那个空壳当状态源。

---

## 5. 边界（这套东西不解决什么）

1. **闸门只认形状**：`evidence check` 过只说明"规范字节 + schema 合规"，不重算
   `files[]`/`artifacts[]` 与磁盘是否一致——那是生产者自证的反面，必须由 D0 或第三方复算。
2. **preflight 不保证结论正确**：它挡的是"必然返工"（错树、cap 不够、计划跳过、
   无租约、抢占产物），不挡"跑出来是错的"。
3. **Human gate 只管关闭路径**，不评价回答质量；回答错了照样落库，靠 `resolves` 可追溯。
4. **业务模块一律未动**：本轮只改 `coordination/` 与协调层测试；`mmdpipe/`、
   PMX/VMD/BLEND 零改动（14 号令 §2 的硬边界）。
