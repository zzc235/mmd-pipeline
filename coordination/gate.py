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


def changed_files(base: str, head: str = "HEAD", repo: str | None = None) -> list:
    """`git diff --name-only base..head`，POSIX 分隔符、按码点升序。"""
    repo = repo or os.getcwd()
    try:
        out = subprocess.run(["git", "-C", repo, "diff", "--name-only", "%s..%s" % (base, head)],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CoverageError([], [], "MISSING_EVIDENCE") from exc
    if out.returncode != 0:
        raise evidence_mod.EvidenceError(
            "无法计算 files[] 覆盖（git diff %s..%s 失败）：%s"
            % (base, head, (out.stderr or "").strip()[:200]), "MISSING_EVIDENCE")
    names = [evidence_mod.norm_path(line) for line in out.stdout.splitlines() if line.strip()]
    return sorted(set(names))


def check_coverage(files, base: str, head: str = "HEAD", repo: str | None = None) -> dict:
    """缺失即抛 CoverageError；通过返回 {base, head, changed, covered}。"""
    changed = changed_files(base, head=head, repo=repo)
    covered = {evidence_mod.norm_path(f["path"]) for f in files}
    missing = [p for p in changed if p not in covered]
    if missing:
        raise CoverageError(missing, changed)
    return {"base": base, "head": head, "changed": changed, "covered": sorted(covered)}
