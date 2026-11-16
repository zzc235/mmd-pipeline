# M00 · result（attempt 4）：`evidence/1` 增加可选字段 `hash_basis`

> 席位 A4 · 分支 `ai/a4` · 本笔 HEAD `8963175`（父 `3f625eb` = 已并入 main 的 attempt 3）· 2026-11-16 13:33
>
> 状态：**PASS**。D0 13:30 提的「两笔证据里都没有 `hash_basis` 这个键」——根因不是忘了写，是**这个字段根本活不到 canonical 里**：
> `normalize()` 只保留 9 个键，其余全丢。所以补的是**模式**，不是文本。

## 1. 改了什么

`coordination/evidence.py` 的 `normalize()` 接受可选 `hash_basis`（字符串）：

| 输入 | 结果 |
|---|---|
| 不给 | canonical 里**没有**这个键，哈希与改动前逐字节相同 |
| `"lf_normalized_v1"` | 进 canonical，参与哈希 |
| `"  lf_normalized_v1  "` | 空白折叠成 `lf_normalized_v1`（与不带空白同值） |
| `"   "`（纯空白） | 等同不给 |
| 非字符串（如 `1`） | `EvidenceError` |

**为什么必须做成可选**：今天的 `evidence/1` 已经被 9 笔提交用过。若把字段写成必填/默认值，
所有已合并的证据哈希都会失效——那等于把历史证据全废掉一次。

## 2. 验证

| 项 | 结果 |
|---|---|
| 参考值（改代码**之前**算的样本 digest） | `evidence/1:0863ecaa9f799f78b20ac87af69291dd5a971934c6662d62bb48d15566ac4186` |
| 改之后同一份样本（不写 `hash_basis`） | **同一个值**（硬编码进测试，回归即红） |
| 写了 `hash_basis` | 规范化结果多一个键、digest 改变；两个不同基数互相不等 |
| `tests.test_coordination` | **41 passed**（新增 4 条） |
| 全量 `unittest discover` | **282 passed / 0 failed / 15 skipped**（16.7 s） |

## 3. 从现在起我交的证据

两笔证据（含这一笔）都带 `"hash_basis": "lf_normalized_v1"`：`files[]` 与 `artifacts[]` 里的文本文件
一律先 `\r\n → \n` 再算 `sha256`，二进制文件按原始字节。**核验方法**：

```python
import hashlib
data = open(path, "rb").read()
sha = hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()   # 文本
```

## 4. 已知限制

1. `hash_basis` 只是**声明**，`evidence.py` 不校验也不重算 `files[]`/`artifacts[]` 的哈希——它仍然"信你报的数"，
   核验靠 D0 复算（这一点与改动前一致，没有变强）；
2. 基数名没有枚举约束（写 `"lf_normalized_v1"` 还是 `"foo"` 都能过），只做了空白折叠与类型检查；
   要收紧成枚举需要 D0 定名字；
3. `SPEC` 仍是 `evidence/1`：这次是**加可选键**，不是破坏性变更，所以没有升级到 `evidence/2`。
