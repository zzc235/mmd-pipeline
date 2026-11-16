# -*- coding: utf-8 -*-
"""只读：把交付件里「PMX 没有的 12 个刚体」逐条读出来（名字/父骨/尺寸/质量/组/掩码/模式/位置）。

为什么：`324 − 312 = 12`，纯 Python 只能算出名字（`$name_j*` 11 个 + `地面_物理`），
说不出它们**在物理上是什么**。判断「缺了它们对 C/D 有没有影响」需要这 12 行的属性，
所以这一步必须在 Blender 里读——但仍然只读，不改场景、不存盘。

`--patch-out <path>`：同一次读取顺手产出 `m08_extra_bodies_patch_v1` 补丁（总控 18:08 §二 选 A）：
12 条属性**全部从旧件读出**、盖 `patch_sha256`、带来源件路径与 sha256 + 抽取脚本路径与 sha256。
抽样函数只有一份（`m02_patch_bpy.body_spec`），重建端用同一个函数回读验回来。

用法：
    blender -b <旧件.blend> -P m02_dump_extra_bodies.py -- <rows_out.json> [--patch-out patch.json]

退出码：0 成功；3 失败；4 有清单里的对象没找到（拒绝产出残缺补丁）。
"""

import hashlib
import io
import json
import os
import sys
import traceback

# GBK 控制台下中文/符号会让脚本崩在打印上（总控 18:18）：入口统一 UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                    # noqa: BLE001
        pass

import bpy                                            # noqa: E402
import addon_utils                                    # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m02_patch_format as pf                         # noqa: E402
import m02_patch_bpy as pb                            # noqa: E402

WANT = list(pf.WANT_NAMES)


def enable_mmd_tools():
    for mod in addon_utils.modules():
        if "mmd_tools" in getattr(mod, "__name__", ""):
            addon_utils.enable(mod.__name__, default_set=True, handle_error=None)
            return mod.__name__
    return None


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def obj_row(obj):
    rb = getattr(obj, "rigid_body", None)
    row = {"name": obj.name, "type": obj.type,
           "mmd_type": getattr(obj, "mmd_type", None),
           "parent": obj.parent.name if obj.parent else None,
           "parent_bone": obj.parent_bone or None,
           "location": [round(v, 6) for v in obj.location],
           "rigid_body": rb is not None}
    if rb is not None:
        row.update({
            "mass": round(float(rb.mass), 6),
            "friction": round(float(rb.friction), 6),
            "restitution": round(float(rb.restitution), 6),
            "kinematic": bool(rb.kinematic),
            "collision_shape": str(rb.collision_shape),
            "collision_collections": [int(b) for b in rb.collision_collections],
            "collision_margin": round(float(rb.collision_margin), 6),
            "linear_damping": round(float(rb.linear_damping), 6),
            "angular_damping": round(float(rb.angular_damping), 6),
            "use_margin": bool(rb.use_margin),
        })
    row["mmd_rigid"] = pb.mmd_rigid_of(obj)
    return row


def build_patch(by_name, source_blend, rigids_total):
    """把 12 条 spec 装成补丁并盖 sha。缺一条就抛，不产出残缺补丁。"""
    bodies, absent = [], []
    for name in WANT:
        obj = by_name.get(name)
        if obj is None:
            absent.append(name)
            continue
        bodies.append(pb.body_spec(obj))
    if absent:
        raise pf.PatchError("PATCH_SOURCE_INCOMPLETE",
                            "旧件里找不到这 %d 个对象：%r（拒绝产出残缺补丁）"
                            % (len(absent), absent))
    extractor = os.path.abspath(__file__)
    patch = {
        "patch_version": pf.PATCH_VERSION,
        "source": {
            "blend": os.path.abspath(source_blend),
            "blend_sha256": sha256_file(source_blend),
            "rigids_total": rigids_total,
            "count_found": len(bodies),
            "blender": bpy.app.version_string,
            "extractor": {"path": extractor, "sha256": sha256_file(extractor)},
            "extractor_sha256": sha256_file(extractor),
        },
        "bodies": bodies,
    }
    return pf.seal(patch)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    patch_out = None
    positional = []
    i = 0
    while i < len(argv):
        if argv[i] == "--patch-out" and i + 1 < len(argv):
            patch_out = argv[i + 1]
            i += 2
            continue
        positional.append(argv[i])
        i += 1
    rows_out = positional[0] if positional else "extra_bodies.json"
    try:
        rec = {"blend": os.path.abspath(bpy.data.filepath), "addon_enabled": enable_mmd_tools(),
               "rows": []}
        by_name = {}
        for o in bpy.data.objects:
            by_name[o.name] = o
            # 交付件里对象名带 `NNN_` 前缀（`000_$name_j`），去前缀后再索引一次
            by_name.setdefault(pb.strip_prefix(o.name), o)
        for name in WANT:
            obj = by_name.get(name)
            rec["rows"].append(obj_row(obj) if obj is not None else
                               {"name": name, "missing_in_this_blend": True})
        rec["count_found"] = sum(1 for r in rec["rows"] if "missing_in_this_blend" not in r)
        rec["rigids_total"] = len([o for o in bpy.data.objects
                                   if getattr(o, "rigid_body", None) is not None])
        rec["rigidbody_world"] = pb.rigidbody_world_snapshot()
        if patch_out:
            try:
                patch = build_patch(by_name, bpy.data.filepath, rec["rigids_total"])
            except pf.PatchError as exc:
                rec["patch"] = {"written": False, "reason_code": exc.reason_code,
                                "message": exc.message}
                with open(rows_out, "w", encoding="utf-8", newline="\n") as fh:
                    json.dump(rec, fh, ensure_ascii=False, indent=1, sort_keys=True)
                    fh.write("\n")
                print("EXTRA_BODIES PATCH_REFUSED %s" % exc)
                return 4
            with io.open(patch_out, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(patch, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
            rec["patch"] = {"written": True, "path": os.path.abspath(patch_out),
                            "patch_sha256": patch["patch_sha256"],
                            "patch_file_sha256": sha256_file(patch_out),
                            "bodies": len(patch["bodies"]),
                            "source_blend_sha256": patch["source"]["blend_sha256"]}
        with open(rows_out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(rec, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
        print("EXTRA_BODIES %s  found=%d rigids_total=%d patch=%s"
              % (rows_out, rec["count_found"], rec["rigids_total"],
                 rec.get("patch", {}).get("patch_sha256")))
        return 0
    except BaseException:                              # noqa: BLE001
        traceback.print_exc()
        print("EXTRA_BODIES ERROR")
        return 3


if __name__ == "__main__":
    sys.exit(main())
