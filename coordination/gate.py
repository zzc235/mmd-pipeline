"""格式闸门：`files[]` 必须覆盖 `git diff base..HEAD` 的每一个文件。

为什么这是闸门而不是提醒：M04 那笔用"这一笔改了什么"冒充"这条分支上有哪些文件"，
漏掉三个未被验证的文件，差一点被合进基线。靠人记就会再犯一次，所以做成机械检查
（D-20261116-022 · 规范 §4.2）：缺任何一个文件即 `MISSING_EVIDENCE`，不进入验证。

判据只认 git 的事实，不认提交说明、不认报告正文。
"""
from __future__ import annotations

import os
import subprocess

from . import evidence as evidence_mod


class CoverageError(evidence_mod.EvidenceError):
    """files[] 没覆盖整条分支的改动。"""

    def __init__(self, missing, changed, reason_code="MISSING_EVIDENCE"):
        super().__init__("files[] 未覆盖分支改动：缺 %s（分支共 %d 个文件）"
                         % (", ".join(missing), len(changed)), reason_code)
        self.missing = list(missing)
        self.changed = list(changed)


def _diff(base: str, head: str, repo: str | None, filter_expr: str) -> list:
    """三点式 `git diff base...head`：从**共同祖先**算起，而不是从 base 当前 tip。

    为什么必须三点：分支落后于 main 时，`main..HEAD` 会把 main 上别人合进来的提交
    也算成"你的改动"，逼着你在 files[] 里列一堆没碰过的文件（M00 第一版就撞过，
    把 coordination/decisions.jsonl 算成缺项）。三点只算你这条分支真正带来的差异。
    """
    repo = repo or os.getcwd()
    try:
        out = subprocess.run(["git", "-C", repo, "diff", "--name-only",
                              "--diff-filter=" + filter_expr,
                              "%s...%s" % (base, head)],
                             capture_output=True, text=True, encoding="utf-8", timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise evidence_mod.EvidenceError(
            "无法计算 files[] 覆盖（git 不可用）：%s" % exc, "MISSING_EVIDENCE") from exc
    if out.returncode != 0:
        raise evidence_mod.EvidenceError(
            "无法计算 files[] 覆盖（git diff %s..%s 失败）：%s"
            % (base, head, (out.stderr or "").strip()[:200]), "MISSING_EVIDENCE")
    names = [evidence_mod.norm_path(line) for line in out.stdout.splitlines() if line.strip()]
    return sorted(set(names))


def changed_files(base: str, head: str = "HEAD", repo: str | None = None) -> list:
    """需要被 `files[]` 覆盖的文件：新增/修改/复制/重命名（ACMR）。

    **删除的文件不在此列**：删除后没有内容可算 sha256，而 `files[]` 每项都要求
    64 位 sha256（evidence_hash_v1.md §3）。硬要把它塞进去只能造一个假哈希，
    那比不列更坏。删除单独由 `deleted_files()` 列出，并在提交时记事件留痕。
    这一条与规范 §4.2 的字面有出入，已在 SUBMISSION 里明说，等 D0 决定是否升 spec。
    """
    return _diff(base, head, repo, "ACMR")


def deleted_files(base: str, head: str = "HEAD", repo: str | None = None) -> list:
    """分支上被删除的文件（无法进 files[]，单独报告）。"""
    return _diff(base, head, repo, "D")


def check_coverage(files, base: str, head: str = "HEAD", repo: str | None = None) -> dict:
    """缺失即抛 CoverageError；通过返回 {base, head, changed, deleted, covered}。"""
    changed = changed_files(base, head=head, repo=repo)
    deleted = deleted_files(base, head=head, repo=repo)
    covered = {evidence_mod.norm_path(f["path"]) for f in files}
    missing = [p for p in changed if p not in covered]
    if missing:
        raise CoverageError(missing, changed)
    return {"base": base, "head": head, "changed": changed,
            "deleted": deleted, "covered": sorted(covered)}
