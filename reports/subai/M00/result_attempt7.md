# M00 · result（attempt 7）：护栏判据收窄 + `coordination/lock.py` 落地

> 席位 A4 · 分支 `ai/a4` · 本笔 HEAD `168cd2e`（两提交：`29d4e9a` 护栏收窄、`168cd2e` 锁模块）· 2026-11-16 13:47
>
> 状态：**PASS**。这一笔包含 D0 13:41 派的第 1 件（lock.py）与 3号 13:44 指出的护栏判据问题。

## 一、护栏判据收窄（3号 的意见是对的，我改了）

第一版判据是「`text=True` **或** `capture_output=True` 却缺 `encoding=` → 红」，白名单必须为空。3号 指出这会自相矛盾：
仓库里有一批**正当的 bytes 用法**（`capture_output` 不带 `text`，根本不解码、不会崩），按第一版它们全红，
而白名单又被要求为空 ⇒ 只能靠 `# noqa` 逐个挂，"白名单为空"变成"豁免满地"。

| 项 | 第一版 | 现在 |
|---|---|---|
| 触发条件 | `text=True` 或 `capture_output=True` | **`text=True` 或 `universal_newlines=True`**（只认"要解码"） |
| `capture_output` 单独出现 | 红 | **不算**（bytes 模式） |
| 扫描范围 | 目录遍历 + 目录黑名单 | **`git ls-files`**（只扫版本控制里的 `.py`） |
| `mmdpipe/stage.py:1237` | 我加了 `encoding=` | **已撤回**——它 `capture_output` 不带 `text`，输出只用来判存在，不属于这条缺陷类 |

**扫描范围的取舍要写清楚**：改用 `git ls-files` 之后，**untracked 的 `.py` 不进判据**；
但 staged 的新文件**是**进判据的（`git ls-files` 读的是索引），也就是说**凡是能进 main 的文件都会被扫到**。
这条我用真实文件验过（见 §三）。

## 二、`coordination/lock.py`

一天撞出两次事故，规矩从"自觉"改成"代码"：

| 动作 | 实现 | 失败时 |
|---|---|---|
| `acquire` | `os.mkdir`（已存在即 `FileExistsError`），成功后写 `owner.txt` | `LOCK_HELD` + **打印持锁人 `owner.txt` 原文**，退出 3 |
| `release` | 先读 `owner.txt`，`模块\|工作树` 与 `--owner` 不一致就抛，**不删** | `LOCK_NOT_YOURS` + 打印实际持有者，退出 3 |
| `status` | 持有者 / PID / 取得时间 / 已占用秒数 | 目录在但读不出 `owner.txt` → `LOCK_UNKNOWN`，**退出 4，不当空闲** |

退出码 `0/2/3/4`（2 = 用法，`--owner` 没写 `模块|工作树` 也走 2）。
`owner.txt` 兼容大家已经在写的 `<模块|工作树>|PID=…|ISO|说明`；校验只看前两段（PID 每次进程不同，拿它比永远比不中）。
`coordination/paths.py` 新增 `lock_dir()`：与 board 同一个根（主工作树 `out/subai/`），可用 `MMDPIPE_LOCK` 覆盖。

## 三、实跑证据（都在本机、真实路径上）

| 项 | 结果 |
|---|---|
| 真实共享锁 `python -m coordination.lock status` | `空闲：E:/dsh pr/woker2\out\subai\locks\blender.lock`，exit 0（当时确实没人持锁） |
| CLI 全序列（临时目录） | `acquire` 0 → 别人再 `acquire` **3**（打印 `LOCK_HELD …模块负责4\|A4\|PID=30120…`）→ `status` 0（`已占用 0.8 s`）→ 别人 `release` **3**（`LOCK_NOT_YOURS …未删除`）→ 自己 `release` 0 → 残缺锁 `status` **4**（`LOCK_UNKNOWN …owner.txt 读不到`） |
| 护栏「应当被拒」端到端 | 造 `tests/_tmp_bad_encoding.py`（`text=True` 无 `encoding`）→ `git add` → 护栏**红**并报 `('tests/_tmp_bad_encoding.py', 2)` → 删掉 → **绿** |
| `tests.test_lock` | **14 passed** |
| `tests.test_subprocess_encoding` | **9 passed** |
| 全量 `unittest discover` | **307 passed / 0 failed / 15 skipped**（18.3 s） |

## 四、三条「应当被拒」的测试（D0 点名要的）

1. **取别人的锁**：`acquire` 第二次抛 `LockHeld`，且**持有者没被覆盖**（`read_owner` 仍是第一个人）；
2. **释放别人的锁**：抛 `NotOwner`，**目录还在、owner.txt 没动**；
3. **残缺锁**：目录在、`owner.txt` 不在 → `status` / `acquire` / `release` **三个动作全部抛** `IncompleteLock`，CLI 退出 4。

## 五、已知限制

1. `release` 只比对 `模块|工作树`，**不比对 PID**：同一个人在两棵树（或两个进程）里都写 `模块负责4|A4` 时，能互相释放——这是有意的（人比进程稳定），但意味着"同一席位并发"仍要靠排队纪律；
2. 没有 `--force` / `--steal`：**故意不做**。锁泄漏只能人工确认后手工删，工具不提供"我确定它死了"的捷径；
3. `wait` 用轮询（默认 0.5 s）不是文件系统事件；`--wait 0`（默认）即"不排队，直接失败"；
4. `owner.txt` 里 PID 只是**线索**不是事实（PID 可能被系统复用），判据只看前两段。
