"""CLI 输出编码：**父进程钉 UTF-8 解码，子进程就必须钉 UTF-8 输出。**

2026-11-16 一天里在两个席位各撞一次，都是「只修一头」：

* 1号：`cache_state.main()` 打印中文走本地编码（GBK），测试按 UTF-8 解码 → `UnicodeDecodeError`
  → `stdout=None` → `assertIn("空闲", None)` → `TypeError`；
* 4号：`coordination/lock.py` 同一处，测出来的现象一模一样，只是**红的那个环境换成了默认环境**
  ——也就是所有人默认会踩的那种。

所以两边都要钉：测试侧显式 `encoding="utf-8"`，产品侧在 `main()` 开头把
`stdout`/`stderr` `reconfigure` 成 UTF-8。只钉一头，只是把红从一种环境搬到另一种。
"""
from __future__ import annotations

import sys


def ensure_utf8_stdio() -> None:
    """把 stdout/stderr 钉成 UTF-8（幂等、失败不抛——被重定向到无 reconfigure 的对象时跳过）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")   # type: ignore[attr-defined]
        except (AttributeError, ValueError, OSError):
            continue
