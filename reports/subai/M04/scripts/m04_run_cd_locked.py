# -*- coding: utf-8 -*-
"""带锁跑一次长作业（`m04_run_cd.py` 就是它的第一个使用者）。

为什么要在驱动外层再包一层：`m04_run_cd.py` 一次跑几十分钟，而**没有心跳的长作业会被
判成过期锁、下一个人回收它**（`D-188` 那套三步闸的反面）。所以这层只做三件事：

1. `acquire`：取不到就**不跑**（exit 3），不排队、不抢；
2. 心跳线程：每 `--touch-every` 秒 `touch` 一次，读数进日志（过期阈值默认 10 分钟，5 分钟一次留两倍余量）；
3. `release`：**无论子进程怎么结束都放**（`finally`），包括 Ctrl-C 与崩溃 —— 留着一把「我崩了但锁还在」的锁，
   比没拿到锁更糟。

跑法（`--` 之后原样传给驱动）：

    python reports/subai/M04/scripts/m04_run_cd_locked.py \
        --owner '模块负责2|A2' --note 'M04 C/D 第二轮三臂' -- \
        --arms-dir <...> --input <...> --out-dir <...> --batch-id round2_324 --freeze

`--driver` 只为自检用（换成别的脚本即可验「取锁→心跳→释放」这一圈），默认就是 `m04_run_cd.py`。
"""
import argparse
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(HERE, "m04_run_cd.py")
# 锁与 `out/` 都在主工作树里；`coordination` 包在那边，`-m coordination.lock` 要在那儿跑。
LOCK_CWD = r"E:\dsh pr\woker2"

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):  # pragma: no cover
    pass


def lock_cmd(kind, owner, cwd, extra=()):
    cmd = [sys.executable, "-m", "coordination.lock", kind, "--owner", owner] + list(extra)
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description="取锁 → 跑驱动 → 心跳 → 释放")
    ap.add_argument("--owner", required=True, help="`模块|工作树`，如 '模块负责2|A2'")
    ap.add_argument("--note", required=True, help="一句话说明这次要跑什么")
    ap.add_argument("--lock-cwd", default=LOCK_CWD)
    ap.add_argument("--touch-every", type=int, default=300)
    ap.add_argument("--driver", default=DRIVER)
    ap.add_argument("driver_args", nargs=argparse.REMAINDER,
                    help="`--` 之后原样传给驱动")
    a = ap.parse_args(argv)

    args = list(a.driver_args)
    if args and args[0] == "--":
        args = args[1:]
    if not args:
        print("[用法] `--` 之后要跟驱动参数", file=sys.stderr)
        return 2

    got = lock_cmd("acquire", a.owner, a.lock_cwd, ["--note", a.note, "--wait", "0"])
    print("[acquire] rc=%s %s" % (got.returncode, (got.stdout or got.stderr or "").strip()[:200]),
          flush=True)
    if got.returncode != 0:
        return 3

    stop = threading.Event()

    def beater():
        while not stop.wait(a.touch_every):
            r = lock_cmd("touch", a.owner, a.lock_cwd)
            print("[touch] rc=%s %s" % (r.returncode, (r.stdout or r.stderr or "").strip()[:160]),
                  flush=True)

    thread = threading.Thread(target=beater, daemon=True)
    thread.start()
    t0 = time.time()
    rc = None
    try:
        rc = subprocess.call([sys.executable, a.driver] + args)
        return rc
    finally:
        stop.set()
        thread.join(timeout=5)
        rel = lock_cmd("release", a.owner, a.lock_cwd)
        print("[release] rc=%s %s  用时 %.1f s"
              % (rel.returncode, (rel.stdout or rel.stderr or "").strip()[:160],
                 time.time() - t0), flush=True)


if __name__ == "__main__":
    sys.exit(main())
