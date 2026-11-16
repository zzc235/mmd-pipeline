# M00 · result（attempt 6）：`subprocess` 文本解码 —— 12 处补 `encoding=` + 全仓护栏

> 席位 A4 · 分支 `ai/a4` · 本笔 HEAD `12b572b`（父 `36fec14`）· 2026-11-16 13:47
>
> 状态：**PASS**。D0 13:41 派的第一件：main 被 `PYTHONIOENCODING=utf-8` 打红，**这是一类缺陷，不是一条测试**。

## 1. 病灶

```python
subprocess.run(cmd, capture_output=True, text=True)     # 没有 encoding=
```

父进程按**本地编码**（这台机器 GBK）解子进程的 **UTF-8** 输出 → `UnicodeDecodeError`；某些路径下
`stdout` 变成 `None` → `json.loads(None)` → `TypeError`。**报错点离病根很远**，所以它能在"默认环境全绿"下活很久。

## 2. 改的 12 处

| 文件 | 处数 | 说明 |
|---|---:|---|
| `coordination/gate.py` / `coordination/paths.py` | 各 1 | `git` 输出解码（diff / rev-parse） |
| `make_report.py` | 1 | `blender --version`——**这处原本无主**，白名单要空就必须一起修 |
| `mmdpipe/stage.py` | 3 | **产品代码**：ffmpeg / ffprobe 输出，`encoding="utf-8", errors="replace"` 兜脏字节（不因为一行乱码把整条流水线打断） |
| `tests/test_coordination.py` | 6 | 见 §3 |

## 3. 最要命的一条：一格假绿

`test_two_processes_same_cwd_agree` 比较两个子进程的 stdout：

```python
a = subprocess.run(..., capture_output=True, text=True)   # 可能 stdout=None
b = subprocess.run(..., capture_output=True, text=True)   # 也可能 None
self.assertEqual(a.stdout.strip(), b.stdout.strip())      # 这里会 AttributeError…
```

而这台机器上它是"绿"的——因为**解码失败发生在别处**、两次都拿到同样的空串，`"" == ""` 为真。
**凡是比较两个子进程输出的测试，必须先把 stdout 断言成非空**，否则「两边都坏」与「两边都对」长得一样。已改成：

```python
self.assertEqual(a.returncode, 0, a.stderr)
self.assertTrue(a.stdout.strip(), "第一次运行没有输出，比较无意义")
... 再比
```

## 4. 护栏：`tests/test_subprocess_encoding.py`

- 用 `ast` 扫全仓 `.py`：`subprocess.{run,Popen,check_output,call,check_call}` 只要带了 `text=True` 或
  `capture_output=True` 而**没有** `encoding=`，测试红；`WHITELIST` **必须为空**（有测试盯着）；
- 唯一豁免是行内 `# noqa: subprocess-bytes`（确实需要字节输出时用），现在全仓 **0 处**；
- **护栏自己也被喂过应当被拒的输入**：
  - `scan_source` 上直接喂违规片段 → 报第 3 行；
  - `scan_tree` 上在临时目录放一份违规文件 → 报 `[("bad_module.py", 2)]`；
  - 仓库里真实放一个违规文件 `tests/_tmp_bad_encoding.py` → 护栏**红**（报出精确 `文件:行号`），删掉后立刻回绿。

## 5. 验证（两种环境都跑）

| 环境 | 结果 |
|---|---|
| `PYTHONIOENCODING=utf-8` | **292 passed / 0 failed / 15 skipped**（17.5 s，exit 0） |
| 不设 `PYTHONIOENCODING` | **292 passed / 0 failed / 15 skipped**（18.8 s，exit 0） |

D0 的自我记账（"验收测试也得有一个应当被拒的环境"）我这边对应的是：**两种环境都跑，缺一个不算验过**。

## 6. 已知限制

1. 护栏只按 `ast` 认 `subprocess.*` 的**直接**调用；`functools.partial`、封装的 `run_shell()` 之类间接调用扫不到；
2. `errors="replace"` 是**有损**的：脏字节会被替换成 `\ufffd`，产品代码里读的是 `returncode` 与关键字，不是全文，所以可接受；若将来有代码要解析完整输出，需要改成显式报错；
3. `capture_output=True` 而**不要文本**的调用现在必须写 `# noqa: subprocess-bytes`——这是一条约定，不是语法约束，靠 review 守。
