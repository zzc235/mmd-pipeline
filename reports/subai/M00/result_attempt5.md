# M00 · result（attempt 5）：`hash_basis` 收成枚举

> 席位 A4 · 分支 `ai/a4` · 本笔 HEAD `36fec14`（父 `8e2efd8` = 已并入 main 的 attempt 4）· 2026-11-16 13:36
>
> 状态：**PASS**。D0 13:34 的第二条答复：**收紧成枚举，唯一合法值 `lf_normalized_v1`（缺省=旧基数），其它值抛 `EvidenceError`。**

## 1. 口径

| 写法 | 结果 |
|---|---|
| 省略 / `null` / 空串 | 旧基数（磁盘原始字节）；canonical 里**不出现**该键，旧 9 笔哈希逐字节不变 |
| `"lf_normalized_v1"` | 合法，进 canonical、参与哈希 |
| `"  lf_normalized_v1  "` | 首尾空白折叠后匹配（仍然合法） |
| `"raw_bytes_v1"` / `"foo"` / `"LF_NORMALIZED_V1"`（大写） | `EvidenceError`，`reason_code = "WRONG_HASH_BASIS"` |
| 非字符串（如 `1`） | `EvidenceError` |

**允许省略不是漏洞，是兼容**：`evidence/1` 已经被 10 笔提交用过，强制必填会让它们全部失效。所以规则是
「**新提交必须带，旧证据可以不带**」，而不是「带不带都行」——`evidence_hash_v1.md` §5.1 写明了这一点。

**大写为什么也拒**：枚举值就是字节相等的字面量。留一条"大小写不敏感"的余地，下一个 bug 就会是
`LF_normalized_v1` 与 `lf_normalized_v1` 两份证据算不算同一基数。

## 2. 验证

| 项 | 结果 |
|---|---|
| `tests.test_coordination` | **43 passed**（新增 2 条：枚举拒绝 + `reason_code`） |
| 全量 `unittest discover` | **284 passed / 0 failed / 15 skipped**（16.2 s） |
| 缺省路径未受影响 | attempt 4 已经用硬编码参考值钉住（不写 `hash_basis` 仍是 `0863ecaa…4186`），本轮改动没有触碰那段 |

## 3. 规范文档同步

`coordination/evidence_hash_v1.md` 新增 **§5.1**：`hash_basis` 是枚举不是自由文本，附拒绝表与"为什么允许省略"。
这句话按 D0 的原话写进去了：**自由文本的"标准"等于没有标准——写 `raw_bytes_v1` 和写 `foo` 一样能过，核验方反而要猜。**

## 4. 已知限制

1. 枚举只有 `lf_normalized_v1` 一个值；将来若要"按 git blob"或"按磁盘字节"作为显式选项，加这里是**升版本**的事
   （`evidence/2`），不是加一个字符串；
2. `hash_basis` 仍是声明、不重算 `files[]`/`artifacts[]` 的哈希（D0 13:34 明确保持现状：让生产者自证会把证据变成自说自话）；
3. 省略仍合法（见 §1），所以"有没有守 LF 口径"这件事**靠核对证据里有没有这个键**，不靠强制。
