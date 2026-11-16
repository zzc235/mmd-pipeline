"""M02 · 等价回读：把打过补丁的 PMX 导入全新场景，回读 18 个关节的 limit_ang_x_*，
断言与 patch_save 写入的 ∓0.7 逐位一致（|Δ| < 1e-6）。

    blender -b -P m02_check_import_equiv.py -- <patched.pmx> <s2_targets.json> <out.json>

动机（总控 D-023 前的要求）：我们出货的是 PMX 补丁副本，但 S2 的动态对照是在 .blend 的
约束上做的。必须证明「导入补丁 PMX 后限位真的落到约束上」，否则字节对 ≠ 语义对。

只读 PMX，写一个新场景到内存，不保存任何 .blend。
"""
import json
import os
import re
import sys

import bpy

PREFIX = re.compile(r"^\d+_J\.")
EXPECT = 0.7
TOL = 1e-6


def parse_argv():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) < 3:
        raise SystemExit("usage: m02_check_import_equiv.py -- patched.pmx targets.json out.json")
    return argv[0], argv[1], argv[2]


def main():
    pmx_path, targets_path, out_path = parse_argv()
    with open(targets_path, encoding="utf-8") as fh:
        pmx_targets = sorted(t["joint_name"] for t in json.load(fh)["targets"])

    # 全新空场景（不读工厂设置，避免触发 10 §6 的 read_factory_settings 禁令）
    bpy.ops.wm.read_homefile(use_empty=True)
    attempts = [
        {"filepath": pmx_path, "scale": 1.0, "types": {"MESH", "ARMATURE", "PHYSICS"}},
        {"filepath": pmx_path},
    ]
    import_ok = False
    import_error = None
    used = None
    for kwargs in attempts:
        try:
            bpy.ops.mmd_tools.import_model(**kwargs)
            import_ok = True
            used = sorted(kwargs)
            break
        except Exception as exc:                  # noqa: BLE001 - 把失败原因原样带出去
            import_error = "%s: %s" % (type(exc).__name__, exc)

    rows = []
    if import_ok:
        for ob in bpy.data.objects:
            rbc = getattr(ob, "rigid_body_constraint", None)
            if rbc is None:
                continue
            name = PREFIX.sub("", ob.name)
            if name in pmx_targets:
                rows.append({
                    "object": ob.name,
                    "joint": name,
                    "limit_ang_x_lower": rbc.limit_ang_x_lower,
                    "limit_ang_x_upper": rbc.limit_ang_x_upper,
                    "use_limit_ang_x": rbc.use_limit_ang_x,
                    "delta_lower": abs(rbc.limit_ang_x_lower + EXPECT),
                    "delta_upper": abs(rbc.limit_ang_x_upper - EXPECT),
                })

    matched = [r for r in rows if r["delta_lower"] < TOL and r["delta_upper"] < TOL]
    result = {
        "task": "M02",
        "stage": "C-equivalence",
        "pmx": pmx_path,
        "import_ok": import_ok,
        "import_error": import_error,
        "pmx_targets": pmx_targets,
        "imported_joint_objects": len([o for o in bpy.data.objects
                                       if getattr(o, "rigid_body_constraint", None)]),
        "targets_found": len(rows),
        "targets_at_minus_plus_0_7": len(matched),
        "tolerance": TOL,
        "rows": rows,
        "verdict": ("EQUIVALENT" if import_ok and len(matched) == len(pmx_targets)
                    else "NOT_EQUIVALENT"),
    }
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("EQUIV ok=%s found=%d matched=%d verdict=%s err=%s"
          % (import_ok, len(rows), len(matched), result["verdict"], import_error))
    sys.stdout.flush()
    os._exit(0)


main()
