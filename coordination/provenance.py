"""产地判定：模块路径到底来自哪棵树。**唯一实现**，`gates.py` 与 `preflight.py` 共用。

为什么要单独一个模块（2026-11-16 17:35，A3 报的实缺陷）：
M06 车道的正本工具与产物按 `evidence_hash_v1 §4.1` **就在外部树**
（`E:\\flowhmr-test\\tools\\manifest.py`），永远不可能"在 worktree 下"。
原来那条判据只有「在 worktree 下」一条路，于是 M06 每笔提交都撞 `PROVENANCE_INVALID`
——**闸门对一整条车道结构性误杀**。判据错，不是提交错。

新规矩（仍然 fail-closed，但给出正式表达）：

1. 默认只认 worktree：路径必须在当前 worktree 根下。
2. 需要外部树时**必须在证据里显式声明** `external_roots`（绝对路径列表）；
   声明了才允许路径落在那些根下，且逐个记为「外部依赖」——让它可见，不是放行。
3. 外部根自身不许是相对路径、也不许落在 worktree **内**（那等于用"外部"给树内路径洗白），
   犯这条判 `GATE_FAILED`。
4. 路径既不在 worktree、也不在任何已声明外部根下 ⇒ `PROVENANCE_INVALID`（原样保留）。
"""
from __future__ import annotations

import os

REASON_PASS = "EVIDENCE_COMPLETE"


def _norm(path: str) -> str:
    return os.path.abspath(path).replace("\\", "/").lower()


def _under(path: str, root: str) -> bool:
    p, r = _norm(path), _norm(root)
    return p == r or p.startswith(r.rstrip("/") + "/")


def check(provenance: dict | None, worktree: str, external_roots=None) -> dict:
    """判定一份 `module_provenance`。返回 {ok, reason_code, detail, inside, external, bad_roots}。

    不抛异常：调用方（闸门/前置）自己决定怎么用这个结论。
    """
    worktree = os.path.abspath(worktree or os.getcwd())
    provenance = provenance or {}
    if not isinstance(provenance, dict) or not provenance:
        return {"ok": False, "reason_code": "PROVENANCE_INVALID",
                "detail": "未声明 module_provenance（无法证明代码来自哪棵树）",
                "inside": [], "external": [], "bad_roots": []}

    roots = []
    bad_roots = []
    for root in external_roots or []:
        if not isinstance(root, str) or not root.strip():
            bad_roots.append(repr(root))
            continue
        root = os.path.abspath(root.strip())
        if not os.path.isabs(root):
            bad_roots.append("非绝对路径：%s" % root)
        elif _under(root, worktree):
            bad_roots.append("外部根落在 worktree 内（不许用『外部』给树内路径洗白）：%s" % root)
        else:
            roots.append(root)
    if bad_roots:
        return {"ok": False, "reason_code": "GATE_FAILED",
                "detail": "external_roots 非法：%s" % "; ".join(bad_roots),
                "inside": [], "external": [], "bad_roots": bad_roots}

    inside, external, outside = [], [], []
    for key, value in sorted(provenance.items()):
        if key in ("sha256", "external_roots") or not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        if _under(value, worktree):
            inside.append("%s=%s" % (key, value))
            continue
        home = next((root for root in roots if _under(value, root)), None)
        if home:
            external.append("%s=%s（外部树种：%s）" % (key, value, home))
        else:
            outside.append("%s=%s" % (key, value))

    if outside:
        hint = "" if roots else "；也没声明 external_roots（外部树要显式声明才认）"
        return {"ok": False, "reason_code": "PROVENANCE_INVALID",
                "detail": "模块既不在 worktree（%s）也不在已声明外部根下：%s%s"
                          % (worktree, "; ".join(outside), hint),
                "inside": inside, "external": external, "bad_roots": []}

    detail = "%d 项在 %s" % (len(inside), worktree)
    if external:
        detail += "；%d 项在已声明外部树种（%s）" % (len(external), ", ".join(roots))
    return {"ok": True, "reason_code": REASON_PASS, "detail": detail,
            "inside": inside, "external": external, "bad_roots": []}
