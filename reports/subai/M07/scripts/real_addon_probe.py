# -*- coding: utf-8 -*-
"""真 Blender 里复测：扩展「装上了 / 没装上」到底改不改变 `stage.ensure_addons()` 的判词。

由 `run_real_addon_recheck.py` 调用，参数写在 `--` 之后：

    blender -b --no-prefs --python-exit-code 3 --python real_addon_probe.py -- \
        --worktree E:\\code\\mmdpipe-ai\\A4 --mode present --out <json>

规矩（和 13:20 那次事故对齐）：不写 `%APPDATA%`、不改 `userpref.blend`、不打开交付场景。
扩展仓库由调用方的 `BLENDER_USER_EXTENSIONS` 指定，本脚本只读它；worktree 代码也只读。

must-pass 写在 `expectations` 里，任一为 False ⇒ `sys.exit(3)`（Blender 自己的退出码不可信，
所以脚本主动给码，外层再配 `--python-exit-code 3` 兜底）。
"""
from __future__ import annotations

import json
import sys
import traceback

import addon_utils
import bpy

MISSING_MODULES = ("bl_ext.user_default.mmd_tools_missing", "mmd_tools_missing_plain")


def _args() -> dict:
    argv = sys.argv
    if "--" not in argv:
        raise SystemExit("参数必须写在 `--` 之后")
    items = argv[argv.index("--") + 1:]
    if len(items) % 2:
        raise SystemExit("参数必须成对：%r" % (items,))
    out = {}
    for n in range(0, len(items), 2):
        key = items[n]
        if not key.startswith("--"):
            raise SystemExit("参数格式不对：%r" % (key,))
        out[key[2:]] = items[n + 1]
    return out


def _registration(namespace, op: str) -> dict:
    """判注册不用 `hasattr`：没注册时它也是 True，只有 `get_rna_type()` 会抛 KeyError。"""
    row = {}
    try:
        row["hasattr"] = hasattr(namespace, op) if namespace is not None else None
    except Exception as exc:                      # 命名空间本身坏了也要记下来
        row["hasattr"] = "raised:%s" % type(exc).__name__
    if namespace is None:
        row["get_rna_type"] = "no_namespace"
        return row
    try:
        getattr(namespace, op).get_rna_type()
        row["get_rna_type"] = "ok"
    except Exception as exc:
        row["get_rna_type"] = "raised:%s" % type(exc).__name__
    return row


def probe(worktree: str) -> dict:
    res = {"blender": bpy.app.version_string, "worktree": worktree}
    res["extension_root"] = bpy.utils.user_resource("EXTENSIONS")
    res["script_root"] = bpy.utils.user_resource("SCRIPTS")

    # 1) 「假成功」的入口：对不存在的模块 enable 会不会抛
    missing = {}
    for module in MISSING_MODULES:
        try:
            returned = addon_utils.enable(module, default_set=False, persistent=False)
            missing[module] = {"raised": None, "returned_repr": repr(returned),
                               "returned_is_none": returned is None}
        except Exception as exc:
            missing[module] = {"raised": type(exc).__name__, "message": str(exc)}
    res["enable_missing_module"] = missing

    # 2) 生产路径：stage.ensure_addons / addon_ready
    sys.path.insert(0, worktree)
    from mmdpipe import stage
    res["stage_module_file"] = stage.__file__
    res["stage_addon_candidates"] = {k: list(v) for k, v in stage.ADDON_CANDIDATES.items()}
    res["ensure_mmd_tools"] = {k: bool(v) for k, v in
                               stage.ensure_addons(names=("mmd_tools",)).items()}
    res["addon_ready_mmd_tools"] = bool(stage.addon_ready("mmd_tools"))
    res["registration_mmd_tools"] = _registration(getattr(bpy.ops, "mmd_tools", None),
                                                  "import_model")
    res["addon_utils_check"] = {}
    for module in ("bl_ext.user_default.mmd_tools", "mmd_tools"):
        try:
            res["addon_utils_check"][module] = [bool(x) for x in addon_utils.check(module)]
        except Exception as exc:
            res["addon_utils_check"][module] = "raised:%s" % type(exc).__name__

    # 3) 反控：名字写错必须判红（用的是真实的候选名表，不是编的）
    res["ensure_typo"] = {k: bool(v) for k, v in
                          stage.ensure_addons(names=("mmd_tools_typo",)).items()}
    res["addon_ready_typo"] = bool(stage.addon_ready("mmd_tools_typo"))
    return res


def expectations(res: dict, mode: str) -> dict:
    """每条判据单独给，不合成一个 and —— 合成后一条坏掉就看不见是哪条。"""
    reg = res.get("registration_mmd_tools") or {}
    exp = {
        "typo_ensure_is_false": res.get("ensure_typo", {}).get("mmd_tools_typo") is False,
        "typo_addon_ready_is_false": res.get("addon_ready_typo") is False,
        # 缺失模块的 enable 不抛 —— 这正是「不报错但没装上」的入口，事实本身要留住
        "missing_module_enable_does_not_raise": all(
            row.get("raised") is None for row in res.get("enable_missing_module", {}).values()),
    }
    if mode == "present":
        exp["ensure_says_true"] = res.get("ensure_mmd_tools", {}).get("mmd_tools") is True
        exp["addon_ready_true"] = res.get("addon_ready_mmd_tools") is True
        exp["operator_really_registered"] = reg.get("get_rna_type") == "ok"
    else:
        exp["ensure_says_false"] = res.get("ensure_mmd_tools", {}).get("mmd_tools") is False
        exp["addon_ready_false"] = res.get("addon_ready_mmd_tools") is False
        exp["operator_not_registered"] = reg.get("get_rna_type") != "ok"
    return exp


def main() -> int:
    opts = _args()
    worktree = opts.get("worktree") or ""
    mode = opts.get("mode") or "present"
    out_path = opts.get("out") or ""
    if not worktree or not out_path or mode not in ("present", "absent"):
        raise SystemExit("缺参数：--worktree / --out / --mode present|absent")

    payload = {"mode": mode, "ok": False}
    code = 0
    try:
        res = probe(worktree)
        exp = expectations(res, mode)
        res.update({"mode": mode, "expectations": exp,
                    "ok": all(exp.values()),
                    "failed": [k for k, v in exp.items() if not v]})
        payload = res
        code = 0 if res["ok"] else 3
    except Exception:
        payload = {"mode": mode, "ok": False, "failed": ["exception"],
                   "traceback": traceback.format_exc()}
        code = 3
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
