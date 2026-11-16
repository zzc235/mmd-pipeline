"""协调层的落盘位置：任务板是**四棵工作树共享的单实例**，不进版本控制。

为什么要有这一层：13 §2 说 `board.db` 是唯一事实源。四棵树各存一份 db 就会
变成四份事实源，谁认领了谁没认领各说各话。而 db 是二进制、带 WAL，本来也不该
进 git（D-20261116-012：board.db 与 dispatch.json 移出版本控制）。

定位规则（从确定到兜底）：
    1. 显式参数 `path`
    2. 环境变量 `MMDPIPE_BOARD` / `MMDPIPE_DISPATCH`
    3. 主工作树根 `…/out/subai/coordination/`（`out/` 已被 .gitignore 忽略）
       —— 主工作树根从 `git rev-parse --git-common-dir` 反推，worktree 的 common dir
          永远指向主仓 `.git`，所以四棵树算出的路径是同一个。
    4. 不是 git 仓库时退回当前工作目录的 `coordination/`（测试与离线演示可用）

纯标准库，不 import bpy / mmdpipe（与 coordination 其余模块一致）。
"""
from __future__ import annotations

import os
import subprocess

DB_NAME = "board.db"
DISPATCH_NAME = "dispatch.json"


def _git_common_dir(start: str) -> str:
    try:
        out = subprocess.run(["git", "-C", start, "rev-parse", "--path-format=absolute",
                              "--git-common-dir"],
                             capture_output=True, text=True, encoding="utf-8", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    if out.returncode != 0:
        return ""
    return out.stdout.strip()


def main_worktree_root(start: str | None = None) -> str:
    """主工作树根。worktree 里返回主仓根，主仓里返回自己。算不出就返回空串。"""
    start = os.path.abspath(start or os.getcwd())
    common = _git_common_dir(start)
    if not common:
        return ""
    if os.path.basename(common) != ".git":
        # 裸仓（bare repo）没有主工作树，不猜
        return ""
    return os.path.dirname(common)


def coordination_dir(start: str | None = None) -> str:
    """共享目录：主工作树 `out/subai/coordination`；非 git 环境退回 `<cwd>/coordination`。"""
    root = main_worktree_root(start)
    if root:
        return os.path.join(root, "out", "subai", "coordination")
    return os.path.join(os.path.abspath(start or os.getcwd()), "coordination")


def board_path(override: str | None = None, start: str | None = None) -> str:
    if override:
        return os.path.abspath(override)
    env = os.environ.get("MMDPIPE_BOARD")
    if env:
        return os.path.abspath(env)
    return os.path.join(coordination_dir(start), DB_NAME)


def dispatch_path(override: str | None = None, start: str | None = None) -> str:
    if override:
        return os.path.abspath(override)
    env = os.environ.get("MMDPIPE_DISPATCH")
    if env:
        return os.path.abspath(env)
    return os.path.join(coordination_dir(start), DISPATCH_NAME)
