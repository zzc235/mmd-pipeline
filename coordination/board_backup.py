"""运行时 board 的在线一致备份与临时恢复验证（S4）。

为什么不用 shutil.copy / 直接拷 board.db：
  - board 是 WAL 模式，db 文件 + -wal + -shm 三者共同构成"当前状态"；
    裸拷 db 文件只会拿到上一次 checkpoint 的旧快照，丢掉仍在 -wal 里的已提交事务。
  - 标准库 Connection.backup() 走 SQLite 在线备份 API，在源连接上取一致快照，
    自动包含 WAL 中已提交的提交；源以只读 URI 打开，不 checkpoint、不写源。

边界（与 reports/coordination/2026-11-18_小模型交接执行约束.md §5 一致）：
  - 只读源；源不存在/不可读即失败，绝不创建"空板备份"；
  - 目标必须是尚不存在的新文件，默认拒绝覆盖；
  - 不执行 bootstrap/resync，不写任务状态，不改任何业务参数；
  - 不假设源与备份的物理 SHA 相同（页布局/WAL 可不同），以逻辑内容与 integrity_check 判一致；
  - 恢复与对账只在临时副本上做，永不覆盖真实 board。

本模块返回的 state / reason 是**备份工具自己的返回码**，不是 board decision taxonomy 的
reason_code：不写进 board、不进闭集、不参与任何任务状态迁移。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

# 退出码（CLI 与函数共用；失败一律非 0，绝不静默成功）
EXIT_OK = 0
EXIT_SOURCE_MISSING = 2
EXIT_SOURCE_UNREADABLE = 2
EXIT_DEST_EXISTS = 3
EXIT_INTEGRITY_BAD = 4
EXIT_MISMATCH = 5
EXIT_UNEXPECTED = 6

EXIT_CODE = {
    "OK": EXIT_OK,
    "SOURCE_MISSING": EXIT_SOURCE_MISSING,
    "SOURCE_UNREADABLE": EXIT_SOURCE_UNREADABLE,
    "DEST_EXISTS": EXIT_DEST_EXISTS,
    "INTEGRITY_BAD": EXIT_INTEGRITY_BAD,
    "MISMATCH": EXIT_MISMATCH,
    "UNEXPECTED": EXIT_UNEXPECTED,
}

# 契约要求的业务表；缺任意一张即判逻辑不完整（sqlite_sequence 是 AUTOINCREMENT 内部表，不做要求）。
REQUIRED_TABLES = (
    "tasks", "deps", "artifacts", "submission_queue", "verifications",
    "merge_queue", "resources", "events",
)


class BackupError(Exception):
    """备份/验证失败。state 是工具自有的返回码，不是 board reason_code。"""

    def __init__(self, state, message):
        super().__init__(message)
        self.state = state


def _ro_uri(path: str) -> str:
    """只读 URI。沿用 board.py / status.py 的写法，Windows 路径统一成正斜杠。"""
    return "file:%s?mode=ro" % os.path.abspath(path).replace("\\", "/")


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _open_ro(path: str, unreadable_state="SOURCE_UNREADABLE") -> sqlite3.Connection:
    if not os.path.isfile(path):
        raise BackupError("SOURCE_MISSING", "源不存在：%s" % path)
    try:
        conn = sqlite3.connect(_ro_uri(path), uri=True, timeout=5.0)
        conn.execute("SELECT 1")          # 真正触发打开，别把失败拖到后面
        return conn
    except sqlite3.Error as exc:
        raise BackupError(unreadable_state, "源不可读：%s（%s）" % (path, exc))


def _q(table: str) -> str:
    return '"%s"' % table.replace('"', '""')


def all_tables(conn: sqlite3.Connection) -> list:
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]


def integrity(conn: sqlite3.Connection) -> str:
    row = conn.execute("PRAGMA integrity_check").fetchone()
    return row[0] if row else ""


def logical_counts(conn: sqlite3.Connection) -> dict:
    """每张表一行计数，含库里所有表（不止 REQUIRED_TABLES）。"""
    return {t: conn.execute("SELECT COUNT(*) FROM %s" % _q(t)).fetchone()[0]
            for t in all_tables(conn)}


def representative(conn: sqlite3.Connection) -> dict:
    """关键表的代表性内容：证明行数一致之外，行本身也一致。

    - tasks: task_id -> [status, base_commit]
    - events: 按 seq 的 (type, task_id, payload_json)（RUN_ISSUED 的 run_id 在 payload 里）
    事件是 append-only，序列一致即证明运行身份与历史没丢。
    """
    out = {"tasks": {}, "events": []}
    try:
        out["tasks"] = {r[0]: [r[1], r[2]] for r in conn.execute(
            "SELECT task_id,status,base_commit FROM tasks ORDER BY task_id")}
    except sqlite3.Error:
        pass
    try:
        out["events"] = [[r[0], r[1], r[2]] for r in conn.execute(
            "SELECT type,task_id,payload_json FROM events ORDER BY seq")]
    except sqlite3.Error:
        pass
    return out


def backup_board(source: str, destination: str, *, overwrite: bool = False) -> dict:
    """把 source 在线一致备份到 destination，返回 manifest。

    默认目标已存在即失败且不改动它；overwrite=True 仅用于显式重建临时副本，
    真实 board 演练一律不传。
    """
    source = os.path.abspath(source)
    destination = os.path.abspath(destination)
    if not os.path.isfile(source):
        raise BackupError("SOURCE_MISSING", "源不存在：%s" % source)
    if os.path.exists(destination) and not overwrite:
        raise BackupError("DEST_EXISTS", "目标已存在，拒绝覆盖：%s" % destination)

    src_sha_before = file_sha256(source)     # 源已确认存在；缺失分支在上面拦掉
    src = _open_ro(source)
    dst = None
    try:
        if integrity(src) != "ok":
            raise BackupError("INTEGRITY_BAD", "源 integrity_check 非 ok，拒绝备份")
        missing = [t for t in REQUIRED_TABLES if t not in all_tables(src)]
        if missing:
            raise BackupError("INTEGRITY_BAD", "源缺契约表：%s" % ",".join(missing))
        counts_before = logical_counts(src)
        rep_before = representative(src)
        journal = str(src.execute("PRAGMA journal_mode").fetchone()[0]).lower()

        dst = sqlite3.connect(destination, timeout=5.0)
        src.backup(dst)                       # 在线一致备份，含 WAL 已提交数据
    except BackupError:
        raise
    except sqlite3.Error as exc:
        raise BackupError("UNEXPECTED", "备份失败：%s" % exc)
    finally:
        if dst is not None:
            dst.close()
        src.close()

    src_sha_after = file_sha256(source)
    if src_sha_after != src_sha_before:
        raise BackupError(
            "MISMATCH",
            "备份改变了源字节（before=%s after=%s），真实 board 不得被写"
            % (src_sha_before, src_sha_after))

    bk = _open_ro(destination, "MISMATCH")
    try:
        bk_integrity = integrity(bk)
        bk_counts = logical_counts(bk)
        bk_rep = representative(bk)
    finally:
        bk.close()

    if not (bk_integrity == "ok"
            and bk_counts == counts_before
            and bk_rep == rep_before):
        raise BackupError("MISMATCH", "备份与源逻辑内容不一致（integrity/counts/representative）")

    return {
        "tool": "board_backup/1",
        "state": "OK",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_path": source,
        "destination_path": destination,
        "source_sha256_before": src_sha_before,
        "source_sha256_after": src_sha_after,
        "backup_sha256": file_sha256(destination),
        "source_journal_mode": journal,
        "source_integrity": "ok",
        "backup_integrity": bk_integrity,
        "tables_source": counts_before,
        "tables_backup": bk_counts,
        "representative_identical": True,
        "physical_sha_equal_required": False,
    }


def verify_backup(backup_path: str, expected_counts: dict | None = None) -> dict:
    """只读验证一个备份件：integrity + 逻辑计数（+ 可选期望计数）。不写任何文件。"""
    path = os.path.abspath(backup_path)
    if not os.path.isfile(path):
        raise BackupError("SOURCE_MISSING", "备份件不存在：%s" % path)
    result = {
        "tool": "board_backup/1",
        "state": "OK",
        "path": path,
        "sha256": file_sha256(path),
        "integrity": "",
        "tables": {},
        "representative": {"tasks": {}, "events": []},
        "expected_counts_matched": True,
    }
    conn = _open_ro(path, "INTEGRITY_BAD")
    try:
        result["integrity"] = integrity(conn)
        result["tables"] = logical_counts(conn)
        result["representative"] = representative(conn)
    finally:
        conn.close()
    if result["integrity"] != "ok":
        result["state"] = "INTEGRITY_BAD"
    if expected_counts is not None:
        result["expected_counts_matched"] = (result["tables"] == expected_counts)
        if not result["expected_counts_matched"] and result["state"] == "OK":
            result["state"] = "MISMATCH"
    return result


def _stdout_utf8():
    try:
        from .cli import ensure_utf8_stdio
        ensure_utf8_stdio()
    except ImportError:
        pass


def main(argv=None) -> int:
    _stdout_utf8()
    ap = argparse.ArgumentParser(
        prog="coordination.board_backup",
        description="board 在线一致备份与只读验证（S4；源只读、目标默认拒绝覆盖）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    bp = sub.add_parser("backup", help="在线一致备份到新文件")
    bp.add_argument("--source", required=True, help="源 board.db（只读）")
    bp.add_argument("--dest", required=True, help="目标新文件（必须不存在）")
    bp.add_argument("--manifest", default=None,
                    help="可选：把 manifest 另写为 JSON（调用方保证落在临时目录）")
    vp = sub.add_parser("verify", help="只读验证备份件")
    vp.add_argument("--backup", required=True, help="备份件路径")
    vp.add_argument("--expect-counts", default=None,
                    help="可选：期望逻辑计数 JSON 文件（通常由 backup 的 tables_source 取得）")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "backup":
            manifest = backup_board(args.source, args.dest)
            blob = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)
            if args.manifest:
                with open(args.manifest, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(blob + "\n")
            print(blob)
            return EXIT_OK
        expected = None
        if args.expect_counts:
            with open(args.expect_counts, encoding="utf-8") as fh:
                expected = json.load(fh)
        result = verify_backup(args.backup, expected_counts=expected)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return EXIT_CODE.get(result["state"], EXIT_UNEXPECTED)
    except BackupError as exc:
        print(json.dumps({"state": exc.state, "error": str(exc)}, ensure_ascii=False),
              file=sys.stderr)
        return EXIT_CODE.get(exc.state, EXIT_UNEXPECTED)
    except (OSError, ValueError) as exc:
        print(json.dumps({"state": "UNEXPECTED", "error": str(exc)}, ensure_ascii=False),
              file=sys.stderr)
        return EXIT_UNEXPECTED


if __name__ == "__main__":
    sys.exit(main())
