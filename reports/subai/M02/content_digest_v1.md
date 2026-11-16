# `content_digest_v1`：交付件「内容」的规范化摘要（规格 v1.1 + 自检 + 模式声明）

**用途**：`.blend` **不是逐字节可复现的**（同一输入三次 5 929 823 / 5 928 599 / 5 923 244 B），
所以「交付件能由代码重建」只能定义在**内容**上。本文件定义「内容」到底是什么，
并给出一个**能被别人复核**的算法与自检——否则「内容相同」只是自述，判据会恒绿。

实现：`reports/subai/M02/scripts/m02_content_digest.py`（纯 Python）。

| 版本 | 前缀（进哈希） | 含义 |
|---|---|---|
| v1.1 强摘要 | `content_digest_v1` | 全部必填字段齐全（含逐刚体属性） |
| v1.1 弱摘要 | `content_digest_v1_partial` | 缺字段，缺项**写进摘要自身**的 `__coverage__` |

## 一、两层身份（总控 18:08 的分层）

| 层 | 定义 | 要求 |
|---|---|---|
| **实例身份** | 某一份 `.blend` 自己的 sha256 | 跨次**不要求**相同；读数必须绑死「这一份」 |
| **可复现性** | 本文件的强摘要 `content_digest_v1` | 跨次**要求**相同 |

## 二、参与 / 剔除（逐条给理由）

**参与**：`rigids`（刚体总数）、`bodies[]`（逐刚体 `name`/`parent_bone`/`mass`/`kinematic`/
`collision_shape`/`collision_collections`/`friction`，按 `name` 排序）、`constraints_by_type`、
`chain_ratio`（round 6）、`mask`（`verdict`/`constraints_capped`/`skipped_count`/`constraints_needed`/
`constraints_added`/`constraints_already_blocked`/`readback_mismatch`）、`action`（`name`/`frame_range`）、
`scene`（`frame_start`/`frame_end`/`fps`）、`cache`（`is_baked`/`is_outdated`）。

**剔除**：

| 字段 | 理由 |
|---|---|
| 绝对路径（`blend`/`out`/`vmd`/`preset`） | 换目录不该改变内容；它们归 identity 记 |
| 时间戳（`started_at`/`finished_at`/`mtime`） | 与内容无关 |
| `.blend` 的 sha256 | 这是**实例身份**，跨次本来就不同 |
| `blender` / `python` 版本 | **环境上下文**：会影响数值，但不是「这份内容」；随件记在 facts 里，不进摘要 |
| `elapsed` | 与内容无关 |

**算法**：`sha256(<前缀> + "\n" + canonical_json)`，
`canonical_json = json.dumps(subset, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`。
前缀**进哈希**——换模式/换版本时摘要必然全变，避免「换了规格却看起来一样」。

## 三、v1.1 修掉的洞（总控 18:09 复现的那条，不是假设）

v1 的 `strict=False` 会**悄悄**跳过缺失字段照样出摘要：两份物理上不同的 facts 得到同一个摘要，
而摘要本身**看不出** `bodies` 被跳过。这正是「判据在缺料时不拒、还给出一个看起来合格的答案」。
v1.1 三条一起改，缺一条都不算修好：

| # | 改法 | 为什么这样够 |
|---|---|---|
| 1 | 弱摘要换**独立版本前缀** `content_digest_v1_partial` | 哈希输入第一行不同 ⇒ 强/弱摘要**数学上不可能相等**，不会被误当同一件事 |
| 2 | `__coverage__` **进摘要输入**：`{"mode", "version", "missing"}`（`rigids` 与 `len(bodies)` 不一致时另带 `body_count_mismatch`） | 弱摘要**自证它少了什么**；读者不必信任调用方 |
| 3 | 记录里带 `digest_mode: "strict" \| "partial"`，`--record-out` 直接落盘 | 模式写在结果里，不靠调用方记得 |

**并且 fail-closed 变成默认**：CLI 不带 `--allow-partial` 时缺字段一律**拒绝出摘要**（exit 2）。
此外三条「缺料」判红：`bodies` 键缺失、`bodies = []`（回读失败最常见的形状，不许当成「0 个刚体」）、
`rigids` 与逐刚体条数不一致（回读不完整）。

## 四、自检（`--selftest`，12 条，已跑，exit 0）

| # | 改动 | 期望 | 实测 |
|---|---|---|---|
| 1 | `bodies[1].kinematic` 翻转 | 变 | 变 |
| 2 | `bodies[0].mass` 改 | 变 | 变 |
| 3 | `scene.frame_end` 改 | 变 | 变 |
| 4 | `constraints_by_type` 条数改 | 变 | 变 |
| 5 | `mask.constraints_added` 改 | 变 | 变 |
| 6 | 只改路径/时间戳/版本 | **不变** | **不变** |
| 7 | 缺 `bodies` 键 + strict | **拒绝**（SystemExit） | 拒绝 |
| 8 | `bodies = []` + strict | **拒绝** | 拒绝 |
| 9 | `rigids=3` 但 `bodies` 2 条 + strict | **拒绝** | 拒绝 |
| 10 | 同一 facts，strict 摘要 vs partial 摘要 | **不同** | 不同 |
| 11 | 弱摘要自证 | `digest_mode=partial`、`missing=["bodies"]` 且 `"missing":["bodies"]` 出现在 canonical json 里 | 对 |
| 12 | 总控的洞（两份不同 facts，一份多带旁证 `mass_total_g`） | strict 双拒；partial 摘要即使仍相等也必须自证 partial | 闭合 |

自检基准值（`_mini_facts` 的强摘要）= `8bdeaa737b03733b24e825f19e395c06fd6a2496e1b4c5c4eb0c89f9c668ce0b`。

### 反向控制（证明自检会红，不是永远绿）

改在临时副本上（`tmp_ctrl/`，不入库），不动仓库脚本：

| 变异 | 结果 |
|---|---|
| A：删掉 `compute()` 里 strict 的拒绝（回到 v1 的 fail-open） | **4 条红**（第 7/8/9/12 条），exit 1 |
| B：`VERSION_PARTIAL = VERSION` 且不写 `__coverage__` | **3 条红**（第 10/11/12 条），exit 1 |

两条变异各自只打中它对应的性质——说明新增的 6 条不是摆设。

## 五、实测：三次重建报告（**报告级部分摘要**，`digest_mode = partial`）

`v1 = b3646cb0836b42b5c254a2b58355af7c78229278061011f4424f700bb2a79d33` **作废**：
那是 v1 非严格模式的产物，命名里没有任何「我少了什么」的线索，按总控 §三 不许再被引用。
v1.1 重算：

```
version        = content_digest_v1_partial
digest         = 3ff7c818a644f4033b4b503cf2f115b59b9f732f317a8957c61697194c25f826
digest_mode    = partial
missing        = ["action", "bodies", "cache", "mask", "rigids", "scene"]
canonical_sha256 = bbac2b344630d0457b73e62ab7319ba20009c437caad2cac6d5595a74cf60dc5（278 B）

out/subai/M08/rebuild_report.json                        同 digest
out/subai/M08/run_20261116_1804/rebuild_report.json      同 digest
out/subai/M08/run_20261116_1805/rebuild_report.json      同 digest
```

**这组数更强的限制**：`rebuild_report.json` 里**连聚合量都不全**——没有 `rigids` / `mask` / `scene` /
`cache` / `action`，脚本只从 `build.metrics` 取了 `constraints_by_type` 与 `chain_ratio`。
所以这份 partial 摘要实际只覆盖**约束类型条数 + 骨链比例**两项。

- **可以用它说明**：三次重建在「约束类型条数 + 骨链比例」这一层一致；
- **不可以用它说明**「内容确定 / 可复现」，**不可以进 T3**；
- 引用这个数的人，从 `version`/`missing` 两个字段就能自己看见它是 partial。

## 六、还没做到的（强摘要）

强摘要要 `bodies` 齐全，得由 `m02_m08_readback.py` 逐刚体回读供给；**它现在只回读掩码与缓存，
没有逐刚体属性**。所以：

- 下一次锁窗口内做：逐刚体回读 → 强摘要（`content_digest_v1`）→ 两个负控（kinematic 翻一位、
  改一条刚体质量，摘要必须变；只改路径/时间戳，必须不变）；
- 在那之前，「内容确定」这句话只到 partial 这一层，**不许**用它给 T3 背书。
