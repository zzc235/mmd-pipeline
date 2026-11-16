"""只读冒烟：`pb.warm_scene()` 是否真的把 `matrix_world` 读到「热身之后」那一侧。

不是新判据，只是把「新加的记录函数在真 Blender 里跑得通、且读数落在正确一侧」量出来。
    blender -b <file> --python smoke_warm_scene.py -- <out.json>
"""

import json
import os
import sys

import bpy

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_TREE = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
for _p in (_TREE, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import m02_patch_bpy as pb  # noqa: E402


def matrices(names):
    out = {}
    for obj in bpy.data.objects:
        if obj.name in names:
            out[obj.name] = [round(float(v), 9) for row in obj.matrix_world for v in row]
    return out


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = argv[0] if argv else "smoke_warm.json"
    import addon_utils
    for name in ("bl_ext.user_default.mmd_tools", "mmd_tools"):
        try:
            addon_utils.enable(name, default_set=False, persistent=False)
        except Exception:  # noqa: BLE001
            pass
    rec = {"blend": os.path.abspath(bpy.data.filepath), "steps": {}}
    names = [o.name for o in bpy.data.objects if getattr(o, "rigid_body", None) is not None][:3]

    # ① 开件后首读（冷）
    cold = matrices(names)
    rec["steps"]["cold_first_read"] = {"first_eval_after_open": True, "names": names,
                                       "matrices": cold}
    # ② warm_scene()：返回记录 + 读数应落在热身侧
    warm_rec = pb.warm_scene()
    warm = matrices(names)
    rec["steps"]["after_warm_scene"] = {"record": warm_rec, "matrices": warm}
    # ③ 再跑一次 warm_scene()：第二次应与第一次逐位相同（可复现）
    pb.warm_scene()
    warm2 = matrices(names)
    rec["steps"]["after_warm_scene_again"] = {"matrices": warm2}

    rec["compare"] = {
        "cold_vs_warm_identical": cold == warm,
        "warm_vs_warm2_identical": warm == warm2,
        "max_delta_cold_warm": max(
            [abs(a - b) for n in names for a, b in zip(cold[n], warm[n])] or [0.0]),
    }
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    c = rec["compare"]
    print("SMOKEWARM record=%r cold_eq_warm=%r warm_eq_warm2=%r max_delta=%r"
          % (warm_rec, c["cold_vs_warm_identical"], c["warm_vs_warm2_identical"],
             round(c["max_delta_cold_warm"], 6)))
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:                       # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("SMOKEWARM ERROR %s: %s" % (type(exc).__name__, exc))
        sys.stdout.flush()
        os._exit(9)
