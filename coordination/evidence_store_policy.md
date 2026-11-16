# 证据快照政策（D-159 落地）

> 一句话：**哈希证明「那一刻」，快照保证「此后还能重算」。** 只有哈希没有副本，
> 一条历史记录就会在文件被改名/移走/原地改写之后永久失效。

## 1. 为什么有这份文件

`known_limits.md` 在 `D-20261116-121` 时的字节是 `7ac68dd6…`。到 `D-20261116-157`
想复核时已经取不回来了：

| 尝试 | 结果 |
|---|---|
| 回退到 `7ac68dd6…` 对应的版本 | 不可能：漂移在 15:0x 追加 `D-133`/`D-134` 时就开始了 |
| 从 git 取 `f3fd0e1:reports/...` | `does not exist`——**`reports/` 不进 git** |
| 全盘搜索副本 | 无 |

于是那条哈希只能标记为**已失效**。这不是谁的疏忽，是「用哈希当存档」这个构造本身的洞。

## 2. 规矩

1. 每笔 `evidence` 记录里 **文本类 artifact**（`.md` / `.json` / `.txt` / `.log` / 脚本）
   除 `path` + `sha256` 外，**必须**再写 `snapshot`。
2. 快照存 **原字节**，不做 LF 归一、不加 BOM、不重新序列化——副本要能直接替换原件。
3. 落点固定：

   ```
   out/subai/_evidence_store/<artifact_sha256 前 16 位>/<原文件名>
   ```

   目录名用哈希前缀：同一份字节全世界只有一份副本；路径可读、可 `ls` 核对。
4. **只写不改**。目标路径已有副本且字节不同 ⇒ 报 `SNAPSHOT_INVALID`，绝不覆盖
   （覆盖等于销毁证据，而且是最不容易发现的那种）。
5. 声明 `sha256` 与磁盘不符 ⇒ 拒绝写快照（`HASH_BASIS_INVALID`）：
   不允许「先存起来再说」，那会把错误字节永久固化。
6. 快照目录**不进 git**（大文本/二进制），但它在主工作树的 `out/subai` 下，
   四棵树共享同一个根——快照跟着仓库走就没有「我这棵树上有」这回事了。

## 3. 机器实现

`coordination/evidence_store.py` 是唯一入口，不许各自 `open(..., "wb")`：

| 调用 | 作用 | 失败码 |
|---|---|---|
| `snapshot_path(sha256, filename=None, root=None, original_path=None)` | 由哈希推路径 | `HASH_BASIS_INVALID` |
| `snapshot_artifact(path, sha256=None, root=None)` | 校验后复制原字节，返回 `{path, sha256, bytes, snapshot}` | `SNAPSHOT_INVALID` / `HASH_BASIS_INVALID` |
| `verify(record)` | 核 `artifacts[]` 一行：快照在不在、字节还对不对 | 返回 `{ok, problems}`，不抛 |
| `store_root(root=None)` | 主工作树 `out/subai/_evidence_store` | — |

`gate bundle` 侧的对应闸门在 `coordination/gates.py`：
`snapshot_paths[]` 里指向 `reports/` 却没带 `snapshot` 的，一律 `SNAPSHOT_INVALID`。

## 4. 三种不被接受的写法

| 写法 | 为什么不行 |
|---|---|
| 「我本地有，路径是 `E:\...\reports\...`」 | 别人的树上没有；换机器没有；文件一改名就没有 |
| 「sha256 记了就够了」 | 哈希只能**验证**副本，不能**产生**副本。这是本节开头那个洞 |
| 「先挪走再改，我会记得」 | 记忆不是状态载体。`D-20261116-159` 就是靠「全盘搜索无副本」确认失败的 |

## 5. 与 `hash_basis` 的关系

两个概念不要混：

- `hash_basis=lf_normalized_v1` 说的是**怎么算哈希**（文本先 `\r\n → \n`）。
- `snapshot` 说的是**原字节存在哪**（不做任何归一）。

同一份文件完全可能：按归一基数算出的哈希与记录相符，而原始字节带 CRLF——
所以快照必须存**磁盘原样**；要核对记录的哈希，读快照后按记录声明的基数再算一次。

## 6. 当前状态（2026-11-16）

- **`reports/` 已纳入 git**（Human 2026-11-16 16:44 定，提交 `e7d9916`，379 个文件 / 3.83 MB，
  只排 `__pycache__/*.pyc`）。`D-20261116-159` ③ 由此关闭。
  三个文件 git 判为 binary 属正常（`M00/goldstandards_attempt8.txt` 是 UTF-16LE；
  `M02/p9_refusal.txt`、`M00/mask_semantics_attempt9.txt` 含 NUL）——**一律不转码**，
  这些字节的 sha256 已写进 evidence 记录，转码等于让历史记录失效。
- **快照规矩不撤**：git 保证「提交过的那一版」可复原，快照保证「记录引用的那一版」可复原。
  记录经常引用一个从未提交过的中间字节，那正是最容易丢的一版。
- 已按新规落地的：`D-20261116-160`（M00 attempt 11 的 4/4 artifact 全带 `snapshot`）。
- 历史 162 条记录里的旧 artifact **不回填**——回填等于伪造当时的证据形态；
  它们的状态就是「无快照，且这一点已记录在案」。
