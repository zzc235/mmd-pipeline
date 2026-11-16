"""Blender 互斥锁：`acquire` / `release` / `status`（纯标准库，不 import bpy）。

    python -m coordination.lock status
    python -m coordination.lock acquire  --owner "模块负责4|A4" --note "M07 D 段打包"
    python -m coordination.lock release  --owner "模块负责4|A4"

为什么要有这一层：原来四个人各自手写 `New-Item` / `Remove-Item`，今天撞出两次事故——

* `New-Item -ItemType Directory -Force` 在目录**已存在**时不报错：以为取到了锁，其实没有，
  两个人真的并行跑过 Blender（1号 自报）；
* `finally { Remove-Item -Recurse -Force }` 无条件删：**删掉的是别人的锁**，
  等于替别人宣布"跑完了"（1号 13:32/13:34 两把，2号 13:31/13:33 两把）。

所以规矩落进代码，而不是靠自觉：

| 动作 | 行为 | 失败时 |
|---|---|---|
| `acquire` | `os.mkdir` 原子建目录（**存在即失败，绝不覆盖**），成功后写 `owner.txt` | `LockHeld`：打印持锁人的 `owner.txt` 原文 |
| `release` | 先读 `owner.txt` 校验 `--owner` 前缀一致才删 | `NotOwner`：打印实际持有者，**不删** |
| `status` | 打印持有者、PID、取得时间、已占用秒数 | 目录在但没 `owner.txt` → `IncompleteLock`（**当异常退出，不当空闲**） |

退出码：`0` 正常 / `2` 用法 / `3` 冲突（别人持有、或不是自己的锁）/ `4` 锁状态不可判定（残缺或不可读）。

`owner.txt` 格式（一行，`|` 分隔，尽量兼容大家已经在写的写法）：

    <模块|工作树>|<PID>|<ISO 取得时间>|<说明>

校验只看**前三段里的前两段**（`模块|工作树`）：PID 每次进程不同，拿它比就永远比不中。
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time

from . import paths

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_CONFLICT = 3
EXIT_UNKNOWN = 4

OWNER_FILE = "owner.txt"


class LockError(RuntimeError):
    exit_code = EXIT_CONFLICT


class LockHeld(LockError):
    """锁已经被别人持有。"""


class NotOwner(LockError):
    """想释放的锁不是自己的。"""


class IncompleteLock(LockError):
    """锁目录在，但读不出持有者——当作异常，不当空闲。"""

    exit_code = EXIT_UNKNOWN


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _format_owner(owner: str, note: str = "") -> str:
    return "%s|PID=%d|%s|%s" % (owner, os.getpid(), _now(), note)


def parse_owner_line(text: str) -> dict:
    """把 `owner.txt` 拆成 dict；拆不出来抛 IncompleteLock。"""
    line = (text or "").strip()
    if not line:
        raise IncompleteLock("owner.txt 是空的")
    parts = line.split("|")
    if len(parts) < 2 or not parts[0].strip():
        raise IncompleteLock("owner.txt 格式不对（至少要 `模块|工作树`）：%r" % line)
    ident = "|".join(p.strip() for p in parts[:2])
    pid = ""
    stamp = ""
    note = ""
    for part in parts[2:]:
        part = part.strip()
        if part.upper().startswith("PID="):
            pid = part[4:]
        elif part[:2].isdigit() and "-" in part:
            stamp = part
        elif part:
            note = part
    return {"ident": ident, "pid": pid, "acquired_at": stamp, "note": note, "raw": line}


def read_owner(lock_dir: str) -> dict:
    if not os.path.isdir(lock_dir):
        raise IncompleteLock("锁目录不存在：%s" % lock_dir)
    path = os.path.join(lock_dir, OWNER_FILE)
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            text = fh.read()
    except OSError as exc:
        raise IncompleteLock("锁目录在，但 owner.txt 读不到：%s（%s）" % (path, exc))
    return parse_owner_line(text)


def held_seconds(lock_dir: str, owner_info: dict | None = None) -> float:
    info = owner_info or read_owner(lock_dir)
    stamp = info.get("acquired_at") or ""
    if not stamp:
        return 0.0
    try:
        started = dt.datetime.fromisoformat(stamp)
    except ValueError:
        return 0.0
    now = dt.datetime.now().astimezone()
    if started.tzinfo is None:
        started = started.replace(tzinfo=now.tzinfo)
    return max(0.0, (now - started).total_seconds())


def status(lock_dir: str | None = None) -> dict:
    """返回 {held, ident, pid, acquired_at, held_seconds, note}；残缺锁抛 IncompleteLock。"""
    lock_dir = lock_dir or paths.lock_dir()
    if not os.path.isdir(lock_dir):
        return {"held": False, "lock_dir": lock_dir}
    info = read_owner(lock_dir)
    info.update({"held": True, "lock_dir": lock_dir,
                 "held_seconds": held_seconds(lock_dir, info)})
    return info


def acquire(owner: str, note: str = "", lock_dir: str | None = None,
            wait_s: float = 0.0, poll_s: float = 0.5) -> dict:
    """原子取锁。锁存在即失败——**绝不覆盖**，`mkdir` 的原子性就是互斥本身。"""
    if not owner or "|" not in owner:
        raise ValueError("owner 必须写成 `模块|工作树`，例如 `模块负责4|A4`")
    lock_dir = lock_dir or paths.lock_dir()
    os.makedirs(os.path.dirname(lock_dir), exist_ok=True)
    deadline = time.time() + max(0.0, wait_s)
    while True:
        try:
            os.mkdir(lock_dir)          # 已存在 → FileExistsError，这就是"fail closed"
        except FileExistsError:
            if time.time() >= deadline:
                try:
                    info = read_owner(lock_dir)
                except IncompleteLock:
                    raise IncompleteLock(
                        "锁目录在但没有可读的 owner.txt：%s（先人工确认，别删）" % lock_dir)
                raise LockHeld("锁已被持有：%s" % info["raw"])
            time.sleep(poll_s)
            continue
        line = _format_owner(owner, note)
        with open(os.path.join(lock_dir, OWNER_FILE), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(line + "\n")
        return {"held": True, "ident": "|".join(owner.split("|")[:2]), "raw": line,
                "lock_dir": lock_dir}


def release(owner: str, lock_dir: str | None = None) -> dict:
    """释放锁。**只删自己的**：`owner.txt` 里的 `模块|工作树` 与 `--owner` 不一致就抛。"""
    if not owner or "|" not in owner:
        raise ValueError("owner 必须写成 `模块|工作树`")
    lock_dir = lock_dir or paths.lock_dir()
    info = read_owner(lock_dir)                     # 残缺锁在这里抛 IncompleteLock
    mine = "|".join(owner.split("|")[:2])
    if info["ident"] != mine:
        raise NotOwner("这把锁不是你的：持有者 %r，你是 %r（未删除）"
                       % (info["raw"], mine))
    path = os.path.join(lock_dir, OWNER_FILE)
    try:
        os.remove(path)
    except OSError:
        pass
    try:
        os.rmdir(lock_dir)
    except OSError as exc:
        raise IncompleteLock("owner.txt 已删但目录删不掉（可能有人在里面放了文件）：%s" % exc)
    return {"held": False, "released": info["raw"], "lock_dir": lock_dir}


def render_status(info: dict) -> str:
    if not info.get("held"):
        return "空闲：%s" % info.get("lock_dir", "")
    return ("持有：%s｜PID=%s｜取得 %s｜已占用 %.1f s｜%s"
            % (info["ident"], info.get("pid") or "?", info.get("acquired_at") or "?",
               info.get("held_seconds", 0.0), info.get("note") or "-"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="coordination.lock",
                                 description="Blender 互斥锁（acquire/release/status，fail-closed）")
    ap.add_argument("action", choices=("acquire", "release", "status"))
    ap.add_argument("--lock", default=None, help="锁目录（缺省 out/subai/locks/blender.lock）")
    ap.add_argument("--owner", default="", help="`模块|工作树`，如 `模块负责4|A4`")
    ap.add_argument("--note", default="", help="一句话说明这次要跑什么")
    ap.add_argument("--wait", type=float, default=0.0, help="等锁秒数（默认 0＝不排队，直接失败）")
    args = ap.parse_args(argv)

    try:
        if args.action == "acquire":
            info = acquire(args.owner, args.note, args.lock, args.wait)
            print("ACQUIRED %s" % info["raw"])
            return EXIT_OK
        if args.action == "release":
            info = release(args.owner, args.lock)
            print("RELEASED %s" % info["released"])
            return EXIT_OK
        print(render_status(status(args.lock)))
        return EXIT_OK
    except IncompleteLock as exc:
        print("LOCK_UNKNOWN %s" % exc)
        return EXIT_UNKNOWN
    except LockHeld as exc:
        print("LOCK_HELD %s" % exc)
        return EXIT_CONFLICT
    except NotOwner as exc:
        print("LOCK_NOT_YOURS %s" % exc)
        return EXIT_CONFLICT
    except ValueError as exc:
        print("LOCK_USAGE %s" % exc)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
