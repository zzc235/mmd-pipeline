# -*- coding: utf-8 -*-
"""只读探针：5.2 里「选中某个 pose bone」的正确属性名（`Bone.select` 已不存在）。"""
import os
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

import bpy  # noqa: E402


def main():
    bpy.ops.object.armature_add()
    arm = bpy.context.object
    bone = arm.data.bones[0]
    pb = arm.pose.bones[0]
    print("bone attrs with select:", [a for a in dir(bone) if "select" in a.lower()])
    print("posebone attrs with select:", [a for a in dir(pb) if "select" in a.lower()])
    print("data attrs with active:", [a for a in dir(arm.data) if "active" in a.lower()])
    print("bone rna props:", [p.identifier for p in bone.bl_rna.properties][:40])
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
