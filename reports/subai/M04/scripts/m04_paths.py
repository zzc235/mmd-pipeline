# -*- coding: utf-8 -*-
"""仓库根的自定位（M04 脚本共用一份实现，不各写一遍层数）。

今晚同一件事被三个人各踩一次：`3号` 18:51（`out/subai/M05` 到根数成 4 层）、
我 19:47（`sys.path[0]` 是脚本目录、`import coordination` 静默失败）、`4号` 20:04
（`out/subai/M00/scripts` 到根说成 4 层，实际 5）。共同点是**数层数**：
搬一次目录就静默失效，而失效长得像「模块不存在」。

所以这里只有一个办法：**往上走到同时有 `coordination/` 与 `mmdpipe/` 的那一层**，
走不到就把起点打出来再死。两种深度（`out/` 与 `reports/`）都成立才算「镜像」。
"""
from __future__ import annotations

import os


def find_repo_root(start):
    """从 `start` 往上走到同时含 `coordination/` 与 `mmdpipe/` 的目录。"""
    cur = os.path.abspath(start)
    while True:
        if (os.path.isdir(os.path.join(cur, "coordination"))
                and os.path.isdir(os.path.join(cur, "mmdpipe"))):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            raise SystemExit(
                "从 %s 往上走到顶也没找到同时含 coordination/ 与 mmdpipe/ 的目录" % start)
        cur = parent


def check_root(root):
    """验根：两个目录都得在，否则**打印那个根**再退出（不是抛 ImportError）。"""
    for need in ("coordination", "mmdpipe"):
        if not os.path.isdir(os.path.join(root, need)):
            raise SystemExit(
                "ROOT 算错了：%r 里没有 %s/ —— 用 find_repo_root() 自定位，别数层数"
                % (root, need))
    return root


def ensure_on_path(start, sys_path=None):
    """自定位 + 验根 + 插 `sys.path`，返回根。"""
    import sys
    path = sys_path if sys_path is not None else sys.path
    root = check_root(find_repo_root(start))
    if root not in path:
        path.insert(0, root)
    return root
