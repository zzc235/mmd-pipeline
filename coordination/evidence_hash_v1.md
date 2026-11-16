# evidence_hash v1 规范（D0 定口径，2026-11-16）

> 依据：`13_自动调度与分流器规范.md` §5.1。本文件补齐该节缺失的两项：**字段序列**与
> **浮点精度**。`scheduler.py` / `dispatcher.py` 与所有 `SUBMISSION` 都按本规范计算，
> 不按本规范算出的 hash，D0 一律 `RETURN_FIX`（理由码 `MISSING_EVIDENCE`）。

## 1. 目标

让同一份证据在任何机器、任何时间、任何工作树算出**同一个** hash；让「只改说明」「重跑同一条
测试」「换个说法再说一遍」无法伪装成新证据。

## 2. 计算总则

- 输入：一个 JSON 对象。输出：`"evidence/1:" + sha256(hex)`。
- 序列化：UTF-8 无 BOM；键按 Unicode 码点**递归**升序；无缩进、无尾随空格；分隔符 `,` 与 `:`；
  `ensure_ascii=false`；结尾**不加换行**。等价的 Python 写法：

  ```python
  raw = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
  digest = "evidence/1:" + hashlib.sha256(raw).hexdigest()
  ```

- 对象内**必须**带 `"spec": "evidence/1"`。规格升级即换版本号，不悄悄改算法。

## 3. 字段表

| 字段 | 类型 | 归一规则 |
|---|---|---|
| `spec` | str | 恒为 `evidence/1` |
| `task_id` | str | 原样，形如 `M01` |
| `attempt` | int | 十进制，无前导零 |
| `status` | str | 只允许 `PASS` / `PARTIAL` / `BLOCKED` |
| `files` | list[obj] | 按 `path` 升序；每项 `{path, sha256, tracked}`；`sha256` 是**文件内容哈希**，不是 diff 文本哈希 |
| `tests` | list[obj] | 按 `(cmd, exit)` 升序；每项 `{cmd, exit, passed, failed, skipped}`，计数为 int |
| `artifacts` | list[obj] | 按 `path` 升序；每项 `{path, sha256, version}` |
| `known_risks` | list[str] | 每项去首尾空白、内部连续空白折成一个空格、丢空项、按码点升序、去重 |
| `interface` | str \| null | 可选；冻结接口标识，如 `pmx_patch/joint_limit@1` |

**明确不进 hash**（改这些不算新证据）：`summary`、`message`、备注、任一时间戳、绝对路径、
主机名、PID、耗时、日志头尾、提交信息、报告正文措辞、`out/` 下临时目录。

## 4. 路径归一

1. `files[].path`：相对**该模块自己的 worktree 根**，POSIX 分隔符 `/`，不带 `./`、不带盘符、不带结尾 `/`。
2. `artifacts[].path`：相对**主工作树根** `E:\dsh pr\woker2`（`reports/` 只在主工作树，避免四份副本）。
3. 大小写原样保留，不在 Windows 上折叠。
4. 同一 `path` 在同一数组里只允许出现一次，重复即格式错误。

### 4.2 files[] 必须覆盖整条分支（v1.2 补充，2026-11-16）

`files[]` 必须覆盖**本分支自己的全部改动**，一个不许漏。基线不要写死某个提交号，用三点式：

```powershell
git diff --name-only main...HEAD      # 等价于 从 merge-base 算到 HEAD
```

证据覆盖不到的提交不能被合并——那等于把没人看过的代码送进基线。

漏了即格式无效（`RETURN_FIX`，理由码 `MISSING_EVIDENCE`），且**补证不算新一轮验证**：
它补的是同一次主张里被漏掉的覆盖面，不是把同一结论换个说法再审一遍。
若一次主张要分多次交，必须在提交里写明"本次覆盖哪些文件、哪些仍未覆盖"。

**分支同步（v1.3）**：允许并建议 `git merge main` 把自己分支拉到最新基线（自己的分支指针前移，
不改写任何历史）；**禁止** `rebase` / `reset` / `push`。合并 main 之后必须重跑全量测试并回报，
遇冲突立即停、报 D0，不自行解决。用三点式基线后，merge main 不会污染 `files[]` 的计算。

### 4.1 外部树例外（v1.1 澄清，算法不变，存量 hash 不重算）

有些模块的正本根本不在 `E:\dsh pr\woker2`，也不在任何 git 仓库里（M06 的
`E:\flowhmr-test`：`library/manifest.jsonl`、`tools/manifest.py`）。规则：

1. 该模块的 `files[]` 与 `artifacts[]` **一律以那棵外部树的根归一**，不得写成绝对路径，
   也不得用 `..\..\` 伪相对。
2. `files[].tracked` 必须为 `false`（无版本控制可言）；把外部文件标成 `tracked:true` 是格式错误。
3. **同一次提交里不许混用两个根**：要么全部仓库根，要么全部外部根。混用即 `RETURN_FIX`。
4. 外部树的报告也写在那棵树里（`<外部根>/library/reports/subai/Mxx/`），不进主工作树，
   避免同一份证据出现两处副本。
5. 外部树没有 git 兜底，所以改动前必须做文件备份并记录前后 `sha256`（M06 的
   `manifest.py`、`library/README.md` 都适用）。

新增黄金样例：

| 编号 | 断言 |
|---|---|
| H7 | 外部树提交：`files[].tracked` 全 `false`，且两个数组的 `path` 都相对外部根 |
| H8 | 同一次提交混用仓库根与外部根 → 直接拒绝 |

## 5. 浮点精度

1. **数值默认不进 hash**：测量值、阈值、帧号、角度、时间跨度一律通过产物文件的 `sha256`
   覆盖（`files` / `artifacts`）。这是首选路径，不是妥协。
2. 必须内联的少数数值，用**最短往返表示**：Python `repr(x)`（等价 `f"{x!r}"`）。`0.3` 就写
   `0.3`，不写 `0.30000`，不写 `format(x, ".6f")`。
3. 归一：`-0.0` 记为 `0.0`。
4. **`NaN` / `+Inf` / `-Inf` 一律拒绝**：提交直接 `RETURN_FIX`，理由码 `MISSING_EVIDENCE`。
   不可复现的数值没有资格当证据。
5. 禁止「先四舍五入到固定小数位再进 hash」：不同机器精度不同，会制造假的新证据。

## 6. 黄金样例（M00 必须写成测试，缺一条不算完成）

| 编号 | 断言 | 用途 |
|---|---|---|
| H1 | 同一提交、两个不同进程、两个不同工作树 → hash 完全相同 | 可复现 |
| H2 | 只改 `summary` / `message` / 报告措辞 / 提交信息 → hash **不变** | 挡住「换个说法再送审」 |
| H3 | 任一 `files[].sha256` 或 `artifacts[].sha256` 变 → hash **必变** | 真新证据放行 |
| H4 | `./mmdpipe\pmx.py` 与 `mmdpipe/pmx.py` → hash 相同 | 路径归一 |
| H5 | `tests[].passed` 从 12 改 13 → hash **必变** | 计数进 hash |
| H6 | 输入含 `NaN` → 拒绝，不产生 hash | 不可复现值拦截 |

## 7. 版本与纪律

- `scheduler` 拒收 `spec != "evidence/1"` 的提交。
- 改本规范 = 升版本（`evidence/2`），存量 hash **不重算**，旧提交仍按 v1 校验。
- 任何人不得为了通过验证而重算 hash、重排字段或重新序列化——那是 W3。

## 5. 哈希基数（2026-11-16 13:24 追加，D-060）

本机 `core.autocrlf=true`，同一份文本内容在不同检出下磁盘字节不同（CRLF / LF），导致同一个文件有两个 sha256。今天已出现两次「看起来造假、其实是换行」：

- M07 attempt 2 的 `tests_bpy/smoke.py`：工作树 135 处 CRLF，按磁盘哈希 `f57b95da…`，按 git blob `1d016956…`；
- 同一份证据里其余三个文件是 LF，两种算法结果相同——**一份证据里混了两种基数**。

**规定**：

1. 文本文件（`.py` / `.md` / `.json` / `.jsonl` / `.txt` / `.toml` / `.cfg`）先把 `\r\n` 规范化为 `\n`，再算 sha256；
2. 二进制文件（`.blend` / `.png` / `.zip` / `.pmx` / `.vmd`）按原始字节算，不做规范化；
3. 证据里记 `hash_basis: "lf_normalized_v1"`；缺该字段的按旧基数（磁盘字节）解释；
4. 已提交的旧证据**不追溯**，但 `result` 里要注明当时用的是哪种基数；
5. 核验方（D0）复核时，**先试 LF 规范化**，只有规范化后仍不等才算内容不一致。

**为什么不是「一律用 git blob」**：`reports/` 与 `out/` 全在 gitignore 里，不进版本库，没有 blob 可比；规范化对两者都适用。