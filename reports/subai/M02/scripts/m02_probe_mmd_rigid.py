# -*- coding: utf-8 -*-
"""只读探针：交付件里那 12 个「PMX 没有的刚体」的 `mmd_rigid` 到底有什么字段。

为什么：补丁里 12 条 `mmd_rigid` 全是 `null`，而交付件的通道作用域是 323（=312+11 个占位体），
说明它们在旧件里**有** mmd_rigid 数据、只是我读错了属性名（「读不到 ≠ 不存在」）。
本探针把 RNA 属性逐个 getattr 一遍，打印能读到的与抛异常的，供 `mmd_rigid_of()` 修正。

退出码：0 成功；3 失败。
"""
import io
import json
import os
import sys
import traceback

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

import bpy                                            # noqa: E402
import addon_utils                                    # noqa: E402

WANT = ["$name_j", "$name_j.001", "地面_物理"]


def enable_mmd_tools():
    for mod in addon_utils.modules():
        if "mmd_tools" in getattr(mod, "__name__", ""):
            addon_utils.enable(mod.__name__, default_set=True, handle_error=None)
            return mod.__name__
    return None


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = argv[0] if argv else "mmd_rigid_probe.json"
    rec = {"blend": os.path.abspath(bpy.data.filepath), "addon": enable_mmd_tools(), "rows": []}
    by_name = {}
    for o in bpy.data.objects:
        by_name[o.name] = o
        if len(o.name) > 4 and o.name[:3].isdigit() and o.name[3] == "_":
            by_name.setdefault(o.name[4:], o)
    for name in WANT:
        obj = by_name.get(name)
        row = {"name": name}
        if obj is None:
            row["missing"] = True
            rec["rows"].append(row)
            continue
        row["object"] = obj.name
        try:
            row["mmd_type"] = str(obj.mmd_type)
        except Exception as exc:                       # noqa: BLE001
            row["mmd_type"] = "ERR:%s" % exc
        rig = getattr(obj, "mmd_rigid", None)
        row["mmd_rigid_is_none"] = rig is None
        if rig is not None:
            attrs = {}
            try:
                names = [p.identifier for p in rig.bl_rna.properties]
            except Exception as exc:                   # noqa: BLE001
                names = []
                row["bl_rna_error"] = str(exc)
            row["rna_properties"] = names
            for ident in names:
                if ident == "rna_type":
                    continue
                try:
                    value = getattr(rig, ident)
                    if hasattr(value, "__len__") and not isinstance(value, str):
                        try:
                            value = [v for v in value]
                        except Exception:              # noqa: BLE001
                            value = str(value)
                    if not isinstance(value, (int, float, str, bool, list, type(None))):
                        value = str(value)
                    attrs[ident] = value
                except Exception as exc:               # noqa: BLE001
                    attrs[ident] = "ERR:%s: %s" % (type(exc).__name__, exc)
            row["attrs"] = attrs
        rec["rows"].append(row)
    # 作用域计数（与 stage.collision_scope 同一判据）
    n_all = n_rb = n_both = n_scope = 0
    for o in bpy.data.objects:
        if getattr(o, "rigid_body", None) is not None:
            n_rb += 1
            if getattr(o, "mmd_rigid", None) is not None:
                n_both += 1
                if getattr(o, "mmd_type", None) == "RIGID_BODY":
                    n_scope += 1
        n_all += 1
    rec["counts"] = {"objects": n_all, "with_rigid_body": n_rb,
                     "with_both": n_both, "scope_u323": n_scope}
    d = os.path.dirname(os.path.abspath(out))
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with io.open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    print("MMD_RIGID_PROBE %s counts=%r" % (out, rec["counts"]))
    for row in rec["rows"]:
        print("  %-14s mmd_rigid_none=%s attrs=%s"
              % (row["name"], row.get("mmd_rigid_is_none"),
                 json.dumps(row.get("attrs"), ensure_ascii=False)[:300]))
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except BaseException:                              # noqa: BLE001
        traceback.print_exc()
        code = 3
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
