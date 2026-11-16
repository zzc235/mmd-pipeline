r"""`stage.ensure_addons()` / `stage_import()` 的闸门实测（要开 Blender，需要锁）：

    # 应当被拒：把扩展仓库指到空目录 ⇒ mmd_tools 不可见 ⇒ 导入必须报 BLOCK，不许产出空场景
    $env:BLENDER_USER_EXTENSIONS = "$env:TEMP\empty_repo"
    blender -b -P tests_bpy/stage_addon_gate.py -- --pmx <pmx> --expect blocked

    # 应当通过：正常环境 + **只含差分段的预设**（没有 import 段）也必须能导入
    blender -b -P tests_bpy/stage_addon_gate.py -- --pmx <pmx> --expect ok

两条都是 2026-11-16 由 1号 实测撞出来的缺陷，这里把「应当被拒」那一半钉死在仓库里：

1. `addon_utils.enable("mmd_tools", …)` 返回成功但 `bpy.ops.mmd_tools.import_model`
   没注册 ⇒ 旧代码 `ensure_addons()` 报 True、`stage_import()` 静默产出一份
   **0 刚体**的场景（安静失败，最难查）。
2. `presets/*.json` 是差分文件，没有 `import` 段 ⇒ 直接 `preset["import"]` 会
   `KeyError`，而那一行在 `try` 之外 ⇒ 导入阶段直接抛栈。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bpy                                  # noqa: E402

from mmdpipe import stage                   # noqa: E402

RIGID_TYPES = ("RIGID_BODY",)


def _args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    want = "ok"
    pmx = ""
    i = 0
    while i < len(argv):
        if argv[i] == "--pmx":
            pmx = argv[i + 1]
            i += 2
        elif argv[i] == "--expect":
            want = argv[i + 1]
            i += 2
        else:
            i += 1
    return pmx, want


def _counts():
    rigids = [o for o in bpy.data.objects if getattr(o, "mmd_type", None) in RIGID_TYPES]
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    return len(rigids), len(arms), len(bpy.data.objects)


def main() -> int:
    pmx, want = _args()
    if not pmx or not os.path.exists(pmx):
        print("GATE_USAGE --pmx <pmx> --expect ok|blocked", flush=True)
        return 2

    status = stage.ensure_addons()
    print("ENSURE=%r" % (status,), flush=True)

    stage.reset_scene()
    # 故意只给差分段：磁盘上的 presets/*.json 就是这个形状（没有 import 段）
    preset = {"look": {"cool": 1.0}}
    print("PRESET_KEYS=%r" % (sorted(preset),), flush=True)
    try:
        res, root, arm, mesh = stage.stage_import(preset, pmx)
    except KeyError as exc:
        print("KEYERROR=%r" % (exc,), flush=True)
        print("GATE_RESULT FAIL 预设缺段直接抛 KeyError", flush=True)
        return 1

    rigids, arms, objects = _counts()
    print("BLOCKED=%r RIGIDS=%d ARMS=%d OBJECTS=%d" % (bool(res.blocked), rigids, arms, objects),
          flush=True)
    for item in getattr(res, "issues", []) or []:
        print("ISSUE=%r" % (item,), flush=True)

    if want == "blocked":
        # 关键断言：不许"安静成功"。旧代码这里会 ensure=True、rigids=0 且 blocked=False。
        ok = (status.get("mmd_tools") is False and bool(res.blocked)
              and rigids == 0 and arms == 0)
        print("GATE_RESULT %s 期望被拒：ensure_mmd_tools=%r blocked=%r rigids=%d arms=%d"
              % ("OK" if ok else "FAIL", status.get("mmd_tools"), bool(res.blocked), rigids, arms),
              flush=True)
        return 0 if ok else 1

    ok = status.get("mmd_tools") is True and (not res.blocked) and rigids > 0 and arm is not None
    print("GATE_RESULT %s 期望通过：ensure_mmd_tools=%r blocked=%r rigids=%d arm=%r"
          % ("OK" if ok else "FAIL", status.get("mmd_tools"), bool(res.blocked), rigids,
             getattr(arm, "name", None)), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
