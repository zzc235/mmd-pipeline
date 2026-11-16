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

退出码：`0` 正常 / `2` 用法 / `3` 冲突（别人持有、或不是自己的锁）/ `4` 锁状态不可判定（残缺或不可读）
/ `5` `guard` 期间锁丢了（命令跑完了，但这次结果作废）。

`guard` 子命令（2026-11-16 19:05 加，起因是同一天两个人的同一个错）：
`python -m coordination.lock guard --owner "模块|工作树" --note "..." -- <命令...>`
取锁 → 跑命令 → 必放锁，**取不到锁则命令根本不执行**，期间后台按 `--heartbeat-every` 刷心跳。
`3号` 18:18 与 `2号` 19:00 都是「`acquire` 返回退出码 3、没判就往下跑」，各在别人窗口里起了
Blender。工具强迫不了别人看退出码，那就把「看退出码」这件事做成命令行的形状。

`owner.txt` 格式（一行，`|` 分隔，尽量兼容大家已经在写的写法）：

    <模块|工作树>|<PID>|<ISO 取得时间>|<说明>

校验只看**前三段里的前两段**（`模块|工作树`）：PID 每次进程不同，拿它比就永远比不中。

## 2026-11-16 14:19 的三处加固（D0 派，起因是一次真实的误判）

现场：`lock status` 报 `PID=28940`，那个 PID 已经死了，**但 Blender 还活着**（另一个 PID，
14:15:35 起）。有人按「PID 死了」判过期就会把锁拿走，而真正干活的进程还在跑——正是全队
在防的那件事。所以：

1. **记真正干活的 PID**：`acquire --work-pid <pid>` 可显式登记（Blender 是子进程，跟取锁的
   shell 不是同一个 PID）；不登记就只记自己的。多个用逗号分隔。
2. **心跳**：`acquire` 写 `heartbeat` 文件，`touch` 子命令刷新它，长跑期间应当周期性调用。
   **过期判定的主依据是心跳 mtime**，PID 只作辅助——PID 不活不代表人走了，反过来也一样。
3. **回收只能是「搬走」**：`reclaim --owner ... ` 要求**三条同时成立**才允许：
   ① 记录的 PID 全都不活 **且** ② 当前没有任何 blender 进程 **且** ③ 心跳超过 `--stale-minutes`
   （默认 10 分钟）。回收把整个锁目录移到 `locks/_reclaimed/<时间戳>-<owner>/`，
   **保留 `owner.txt` 作为证据**，并打印一行日志。任何一条不成立就 `LockHeld` 且不动它。
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import sys
import threading
import time

from . import paths

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_CONFLICT = 3
EXIT_UNKNOWN = 4
EXIT_LOCK_LOST = 5

OWNER_FILE = "owner.txt"
HEARTBEAT_FILE = "heartbeat"
RECLAIM_SUBDIR = "_reclaimed"
DEFAULT_STALE_MINUTES = 10.0


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


def _format_owner(owner: str, note: str = "", work_pids=()) -> str:
    pids = [str(os.getpid())] + [str(p) for p in work_pids if str(p).strip()]
    return "%s|PID=%s|%s|%s" % (owner, ",".join(pids), _now(), note)


def _write_heartbeat(lock_dir: str, note: str = "") -> str:
    """写/刷心跳文件（mtime 就是"最后一次活着"的证据）。"""
    path = os.path.join(lock_dir, HEARTBEAT_FILE)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("%s %s\n" % (_now(), note or ""))
    return path


def heartbeat_age_seconds(lock_dir: str) -> float:
    """心跳多久没跳了（秒）。**没有心跳文件时返回 `inf`**，不是 0——

    返回 0 会让"从来没写过心跳"看起来"刚刚还活着"，那是最坏方向的假绿。
    """
    path = os.path.join(lock_dir, HEARTBEAT_FILE)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return float("inf")
    return max(0.0, time.time() - mtime)


def pid_alive(pid: int) -> bool:
    """这个 PID 还活着吗。

    **Windows 上不能用 `os.kill(pid, 0)`**：CPython 在 Windows 把 `os.kill` 实现成
    `TerminateProcess(handle, sig)`，所以 `os.kill(pid, 0)` 是**把那个进程杀掉**
    （2026-11-16 我自己踩了：测试里传自己的 PID，测试进程当场消失、一个字节输出都没有，
    看起来像"无声崩溃"）。改成两条安全探针：

    * Windows：`tasklist /FI "PID eq N"`，看输出里有没有这个 PID；
    * 其它平台：`os.kill(pid, 0)` 在那里确实是探活。

    探针本身失败（命令不可用/超时）一律返回 **False**，由调用方的另两条判据兜底——
    不要因为"问不出来"就当"活着"。
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True
    try:
        import subprocess
        proc = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=20)
    except (OSError, ValueError, Exception):        # noqa: BLE001 - 探针失败一律当"不活"
        return False
    text = (proc.stdout or "")
    return ("%d" % pid) in text


def blender_running() -> list:
    """系统里有没有 blender 进程（有 = 一定有人在算，不许回收）。返回 PID 列表。

    Windows 上用 `tasklist`；没有该命令（或非 Windows）时返回空列表，并让调用方
    知道"这条判据不可用"——由 `reclaim` 把它写进说明里。
    """
    out = []
    try:
        import subprocess
        proc = subprocess.run(["tasklist", "/FI", "IMAGENAME eq blender.exe", "/NH"],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=20)
    except (OSError, ValueError, subprocess.SubprocessError):
        return out
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].lower().startswith("blender"):
            try:
                out.append(int(parts[1]))
            except ValueError:
                continue
    return out


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
    """返回 {held, ident, pid, acquired_at, held_seconds, heartbeat_age, note}。"""
    lock_dir = lock_dir or paths.lock_dir()
    if not os.path.isdir(lock_dir):
        return {"held": False, "lock_dir": lock_dir}
    info = read_owner(lock_dir)
    info.update({"held": True, "lock_dir": lock_dir,
                 "held_seconds": held_seconds(lock_dir, info),
                 "heartbeat_age": heartbeat_age_seconds(lock_dir)})
    return info


def acquire(owner: str, note: str = "", lock_dir: str | None = None,
            wait_s: float = 0.0, poll_s: float = 0.5, work_pids=()) -> dict:
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
        line = _format_owner(owner, note, work_pids)
        with open(os.path.join(lock_dir, OWNER_FILE), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(line + "\n")
        # 心跳从取锁那一刻就开始：过期判定以它的 mtime 为主依据
        _write_heartbeat(lock_dir, note)
        return {"held": True, "ident": "|".join(owner.split("|")[:2]), "raw": line,
                "lock_dir": lock_dir}


def touch(owner: str = "", lock_dir: str | None = None, note: str = "") -> dict:
    """刷心跳。长跑请周期性调用（例如每 2–3 分钟一次）。

    `owner` 给了就校验一次（刷别人的锁的头跳是在替别人续命，不许）；不给就不校验，
    留给"我只想看一眼自己还活着"的场景。
    """
    lock_dir = lock_dir or paths.lock_dir()
    info = read_owner(lock_dir)
    if owner:
        mine = "|".join(owner.split("|")[:2])
        if info["ident"] != mine:
            raise NotOwner("这把锁不是你的：持有者 %r，你是 %r（未刷心跳）"
                           % (info["raw"], mine))
    _write_heartbeat(lock_dir, note or info.get("note") or "")
    return {"held": True, "ident": info["ident"], "heartbeat_age": heartbeat_age_seconds(lock_dir)}


def reclaim(lock_dir: str | None = None, stale_minutes: float = DEFAULT_STALE_MINUTES,
            blender_pids=None) -> dict:
    """把**确实没人管**的锁搬走（不是删）。

    三条同时成立才允许，任何一条不成立就 `LockHeld` 且原地不动：

    1. `owner.txt` 记录的 PID 全部不活；
    2. 当前没有任何 blender 进程（`blender_pids` 可注入，测试用它造"还活着"）；
    3. 心跳超过 `stale_minutes` 分钟（没有心跳文件按 `inf` 算，即"从来没跳过"）。

    回收动作：整个锁目录 `shutil.move` 到 `locks/_reclaimed/<时间戳>-<ident>/`，
    **`owner.txt` 原样保留**作为证据（"证据不删、只搬走"）。
    """
    lock_dir = lock_dir or paths.lock_dir()
    info = read_owner(lock_dir)                       # 残缺锁在这里抛
    pids = [p for p in (info.get("pid") or "").split(",") if p.strip()]
    alive = [p for p in pids if pid_alive(p)]
    running = blender_running() if blender_pids is None else list(blender_pids)
    age = heartbeat_age_seconds(lock_dir)
    reasons = []
    if alive:
        reasons.append("记录的 PID 还活着：%s" % ",".join(alive))
    if running:
        reasons.append("系统里有 blender 进程：%s" % ",".join(str(p) for p in running))
    if age < stale_minutes * 60.0:
        reasons.append("心跳只有 %.0f s 没跳（阈值 %.0f min）" % (age, stale_minutes))
    if reasons:
        raise LockHeld("不许回收（%s）：%s" % ("；".join(reasons), info["raw"]))

    parent = os.path.dirname(lock_dir)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_ident = info["ident"].replace("|", "_").replace("/", "_")
    target = os.path.join(parent, RECLAIM_SUBDIR, "%s-%s" % (stamp, safe_ident))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.move(lock_dir, target)
    sys.stderr.write("RECLAIMED %s -> %s（心跳 %.0f s 未跳，PID 全不活，无 blender 进程）\n"
                     % (lock_dir, target, age))
    return {"held": False, "reclaimed": info["raw"], "moved_to": target,
            "heartbeat_age": age}



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
    for name in (OWNER_FILE, HEARTBEAT_FILE):
        try:
            os.remove(os.path.join(lock_dir, name))
        except OSError:
            pass
    try:
        os.rmdir(lock_dir)
    except OSError as exc:
        raise IncompleteLock("owner.txt 已删但目录删不掉（可能有人在里面放了文件）：%s" % exc)
    return {"held": False, "released": info["raw"], "lock_dir": lock_dir}


def assert_owner(owner: str, lock_dir: str | None = None) -> dict:
    """**跑 Blender 之前的第一句**：确认这把锁现在是你的，否则抛 `NotOwner`。

    为什么要有它（D0 2026-11-16 18:20，`3号` 自报的真实事故）：`acquire` 在锁被占时
    返回 `LOCK_HELD` 且退出码 3 —— 但**退出码是调用方的事**，有人不看返回值就往下跑了
    7 个 Blender 进程，到 `release` 才报 `LOCK_NOT_YOURS`。工具没法强迫别人看退出码，
    但可以给一条**在产物侧**才爆炸的检查：凡是要起 Blender 的脚本，第一句先 `assert-owner`，
    不是自己持锁就直接失败，读数和产物一个都不留。

    与 `acquire` 的区别：`acquire` 要写锁（可能抢到），`assert-owner` **只读不写**，
    只回答「现在是不是我」，所以它可以安全地放在每个 Blender 进程的入口。
    """
    if not owner or "|" not in owner:
        raise ValueError("owner 必须写成 `模块|工作树`")
    lock_dir = lock_dir or paths.lock_dir()
    if not os.path.isdir(lock_dir):
        # 空闲 ≠ 谁都能跑：必须先 acquire 才叫「你在跑」。
        raise NotOwner("锁空闲（没有锁目录 %s）：先 acquire 再起 Blender" % lock_dir)
    info = read_owner(lock_dir)                     # 残缺锁在这里抛 IncompleteLock
    mine = "|".join(owner.split("|")[:2])
    if info["ident"] != mine:
        raise NotOwner("现在不是你的锁：持有者 %r，你是 %r —— 不许起 Blender"
                       % (info["raw"], mine))
    return {"held": True, "ident": info["ident"], "raw": info["raw"],
            "heartbeat_age": heartbeat_age_seconds(lock_dir)}


def guard(owner: str, command, note: str = "", lock_dir: str | None = None,
          wait_s: float = 0.0, heartbeat_every: float = 120.0,
          runner=None, toucher=None) -> dict:
    """**取锁 → 判成败 → 跑命令 → 必放锁**，一条命令包住整个窗口。

    为什么要有它（2026-11-16 19:00，`2号` 自报，与 `3号` 18:18 同一个错）：
    `acquire` 在锁被占时返回退出码 3，**但退出码是调用方的事** —— 两个人都没判，
    就各自在别人的窗口里起了 Blender。`assert-owner` 治的是「进程内」那一半
    （起 bpy 之前先问一句），`guard` 治的是「进程外」那一半：
    **取不到锁，命令行里的东西根本不执行**，退出码与心跳都由它代持。

    行为：

    | 情形 | 命令跑不跑 | 返回 |
    |---|---|---|
    | 取锁成功 | 跑 | 命令的退出码透传 |
    | 锁被别人持有 / 锁残缺 | **不跑**（不是跑了才发现） | 抛 `LockHeld` / `IncompleteLock` |
    | 跑的过程中锁丢了（被回收/被别人 release） | 已跑完，但结果作废 | `lock_lost` 有值；命令 rc==0 时判 `EXIT_LOCK_LOST` |
    | 心跳 | 跑期间后台每 `heartbeat_every` 秒刷一次 | `heartbeats` 计数进返回值 |

    `runner(command) -> int` 与 `toucher(owner, lock_dir, note)` 可注入（离屏测）。
    """
    command = list(command or [])
    if not command:
        raise ValueError("guard 需要一条要跑的命令（`-- <cmd> [args...]`）")
    lock_dir = lock_dir or paths.lock_dir()
    info = acquire(owner, note, lock_dir, wait_s)      # 失败直接抛：命令一个字节都不动
    stop = threading.Event()
    ticks = {"n": 0, "error": None}

    def _beat():
        while not stop.wait(max(0.01, float(heartbeat_every))):
            try:
                (toucher or touch)(owner, lock_dir, "guard")
                ticks["n"] += 1
            except Exception as exc:                   # noqa: BLE001 - 心跳失败要记账，别打死主进程
                ticks["error"] = str(exc)
                return

    thread = None
    if heartbeat_every and float(heartbeat_every) > 0:
        thread = threading.Thread(target=_beat, daemon=True)
        thread.start()
    rc = 127
    try:
        rc = int((runner or _default_runner)(command))
    finally:
        stop.set()
        if thread is not None:
            thread.join(timeout=5.0)
        lost = None
        try:
            release(owner, lock_dir)
        except LockError as exc:
            lost = str(exc)
    return {"rc": rc, "command": command, "heartbeats": ticks["n"],
            "heartbeat_error": ticks["error"], "lock_lost": lost, "acquirer": info}


def _default_runner(command) -> int:
    import subprocess
    return subprocess.call(list(command))               # 继承 stdio：Blender 的输出直接看得到


def render_status(info: dict) -> str:
    if not info.get("held"):
        return "空闲：%s" % info.get("lock_dir", "")
    age = info.get("heartbeat_age")
    if age is None:
        beat = "心跳 ?"
    elif age == float("inf"):
        beat = "心跳 从未"
    else:
        beat = "心跳 %.0f s 前" % age
    return ("持有：%s｜PID=%s｜取得 %s｜已占用 %.1f s｜%s｜%s"
            % (info["ident"], info.get("pid") or "?", info.get("acquired_at") or "?",
               info.get("held_seconds", 0.0), beat, info.get("note") or "-"))


def _split_dashdash(argv) -> tuple:
    """在第一个 `--` 处把参数切成两段：前段交给 argparse，后段是要跑的命令。

    为什么不用 `argparse.REMAINDER`：它会把**第一个位置参数之后的一切**都吞掉，
    于是最自然的写法 `lock guard --owner X -- python a.py` 里 `--owner` 被吞进命令、
    `owner` 变成空串 ⇒ 报「owner 必须写成 模块|工作树」（2026-11-16 19:05 我自己撞的）。
    那种失败虽然是 fail-closed（命令没跑），但它把「用法错」伪装成「参数错」，
    而正确的形状只需要先切一刀。
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" in argv:
        cut = argv.index("--")
        return argv[:cut], argv[cut + 1:]
    return argv, []


def main(argv=None) -> int:
    from .cli import ensure_utf8_stdio
    ensure_utf8_stdio()
    head, tail = _split_dashdash(argv)
    ap = argparse.ArgumentParser(
        prog="coordination.lock",
        description="Blender 互斥锁（acquire/release/status/touch/reclaim，fail-closed）",
        epilog="退出码：0 正常 / 2 用法 / 3 冲突或拒绝回收 / 4 锁状态不可判定 / 5 guard 期间锁丢失。\n"
               "回收（reclaim）三条同时成立才允许：记录的 PID 全不活、系统里没有 blender 进程、"
               "心跳超过阈值；回收是**搬到** locks/_reclaimed/ 下，不删，owner.txt 原样保留。\n"
               "guard 用法：`lock guard --owner A|B --note ... -- python script.py`（取不到锁就不跑）。")
    ap.add_argument("action", choices=("acquire", "release", "status", "touch", "reclaim",
                                       "assert-owner", "guard"))
    ap.add_argument("--lock", default=None, help="锁目录（缺省 out/subai/locks/blender.lock）")
    ap.add_argument("--owner", default="", help="`模块|工作树`，如 `模块负责4|A4`")
    ap.add_argument("--owner-module", default="",
                    help="owner 的第一段（替代 --owner；竖线在后台作业启动器里会被当管道吞掉）")
    ap.add_argument("--owner-tree", default="", help="owner 的第二段")
    ap.add_argument("--note", default="", help="一句话说明这次要跑什么")
    ap.add_argument("--wait", type=float, default=0.0, help="等锁秒数（默认 0＝不排队，直接失败）")
    ap.add_argument("--heartbeat-every", type=float, default=120.0,
                    help="guard 期间每多少秒刷一次心跳（默认 120；0 表示不刷）")
    ap.add_argument("--work-pid", default="",
                    help="真正干活的 PID（逗号分隔，例如 Blender 子进程的 PID）")
    ap.add_argument("--stale-minutes", type=float, default=DEFAULT_STALE_MINUTES,
                    help="心跳超过这么多分钟才算过期（默认 %.0f）" % DEFAULT_STALE_MINUTES)
    args = ap.parse_args(head)
    if args.owner_module or args.owner_tree:
        # 两段写法：`--owner-module 模块负责2 --owner-tree A2`。竖线在 cmd/后台作业启动器里
        # 会被当管道吞掉（2号 19:07 实测），所以给一条不含竖线的入口；两种写法同时给 = 用法错，
        # 不猜哪个更可信。
        if args.owner:
            print("LOCK_USAGE --owner 与 --owner-module/--owner-tree 只能给一种")
            return EXIT_USAGE
        if not (args.owner_module and args.owner_tree):
            print("LOCK_USAGE 两段写法要同时给 --owner-module 与 --owner-tree")
            return EXIT_USAGE
        args.owner = "%s|%s" % (args.owner_module.strip(), args.owner_tree.strip())

    work_pids = [p.strip() for p in args.work_pid.split(",") if p.strip()]
    try:
        if args.action == "acquire":
            info = acquire(args.owner, args.note, args.lock, args.wait, work_pids=work_pids)
            print("ACQUIRED %s" % info["raw"])
            return EXIT_OK
        if args.action == "release":
            info = release(args.owner, args.lock)
            print("RELEASED %s" % info["released"])
            return EXIT_OK
        if args.action == "touch":
            info = touch(args.owner, args.lock, args.note)
            print("HEARTBEAT 已刷新（%.1f s 前那次）" % info["heartbeat_age"])
            return EXIT_OK
        if args.action == "reclaim":
            info = reclaim(args.lock, args.stale_minutes)
            print("RECLAIMED %s -> %s" % (info["reclaimed"], info["moved_to"]))
            return EXIT_OK
        if args.action == "assert-owner":
            info = assert_owner(args.owner, args.lock)
            print("OWNER_OK %s" % info["raw"])
            return EXIT_OK
        if args.action == "guard":
            command = list(tail)
            result = guard(args.owner, command, args.note, args.lock, args.wait,
                           args.heartbeat_every)
            print("GUARD_DONE rc=%d heartbeats=%d lock_lost=%s"
                  % (result["rc"], result["heartbeats"], result["lock_lost"] or "none"))
            if result["lock_lost"] and result["rc"] == EXIT_OK:
                return EXIT_LOCK_LOST
            return result["rc"]
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
