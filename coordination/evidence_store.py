"""证据快照：被 evidence 引用的 artifact 必须能在事后复原（D-157 / D-159）。

**要解决的问题**（实测过的洞）：
`reports/` 不进 git，于是 `evidence` 里记的 `artifacts[].sha256` 只能证明
「那一刻磁盘上是什么」。文件后来被改名、移走、或原地改写，那条哈希就永远无法复原——
`known_limits.md` 的 `7ac68dd6…` 就是这么变成一条永久失效记录的（全盘搜索无副本）。
**哈希不能替代副本。**

规矩：文本类 artifact 落一份**原字节**副本到

    out/subai/_evidence_store/<artifact_sha256 前 16 位>/<原文件名>

目录名取哈希前缀而不是 digest 全串，是为了「同一份字节只有一份副本」且路径可读；
证据记录里同时写 `path`（原位置）、`sha256`、`snapshot`（副本路径），
`verify()` 用副本重算，与记录不符即判 `SNAPSHOT_INVALID`。

快照目录**不进 git**（二进制 / 大文本），但它是**只写不改**的：
同一路径已有副本且字节不同 ⇒ 直接报错，绝不覆盖（覆盖等于销毁证据）。
"""
from __future__ import annotations

import hashlib
import os
import shutil

from . import paths

STORE_DIRNAME = "_evidence_store"
SHA16 = 16


class SnapshotError(RuntimeError):
    def __init__(self, message: str, reason_code: str = "SNAPSHOT_INVALID"):
        super().__init__(message)
        self.reason_code = reason_code


def store_root(root: str | None = None) -> str:
    """快照根：主工作树 `out/subai/_evidence_store`（四棵树共享同一个根）。"""
    if root:
        return os.path.normpath(os.path.abspath(root))
    main_root = paths.main_worktree_root()
    base = main_root or os.path.abspath(os.getcwd())
    return os.path.normpath(os.path.join(base, "out", "subai", STORE_DIRNAME))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return sha256_bytes(fh.read())


def snapshot_path(artifact_sha256: str, filename: str | None = None,
                  root: str | None = None, original_path: str | None = None) -> str:
    """由 artifact 的 sha256 推出快照路径（`filename` 缺省取原文件名）。"""
    digest = (artifact_sha256 or "").strip().lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise SnapshotError("artifact sha256 必须是 64 位小写 hex：%r" % (artifact_sha256,),
                            "HASH_BASIS_INVALID")
    name = filename or (os.path.basename(original_path) if original_path else "artifact.bin")
    if not name:
        raise SnapshotError("快照需要文件名", "SNAPSHOT_INVALID")
    return os.path.join(store_root(root), digest[:SHA16], name)


def snapshot_artifact(path: str, sha256: str | None = None, root: str | None = None) -> dict:
    """把 `path` 的原字节复制进快照库，返回可直接写进 `artifacts[]` 的行。"""
    if not os.path.isfile(path):
        raise SnapshotError("artifact 不存在：%s" % (path,), "SNAPSHOT_INVALID")
    digest = (sha256 or file_sha256(path)).strip().lower()
    actual = file_sha256(path)
    if digest != actual:
        raise SnapshotError("声明的 sha256 %s 与磁盘 %s 不符（快照拒绝存错字节）"
                            % (digest[:16], actual[:16]), "HASH_BASIS_INVALID")
    target = snapshot_path(digest, root=root, original_path=path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.exists(target):
        if file_sha256(target) != digest:
            raise SnapshotError("快照已存在且字节不同，拒绝覆盖：%s" % target, "SNAPSHOT_INVALID")
    else:
        tmp = target + ".tmp"
        shutil.copyfile(path, tmp)
        os.replace(tmp, target)
    return {"path": path.replace("\\", "/"), "sha256": digest,
            "bytes": os.path.getsize(path), "snapshot": target.replace("\\", "/")}


def verify(record: dict) -> dict:
    """核一份 `artifacts[]` 行：快照在不在、字节还对不对。"""
    path = record.get("path") or ""
    declared = (record.get("sha256") or "").strip().lower()
    snapshot = record.get("snapshot") or ""
    problems = []
    if not declared:
        problems.append("没写 sha256")
    if not snapshot:
        problems.append("没写 snapshot（D-159 之后必须写；reports/ 不进 git，哈希无法复原）")
    elif not os.path.isfile(snapshot):
        problems.append("快照不存在：%s" % snapshot)
    elif declared and file_sha256(snapshot) != declared:
        problems.append("快照字节与声明的 sha256 不符：%s" % snapshot)
    return {"ok": not problems, "path": path, "sha256": declared,
            "snapshot": snapshot, "problems": problems}
