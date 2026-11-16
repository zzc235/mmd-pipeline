# -*- coding: utf-8 -*-
"""C/D 三臂的**启动器**：把 `m04_run_cd.py` 包进 `coordination.lock guard` 里跑。

## 为什么它这么薄（2026-11-16 19:06 改）

我原来在这层自己实现「取锁 → 心跳 → 必放锁」。`D-213` 之后 `coordination.lock guard` 已经
把这三件事做成命令行的形状（**取不到锁，命令根本不执行**；跑期间自动刷心跳；跑完必放锁；
锁中途丢了判 `EXIT_LOCK_LOST=5`）。两处实现同一件事就是两份规则，所以这里的锁逻辑**全删了**，
只留下面两件它不提供的东西：

1. **owner 可以不写竖线**：`模块负责2|A2` 在某些启动路径（后台作业启动器）里竖线会被当管道吞掉，
   owner 变成「模块负责2A2」⇒ 锁报「用法错」而真因是参数被改了。这里允许
   `--owner-module 模块负责2 --owner-tree A2`，竖线在 Python 里拼，**不经命令行**；
2. 默认值（驱动脚本路径、`out/` 所在的主工作树）。

跑法：

    python reports/subai/M04/scripts/m04_run_cd_locked.py \
        --owner-module 模块负责2 --owner-tree A2 \
        --note 'M04 C/D 第二轮三臂' --wait 1800 --heartbeat-every 240 -- \
        --arms-dir <...> --input <...> --out-dir <...> --batch-id round2_324b --freeze

`--driver` 只为自检用（换别的脚本即可验「取不到锁就不跑」这一圈）。
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(HERE, "m04_run_cd.py")
# 锁与 `out/` 都在主工作树里；`coordination` 包在那边，`-m coordination.lock` 要在那儿跑。
LOCK_CWD = r"E:\dsh pr\woker2"

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):  # pragma: no cover
    pass


def resolve_owner(owner, owner_module, owner_tree):
    """`a|b` 或两段写；都不成立就返回空串（由调用方以用法错停下）。"""
    if owner:
        return owner if "|" in owner else ""
    if owner_module and owner_tree:
        return owner_module + "|" + owner_tree
    return ""


def build_guard_cmd(owner, note, lock_cwd, driver, driver_args,
                    wait_s=0, heartbeat_every=240, owner_module="", owner_tree=""):
    """拼出 `python -m coordination.lock guard ... -- <driver> ...`（纯函数，可离屏测）。

    两段写现在 `guard` 自己就支持（`--owner-module`/`--owner-tree`，与 `--owner` 互斥），
    所以**原样透传**，不在这里拼竖线 —— 拼一次就是一份重复规则。
    """
    cmd = [sys.executable, "-m", "coordination.lock", "guard"]
    if owner_module and owner_tree:
        cmd += ["--owner-module", owner_module, "--owner-tree", owner_tree]
    else:
        cmd += ["--owner", owner]
    cmd += ["--note", note, "--wait", str(wait_s), "--heartbeat-every", str(heartbeat_every),
            "--", sys.executable, driver]
    cmd.extend(driver_args)
    return cmd


def main(argv=None):
    ap = argparse.ArgumentParser(description="把驱动包进 coordination.lock guard")
    ap.add_argument("--owner", default="", help="`模块|工作树`（命令行里有竖线时用下面两段写）")
    ap.add_argument("--owner-module", default="", help="模块名，如 模块负责2")
    ap.add_argument("--owner-tree", default="", help="工作树名，如 A2")
    ap.add_argument("--note", required=True)
    ap.add_argument("--lock-cwd", default=LOCK_CWD)
    ap.add_argument("--wait", type=float, default=0.0, help="等锁秒数（0＝不等，直接失败）")
    ap.add_argument("--heartbeat-every", type=float, default=240.0)
    ap.add_argument("--driver", default=DRIVER)
    ap.add_argument("driver_args", nargs=argparse.REMAINDER, help="`--` 之后原样传给驱动")
    a = ap.parse_args(argv)

    owner = resolve_owner(a.owner, a.owner_module, a.owner_tree)
    if not owner:
        print("[用法] 给 --owner '模块|工作树'，或 --owner-module 模块 --owner-tree 树",
              file=sys.stderr)
        return 2
    args = list(a.driver_args)
    if args and args[0] == "--":
        args = args[1:]
    if not args:
        print("[用法] `--` 之后要跟驱动参数", file=sys.stderr)
        return 2

    cmd = build_guard_cmd(owner, a.note, a.lock_cwd, a.driver, args,
                          wait_s=a.wait, heartbeat_every=a.heartbeat_every,
                          owner_module=a.owner_module, owner_tree=a.owner_tree)
    print("[guard] %s" % " ".join(cmd[3:8]), flush=True)
    return subprocess.call(cmd, cwd=a.lock_cwd)


if __name__ == "__main__":
    sys.exit(main())
