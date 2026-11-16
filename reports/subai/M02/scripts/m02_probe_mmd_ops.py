# -*- coding: utf-8 -*-
"""只读探针：mmd_tools 的刚体相关算子与它们的参数名（补丁要用现成算子造 MMD 刚体）。"""
import os
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

import bpy                                            # noqa: E402
import addon_utils                                    # noqa: E402


def main():
    for mod in addon_utils.modules():
        if "mmd_tools" in getattr(mod, "__name__", ""):
            addon_utils.enable(mod.__name__, default_set=True, handle_error=None)
            print("addon", mod.__name__)
            break
    names = [n for n in dir(bpy.ops.mmd_tools) if "rigid" in n.lower()]
    print("rigid ops:", names)
    for opname in names:
        op = getattr(bpy.ops.mmd_tools, opname)
        try:
            rna = op.get_rna_type()
        except Exception as exc:                       # noqa: BLE001
            print("  %s rna error %s" % (opname, exc))
            continue
        props = []
        for p in rna.properties:
            if p.identifier == "rna_type":
                continue
            extra = ""
            if getattr(p, "enum_items", None):
                extra = " enum=%r" % ([i.identifier for i in p.enum_items],)
            props.append("%s:%s%s" % (p.identifier, p.type, extra))
        print("  %s(%s)" % (opname, ", ".join(props)))
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
