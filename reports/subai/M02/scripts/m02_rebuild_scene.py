"""M02 · 「今天的代码能不能重建交付场景」：从 PMX 产一次最小场景。

    blender -b -P m02_rebuild_scene.py -- <preset.json> <model.pmx> <out_dir> [--build]

做三件事，全部走仓库里现成的入口（AGENTS.md 第一条）：
1. `stage.ensure_addons()` + `stage.reset_scene()` + `stage.stage_import(preset, pmx)` —— 与产线同一条导入路径；
2. 可选 `stage.stage_build(preset, root, arm)` —— 建物理（刚体世界 + 阻尼）；
3. 落盘到 `<out_dir>/rebuild_import.blend` / `rebuild_built.blend`，并把刚体清单、`$name_j` 命中数、
   `下擺_11_*` 是否有刚体写进 `<out_dir>/rebuild_report.json`。

回答 D0 的三个数：刚体总数 / 有没有 `$name_j` / 之后用 `m02_cache_gate.py` 得退出码。
"""
import hashlib
import json
import os
import sys

import bpy

A1 = r"E:\code\mmdpipe-ai\A1"
sys.path.insert(0, A1)
from mmdpipe import stage  # noqa: E402


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    do_build = "--build" in argv
    argv = [a for a in argv if not a.startswith("--")]
    if len(argv) < 3:
        raise SystemExit("usage: m02_rebuild_scene.py -- preset.json model.pmx out_dir [--build]")
    preset_path, pmx_path, out_dir = argv[0], argv[1], argv[2]
    os.makedirs(out_dir, exist_ok=True)

    with open(preset_path, encoding="utf-8") as fh:
        preset = json.load(fh)

    report = {"stage": "rebuild", "preset": preset_path, "pmx": pmx_path,
              "pmx_sha256": sha256_file(pmx_path), "build_physics": do_build,
              "addons": stage.ensure_addons(), "objects_reset": stage.reset_scene()}

    res, root, arm, mesh = stage.stage_import(preset, pmx_path)
    report["import"] = {"ok": root is not None and arm is not None,
                        "root": getattr(root, "name", None),
                        "armature": getattr(arm, "name", None),
                        "issues": [i for i in res.issues] if hasattr(res, "issues") else [],
                        "metrics": dict(getattr(res, "metrics", {}))}

    def rigid_report():
        rigids = [o for o in bpy.data.objects if getattr(o, "rigid_body", None) is not None]
        names = sorted(o.name for o in rigids)
        bones_of = {}
        for o in rigids:
            mr = getattr(o, "mmd_rigid", None)
            bones_of[o.name] = mr.bone if mr is not None else None
        xia11 = sorted(b for b in bones_of.values() if b and b.startswith("下擺_11_"))
        return {"rigid_count": len(rigids),
                "placeholder_count": sum(1 for n in names if "$name_j" in n),
                "placeholder_names": [n for n in names if "$name_j" in n][:20],
                "xia_bai_11_bones_with_body": xia11,
                "sample_names": names[:8]}

    dump1 = os.path.join(out_dir, "rebuild_import.blend")
    bpy.ops.wm.save_as_mainfile(filepath=dump1)
    report["import_blend"] = {"path": dump1, "sha256": sha256_file(dump1),
                              "rigids": rigid_report()}

    if do_build and arm is not None and root is not None:
        res2 = stage.stage_build(preset, root, arm)
        report["build"] = {"issues": [i for i in res2.issues] if hasattr(res2, "issues") else [],
                           "metrics": dict(getattr(res2, "metrics", {}))}
        dump2 = os.path.join(out_dir, "rebuild_built.blend")
        bpy.ops.wm.save_as_mainfile(filepath=dump2)
        report["built_blend"] = {"path": dump2, "sha256": sha256_file(dump2),
                                 "rigids": rigid_report()}

    with open(os.path.join(out_dir, "rebuild_report.json"), "w", encoding="utf-8",
              newline="\n") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("REBUILD rigids=%d placeholder=%d built=%s"
          % (report["import_blend"]["rigids"]["rigid_count"],
             report["import_blend"]["rigids"]["placeholder_count"], do_build))
    sys.stdout.flush()
    os._exit(0)


main()
