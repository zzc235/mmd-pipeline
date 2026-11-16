# `content_digest_v1`：交付件「内容」的规范化摘要（规格 + 自检 + 已知弱处）

**用途**：`.blend` **不是逐字节可复现的**（同一输入三次 5 929 823 / 5 928 599 / 5 923 244 B），
所以「交付件能由代码重建」只能定义在**内容**上。本文件定义「内容」到底是什么，
并给出一个**能被别人复核**的算法与自检——否则「内容相同」只是自述，判据会恒绿。

实现：`reports/subai/M02/scripts/m02_content_digest.py`（纯 Python，`VERSION = "content_digest_v1"`）。

## 一、两层身份（总控 18:08 的分层）

| 层 | 定义 | 要求 |
|---|---|---|
| **实例身份** | 某一份 `.blend` 自己的 sha256 | 跨次**不要求**相同；读数必须绑死「这一份」 |
| **可复现性** | 本文件的 `content_digest_v1` | 跨次**要求**相同 |

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

**算法**：`sha256(b"content_digest_v1\n" + canonical_json)`，
`canonical_json = json.dumps(subset, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`。
版本串**进哈希**——换版本时摘要必然全变，避免「换了规格却看起来一样」。

## 三、自检（`--selftest`，6 条，已跑）

| 改动 | 期望 | 实测 |
|---|---|---|
| `bodies[1].kinematic` 翻转 | 变 | 变 |
| `bodies[0].mass` 改 | 变 | 变 |
| `scene.frame_end` 改 | 变 | 变 |
| `constraints_by_type` 条数改 | 变 | 变 |
| `mask.constraints_added` 改 | 变 | 变 |
| 只改路径/时间戳/版本 | **不变** | **不变** |

## 四、实测：三次重建的内容摘要相同

```
out/subai/M08/rebuild_report.json              b3646cb0836b42b5c254a2b58355af7c78229278061011f4424f700bb2a79d33
out/subai/M08/run_20261116_1804/rebuild_report b3646cb0836b42b5c254a2b58355af7c78229278061011f4424f700bb2a79d33
out/subai/M08/run_20261116_1805/rebuild_report b3646cb0836b42b5c254a2b58355af7c78229278061011f4424f700bb2a79d33
```

## 五、**已知弱处（必须写在纸上）**

上面那次是**弱摘要**：`rebuild_report.json` 里没有逐刚体属性，`bodies` 缺项时脚本按非严格模式算，
摘要只覆盖 `rigids`/约束/`chain_ratio`。**弱摘要不足以证明「交付件的物理内容一致」**——
它没看质量、kinematic、父骨、碰撞组。

**强摘要**（`bodies` 齐全）要由 `m02_m08_readback.py` 的逐刚体回读供给，**当前它只回读掩码与缓存，
还没逐刚体属性**。所以：

- 下一步在补丁 + 动作那一步落地、重跑交付件时，同一次锁窗口内补上逐刚体回读，然后算**强摘要**；
- 在那之前，「内容确定」这句话只到弱摘要这一层，**不许**用它给 T3 背书。
