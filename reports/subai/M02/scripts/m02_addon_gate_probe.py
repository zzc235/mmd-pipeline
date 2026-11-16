"""一次性判据探针：插件「假启用」到底该怎么判。

    blender -b -P m02_addon_gate_probe.py -- <out.json>

分别记录：
  - `addon_utils.enable()` 的返回值（短名 / 扩展真名）；
  - `hasattr(bpy.ops.mmd_tools, "import_model")`  ← 4号 说它在算子缺失时也是 True；
  - `bpy.ops.mmd_tools.import_model.get_rna_type()`（真注册才有）；
  - `bpy.ops.mmd_tools.import_model.poll()`。

同一份脚本跑两次：一次正常扩展仓库，一次 `BLENDER_USER_EXTENSIONS` 指空目录（算子彻底不可见）。
"""
import json
import os
import sys

import bpy

try:
    import addon_utils
except ImportError:  # pragma: no cover
    addon_utils = None


def try_call(fn):
    """返回值一律转成 JSON 安全形态：`enable()` 返回的是模块对象，直接 dump 会中途抛 TypeError
    并把文件截断（第一版就踩了，落了个 79 字节的半个 JSON）。"""
    try:
        return {"ok": True, "value": json_safe(fn())}
    except Exception as exc:
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}


def json_safe(value):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    return "repr:%s" % (value,)


def main():
    out_path = sys.argv[sys.argv.index("--") + 1]
    out = {"extensions_repo": os.environ.get("BLENDER_USER_EXTENSIONS"),
           "enabled_pref": None, "enable": {}, "operator": {}}

    if addon_utils is not None:
        for name in ("mmd_tools", "bl_ext.user_default.mmd_tools"):
            out["enable"][name] = try_call(
                lambda n=name: addon_utils.enable(n, default_set=False, persistent=False))
        out["enabled_pref"] = sorted(".".join(m.__name__.split(".")[-1:])
                                     for m in addon_utils.modules() if addon_utils.check(
                                         m.__name__)[1]) \
            if hasattr(addon_utils, "check") else None

    ops = try_call(lambda: bpy.ops.mmd_tools)
    out["operator"]["module_resolved"] = ops.get("ok", False)
    if isinstance(ops.get("value"), object) and ops["ok"]:
        out["operator"]["hasattr_import_model"] = try_call(
            lambda: hasattr(bpy.ops.mmd_tools, "import_model"))
        out["operator"]["get_rna_type"] = try_call(
            lambda: bpy.ops.mmd_tools.import_model.get_rna_type().identifier)
        out["operator"]["poll"] = try_call(lambda: bpy.ops.mmd_tools.import_model.poll())
    else:
        out["operator"]["error"] = ops.get("error")

    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("ADDON_PROBE " + json.dumps(out, ensure_ascii=False))
    sys.stdout.flush()
    os._exit(0)


main()
