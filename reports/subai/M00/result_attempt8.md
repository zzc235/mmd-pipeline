# M00 attempt 8 · PASS（锁的输出编码 + `commit`/`scope` + 护栏与 status 硬化 + `check` 失败分形）

A4 / `ai/a4` / HEAD `13c4ff7` / 未 push。本笔覆盖 **两个提交**：`bf75ad0`（`measurements` + `check`
入口，总控已在它上面验过 8 组输入）+ `13c4ff7`（本笔主体）。三点式 vs `main` (`98ca37f`) 共
**10 个文件**，`files[]` 10 == 10。

## 一、`check` 的失败分家（D0 13:53 定死）

| 码 | reason_code | 判据 | 在本笔实测的输入 |
|---:|---|---|---|
| 0 | `OK` | 磁盘字节 == 规范字节，digest 自洽 | M04 记录（重出后的规范字节） |
| 3 | `SCHEMA_INVALID` | 能读能解析，但违反 schema | `interface` 是对象、`status` 不在枚举、`commit` 大写 |
| **5** | **`NOT_CANONICAL`** | schema 没问题，磁盘那份不是规范字节 | 2号 的真实 M04 attempt11（5633 vs 5291） |
| 4 | `UNREADABLE` | 读不出 / 不是合法 JSON | 不存在的路径、`{not json` |

**为什么必须分**：只有退出码是调用方能机械判的；`reason_code` 得读输出才知道，脚本作者一定会把 3
当一种情况处理。这是今天反复撞的「失败与不一致同形」里**唯一能机械消掉**的一处。

**exit 5 现在会点名差从哪来**（否则它只是个哑码）。分四类，处理办法完全不同：

| 类 | 诊断输出 | 改法 |
|---|---|---|
| 自建序列化 | `序列化本身不是规范形态（缩进/分隔符/键序）` | 落盘前用 `canonical_bytes()` |
| 顶层多写键 | `顶层多了不进哈希的键：summary` | 去掉，或接受 `sha256(file) != digest` |
| `tests[]` 多写字段 | `tests[] 行里多了不进哈希的字段：note` | 同上 |
| 值被改写 | `known_risks 折叠、路径归一、行重排` | 磁盘那份是手写的 |

**在 2号 的真实记录上验出来的**（不是构造的样本）：

```
$ python -m coordination.evidence check reports/subai/M04/evidence_m04_attempt11.json
NOT_CANONICAL 不是 canonical 字节：磁盘 5633 字节 vs 规范 5291 字节；规范 digest 应为 evidence/1:0be68a45…b75a
  tests[] 行里多了不进哈希的字段：note（只保留 cmd/exit/passed/failed/skipped）
exit=5
```

⇒ 这条记录**内容是对的**（digest 与 2号 公布的终值逐字节相同），只是它的 `tests[]` 行带 `note`，
而 `tests[]` 行会被 `normalize()` **重建**，所以 `sha256(文件) == digest` 这条等式对它不成立。
**不是篡改，但等式确实不成立**——这个区别现在一句话就能看见，不必再有人写 diff 脚本。

## 二、`evidence/1` 加两个可选键（D0 选 (b)）

| 键 | 约束 | 空值语义 |
|---|---|---|
| `commit` | `^[0-9a-f]{7,40}$`，不 strip，**不查该 commit 是否存在** | 空串 → `WRONG_COMMIT`（不是缺席） |
| `scope` | 空白折叠（同 `known_risks`） | 折成空串 → **缺席**，不进 canonical |

不对称是有意的：`scope` 为空是「没写范围」这个声明；`commit` 为空是「我以为我填了但它是空的」，
那是缺陷。不 strip 同理——哈希串上的空白是手误，静默吃掉它就会让同一份内容有两种写法同值。

`--help` 里写进了六个码/口径 + **能力边界**：`check` 只认形状与字节规范，**不重算**
`artifacts[]` 与磁盘是否一致，所以 `exit 0` 不等于 artifact 没被换掉。

## 三、六道验收输入：五道我独立复算，第五道只作自证

用规范实现 `coordination.evidence` 直接算（`goldstandards_attempt8.py`，随本笔入库）：

| 输入 | 期望 | 本笔实测 | 结论 |
|---|---|---|---|
| M04 无三键（旧基数） | `3c4489f6…` / 3791 B | `3c4489f6…` / 3791 B | 一致 |
| M04 + 仅 `measurements` | `22356081…` / 4808 B | `22356081…` / 4808 B | 一致（五方同值不变） |
| M04 + `measurements` + `commit`、无 `scope` | `37a40240…` / 4827 B | `37a40240…` / 4827 B | 一致 |
| M04 含三键（2号 终值） | `0be68a45…` / 5291 B | `0be68a45…` / 5291 B | **一致** |
| `scope=""` vs 缺席 | canonical 相同 | A == B，且 `'scope' in normalize(B)` 为 False | 一致 |
| M02 含三键 | `b837f933…` / 22465 B | 盘上还没有这份记录 | **未验**（1号 尚未落盘） |

**这张表的两处口径，先说清**：

1. 前四条用的是**磁盘上 2号 那份真实记录**逐层剥键，不是我构造的样本；`0be68a45…` 与 2号 的公布值
   逐字节相同，说明「`commit` 原样进 canonical + `scope` 折叠」这一口径在两个独立实现上一致。
2. `b837f933…` 我算不出来——它需要 1号 生成器的那份 dict。**能独立复算的我复算，只能自证的我标明
   是自证**，不混着说。

## 四、编码契约的两头都钉（main 那处红）

`coordination/cli.py` 新增 `ensure_utf8_stdio()`，`lock` / `status` / `evidence` 的 `main()` 开头调用；
测试侧一律把子进程钉成**最坏环境** `PYTHONIOENCODING=gbk`，父进程按 UTF-8 解码并断言成功、且
`stdout.strip()` 非空（`None` 与空串同一类坑）。

新增 `tests/test_cli_utf8_output.py` 是**第三类判据**的落地：凡用子进程调用的 CLI，必须有一条
「子进程 GBK、父进程 UTF-8 解码仍成功」的测试。它自己带**负控**——一个不 reconfigure 的朴素 CLI
在同一环境下必须失败；否则这条测试本身可能是假绿。

## 五、护栏三处假阴性（3号 / 2号 / 1号 各撞一次，同一族）

| 处 | 改法 |
|---|---|
| `scan_tree` 的两个静默 `continue` | 返回 `(violations, scanned, skipped)`，`skipped` 是 `[(path, reason)]` **列表** |
| `tracked_py` 的 `os.walk` 回退 | `git ls-files` 失败 → `RuntimeError` 判红（这个仓库永远是 git 仓库，判红没有代价） |
| opt-out 只看 `lineno` | 扫 `lineno..end_lineno` 整段（`# noqa` 常落在调用最后一行） |

输出固定 `scanned=N  violations=0  skipped=0`，且断言 `skipped == []`、`scanned >= 50`（防扫描器空转）。

## 六、`status.py` 待批项全量聚合

旧实现按「同一任务后续任意裁决即清账」，于是 `D-20261116-075`（掩码结构性未接线）被后来的
`D-083` **挤掉**——没有任何人回答过它，它只是不再是最新一条。**这是最坏的一类状态载体说谎：
消失得没有痕迹。** 现在跨任务跨时间全量聚合，只有后续裁决**显式提到它的 `decision_id`** 才算关闭；
时间顺序本身不构成回答。真实台账上重渲染：待批项从 1 条回到 4 条（D-017 / D-023 / D-028 / D-068）。

## 七、验证

| cmd | exit | 结果 |
|---|---:|---|
| `discover`（默认环境，未设 `PYTHONIOENCODING`） | 0 | **343 passed / 0 failed / 15 skipped**（18.9 s） |
| `discover` + `PYTHONIOENCODING=utf-8` | 0 | **343 passed / 15 skipped**（19.4 s） |
| `discover` + `PYTHONIOENCODING=gbk` | 0 | **343 passed / 15 skipped**（19.0 s） |
| `python -m unittest tests.test_subprocess_encoding` | 0 | 13 passed，`scanned=128 violations=0 skipped=0` |
| `python -m coordination.evidence check <2号 的 M04 记录>` | **5** | `NOT_CANONICAL` + 点名 `tests[].note` |
| `python -m coordination.evidence --help` | 0 | 四个码 + 能力边界都在 |

## 八、`known_risks`

- `check` 只认形状，**不重算** `artifacts[]` 与磁盘是否一致；`exit 0` 不等于 artifact 没被换掉。
- 退出码 5 会在「`tests[]` 行带注释字段」的**合法**记录上触发——本笔把它做成可读诊断，但没有权力
  宣布那种写法合规或不合规，那是记录规范的事。
- 六道金标里第五道（M02 `b837f933…`）**未验**：盘上还没有那份记录，只能等 1号 真跑后按他自己的
  生成器比。
- 护栏只扫 `git ls-files`（能进 main 的），`reports/` 下的辅助脚本不在范围内——1号 与 2号 的同类缺陷
  要靠各自树上的扫描器，护栏兜不住。
- `mmdpipe/stage.py` 的掩码通道（`collision_group_mask` → `collision_collections` 位 +
  `DISABLE_COLLISIONS` 约束）**本笔未做**，是队列里的下一件。
