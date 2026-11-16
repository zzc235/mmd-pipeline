"""导出「刚体 → 骨 + 组号 + 掩码」全表，供 M04 的基线与 MMD 掩码语义对账。

只读：`open_mainfile` 后不写任何东西、不存盘。
为什么需要它：我的胶囊基线是 5076 个「刚体对 → 重叠量」。要回答
「这些重叠有多少是因为碰撞掩码没接线才存在的」，必须把每对映射回 PMX 的
组号与掩码——而对象名（`<序号>_<刚体名>`）、`obj.parent` 都不可靠，
只能读 `mmd_rigid.bone` / `mmd_rigid.collision_group_number` / `mmd_rigid.collision_group_mask`。
"""
import argparse
import json
import sys

import addon_utils
import bpy


def _args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--blend", required=True)
    p.add_argument("--out", required=True)
    return p.parse_args(argv)


def bits_of(value):
    """`collision_group_mask` 是 16 个布尔（位集合），不是 int。"""
    if isinstance(value, int):
        return value
    out = 0
    for i, flag in enumerate(value):
        if flag:
            out |= 1 << i
    return out


def main():
    a = _args()
    addon_utils.enable("bl_ext.user_default.mmd_tools", default_set=False, handle_error=None)
    bpy.ops.wm.open_mainfile(filepath=a.blend)
    rows, fails = [], []
    for o in bpy.data.objects:
        # 扩展启用后**每个对象**都有 `mmd_rigid` 属性（PropertyGroup 注册在 Object 上），
        # 所以 `hasattr` 不能当「它是不是刚体」用——实测这样会数出 4853 个。
        # 真刚体才有 `rigid_body`。
        if getattr(o, "rigid_body", None) is None:
            continue
        try:
            rows.append({
                "object": o.name,
                "bone": getattr(o.mmd_rigid, "bone", "") or "",
                "group": int(getattr(o.mmd_rigid, "collision_group_number", 0)) + 1,
                "mask": bits_of(getattr(o.mmd_rigid, "collision_group_mask", [])),
                "kinematic": bool(getattr(o.rigid_body, "kinematic", False)),
            })
        except Exception as exc:  # noqa: BLE001
            # 读不到要单独报，绝不折成 0——「读不到 ≠ 不存在」
            fails.append({"object": o.name, "error": "%s: %s" % (type(exc).__name__, exc)})
    doc = {"blend": a.blend, "rigid_objects": len(rows), "read_failures": fails, "rows": rows}
    with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print("[maskdump] rigid=%d failures=%d -> %s" % (len(rows), len(fails), a.out), flush=True)
    sys.exit(0 if not fails else 2)


main()
