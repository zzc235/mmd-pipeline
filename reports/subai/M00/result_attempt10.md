# M00 attempt 10 · PASS（`lock.py` 三处加固 + 作用域钉成 U323、例外单列 + `地面_物理` 复核 62）

A4 / `ai/a4` / HEAD **`cba05fb`** / 未 push。本笔覆盖 `c57c052`（加固主体）+ `cba05fb`（作用域更正 +
`exception_rows` 搬进纯 Python 模块）。attempt 9（`cf15b206…`）已入 main `dc9127c`，不在本笔。

## 一、`地面_物理`：不接线、单列例外（按 `D-20261116-133`）

作用域 `stage.collision_scope()` = `mmd_type == "RIGID_BODY"`（U323）。作用域外的对象逐条进
`exception_rows()`：

| 字段 | 值 |
|---|---|
| name | `地面_物理` |
| group | **1**（RNA 0 基；2号 的 dump 用 1 基，所以他那张表写「组 2」——同一个对象，两种坐标） |
| mask | 0（声明不与任何组碰） |
| 当前位 | `{bit0}` |
| **接上之后仍与 62 个刚体互撞** | **62**（与 2号 独立算的 62 一致） |

`still_collides_with` 比的是**通道打完之后的位**（`mask|own`），不是当前的 `{0001}`——后者数出来
是全部 323，没有信息量。逻辑搬进 `mmdpipe/mask.py`（纯 Python），`tests/test_stage_mask.py` 覆盖。

## 二、两个宇宙都报、都带标签

| 宇宙 | 刚体 | 对 | 该碰 | 不该碰 | 用途 |
|---|---:|---:|---:|---:|---|
| U323（`mmd_type`） | 323 | 52 003 | 11 908 | **40 095** | 1c 等式的唯一宇宙 |
| U324（`rigid_body`） | 324 | 52 326 | 11 908 | **40 418** | 旧场景物理/穿透数 |

`rigid_object_set_diff.only_by_rigid_body = ["地面_物理"]`：**点名，不用对数反推**。

交付场景前态（`J_baked.blend`，sha256 `e22e03f5…`，未变）与 1号 的 v3 探头逐位相同：
4009 条 `disable_collisions`（ncc 3651 + JOINT 358）/ 挡对 1813 / 挡错 2196 / 位型 1 种 `{0001}` /
按位分开 0。

## 三、`lock.py` 三处加固

| 处 | 做法 |
|---|---|
| 真正干活的 PID | `acquire --work-pid <pid,...>`（Blender 是子进程，与取锁的 shell 不同 PID） |
| 心跳 | `acquire` 起写 `heartbeat`，`touch` 刷新；**过期判定以心跳 mtime 为主依据**；没有心跳文件返回 **inf 而不是 0**（返回 0 会让「从没跳过」看起来「刚刚还活着」） |
| 回收 | 三条同时成立才允许：记录 PID 全不活 **且** 无 blender 进程 **且** 心跳超 `--stale-minutes`（默认 10）；动作是 `shutil.move` 到 `locks/_reclaimed/<时间戳>-<ident>/`，**`owner.txt` 原样保留**；任何一条不成立就 `LockHeld` 且原地不动 |

`release` 也要清 `heartbeat`（否则目录删不掉——第一版就是这么红的）。
`tests.test_lock` 31 passed：6 条新负控（blender 活着 / 自己的 PID 活着 / 心跳新鲜）+ 1 条正控
（回收后能重新取锁，且证据文件还在）。

## 四、自报：探活第一版会把仪器自己杀掉

`pid_alive()` 起初用 `os.kill(pid, 0)`。**Windows 上 CPython 把它实现成
`TerminateProcess(handle, sig)`** —— 不是探活，是**杀掉那个进程**。测试里传自己的 PID，测试进程
当场消失、**一个字节输出都没有**，我一度读成「无声崩溃」。改成 Windows 走
`tasklist /FI "PID eq N"`、非 Windows 才用 `os.kill(pid,0)`；探针自身失败一律返回 False
（「问不出来」不许当「活着」）。新增 `test_pid_alive_is_safe_probe`：探完一个不存在的 PID，
自己必须还活着。

## 五、更正 `c57c052` 的标题

`c57c052` 标题写「U324 与 U323 两个宇宙合一」——写于 `D-20261116-133` 之前，方向与决定相反。
禁 amend，故在 `cba05fb` 里显式更正，并把做法落成代码与测试。**标题作废，以 `cba05fb` 为准。**

## 六、验证

| cmd | exit | 结果 |
|---|---:|---|
| `discover`（默认） | 0 | **389 passed / 0 failed / 15 skipped** |
| `discover` + `utf-8` / `gbk` | 0 | 389 / 15 各一遍 |
| `tests.test_lock` | 0 | 31 passed |
| `tests.test_stage_mask` | 0 | 25 passed |
| 护栏 | 0 | `scanned=133 violations=0 skipped=0` |

## 七、`known_risks`

- `地面_物理` 不在作用域，接上之后仍与 62 个刚体互撞——已单列，不是漏掉。
- 1c 等式只在 U323 成立；U324 的数只用于旧场景物理/穿透。
- `reclaim` 依赖 `tasklist` 探测 blender；该命令不可用时只剩 PID + 心跳两条判据，报告须写明。
- 逐对象 `constraint_add` 在大场景代价过高，事后 apply 只适合小场景（attempt 9 已量化）。
