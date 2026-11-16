"""在真 Blender 5.2 里量「写侧」的三件事（**只读，不存盘**）。

要回答的（`D-213` / `D-214` 派工里那句「是待验假设，不是事实」）：

1. `Action.fcurve_ensure_for_datablock` 到底存不存在？签名是什么？（`__doc__` 就是答案）
2. 存过盘的臂件里，动作的 `layers/strips/channelbags` 有几层、槽位与
   `arm.animation_data.action_slot` 对不对得上？
3. `apply_action.ensure_fcurve` 在一份 `action.copy()` 上会走哪条路（`how`），
   曲线最后落在哪个 channelbag 里？

为什么用 `action.copy()`：写曲线是**改场景**，而臂件是 `0o444` 物证 —— 复制一份再改，
文件前后 sha 必须同值（`D-209`）。本脚本不调任何 `save`。

    blender -b <臂件.blend> -P out/subai/M05/probe_fcurve_write_shape.py -- \
        --owner '模块负责3|A3' --json out/subai/M05/probe_fcurve_write_shape.json
"""
import argparse
import hashlib
import json
import os
import sys
import traceback

def find_repo_root(start):
    """往上走到有 `coordination/` 与 `mmdpipe/` 的那一层；走不到就把起点打出来再死。

    不写死 `dirname` 次数：同一份脚本既可能在 `out/subai/M05/`（产物树）也可能在
    `reports/subai/M05/scripts/`（仓库），深度不同，写死次数必然有一边算错 ——
    而算错的形状是 `ImportError`，看起来像「这个模块不存在」（`D-228` 规则十二条）。
    """
    cur = os.path.abspath(start)
    while True:
        if (os.path.isdir(os.path.join(cur, "coordination"))
                and os.path.isdir(os.path.join(cur, "mmdpipe"))):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            raise SystemExit("从 %s 往上走到顶也没找到 coordination/ 与 mmdpipe/"
                             % os.path.abspath(start))
        cur = parent
ROOT = find_repo_root(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from coordination import lock as lock_mod          # noqa: E402


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def bags_of(action):
    out = []
    for li, layer in enumerate(getattr(action, "layers", []) or []):
        for si, strip in enumerate(getattr(layer, "strips", []) or []):
            for bi, bag in enumerate(getattr(strip, "channelbags", None) or []):
                slot = getattr(bag, "slot", None)
                out.append({
                    "at": [li, si, bi],
                    "fcurves": len(getattr(bag, "fcurves", []) or []),
                    "slot": getattr(slot, "name_display", None) or getattr(slot, "identifier", None),
                })
    return out


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="probe_fcurve_write_shape")
    ap.add_argument("--owner", required=True)
    ap.add_argument("--json", required=True)
    ap.add_argument("--force", action="store_true",
                    help="目标 json 已存在时允许覆盖（默认拒绝：那份读数是报告引用的物证）")
    args = ap.parse_args(argv)

    # 覆盖守卫放在**最前面**：先判目标，再花 20 秒开臂件做测量。
    # 排在测量之后等于「先做完整件活再告诉你能不能落盘」，负控也测不出「没动任何东西」。
    # 语义码 10 = 拒绝覆盖（不用 3：那是 `coordination.lock` 的冲突码，guard 会透传）。
    out = args.json if os.path.isabs(args.json) else os.path.join(ROOT, args.json)
    if os.path.exists(out) and not args.force:
        print("REFUSE 已有读数：%s（确需重测加 --force）" % out)
        return 10

    import bpy
    from mmdpipe import apply_action as AA

    # `D-188`：跑 Blender 的第一句先问「锁是不是我的」，不是就直接失败、不留读数。
    owner_info = lock_mod.assert_owner(args.owner)

    blend = bpy.data.filepath
    sha_before = sha256_file(blend)
    rep = {"blend": blend, "sha_before": sha_before, "lock": owner_info,
           "errors": []}

    try:
        arm = None
        for ob in bpy.data.objects:
            if ob.type == "ARMATURE" and ob.animation_data and ob.animation_data.action:
                if arm is None or len(ob.data.bones) > len(arm.data.bones):
                    arm = ob
        if arm is None:
            rep["errors"].append("场景里没有带 action 的骨架")
            raise SystemExit(2)
        action = arm.animation_data.action

        ad = arm.animation_data
        rep["arm"] = {"name": arm.name, "bones": len(arm.data.bones),
                      "action_slot": getattr(getattr(ad, "action_slot", None),
                                             "identifier", None)}
        # ① 动作形状：`.fcurves` 在存盘再读回来的动作上到底给不给
        shape = {"name": action.name, "fcurves_readable": None, "fcurves_error": None,
                 "layers": len(getattr(action, "layers", []) or []),
                 "bags": bags_of(action),
                 "instance_attrs": sorted(a for a in dir(action) if "fcurve" in a.lower()),
                 "class_attrs": sorted(a for a in dir(bpy.types.Action)
                                       if "fcurve" in a.lower())}
        try:
            shape["fcurves_readable"] = len(action.fcurves)
        except Exception as exc:                       # noqa: BLE001 —— 就是要记录它抛什么
            shape["fcurves_error"] = "%s: %s" % (type(exc).__name__, exc)
        rep["action"] = shape

        # ② 上游接口：存在性、签名（`__doc__`）、能不能真调
        fn = getattr(action, "fcurve_ensure_for_datablock", None)
        up = {"exists_on_class": hasattr(bpy.types.Action, "fcurve_ensure_for_datablock"),
              "exists_on_instance": fn is not None,
              "doc": (getattr(fn, "__doc__", None) or "")[:400] if fn else None}
        rep["upstream"] = up

        # ③ 在一份 copy 上试写：不碰文件
        copy = action.copy()
        path = 'pose.bones["%s"].location' % arm.pose.bones[0].name
        written = {"path": path, "bags_before": bags_of(copy)}
        try:
            fc, how = AA.ensure_fcurve(copy, arm, path, index=1, group=arm.pose.bones[0].name)
            written.update({"how": how, "array_index": getattr(fc, "array_index", None),
                            "data_path": getattr(fc, "data_path", None),
                            "bags_after": bags_of(copy)})
        except Exception as exc:                       # noqa: BLE001
            written.update({"how": None,
                            "error": "%s: %s" % (type(exc).__name__, exc),
                            "trace": traceback.format_exc()[-1200:]})
        rep["ensure_fcurve_on_copy"] = written
    except SystemExit:
        pass
    except Exception:                                  # noqa: BLE001
        rep["errors"].append(traceback.format_exc()[-2000:])

    sha_after = sha256_file(blend)
    rep["sha_after"] = sha_after
    rep["blend_untouched"] = sha_after == sha_before

    out = args.json if os.path.isabs(args.json) else os.path.join(ROOT, args.json)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2, sort_keys=True)
    print("PROBE %s" % out)
    print(json.dumps({k: rep[k] for k in ("blend_untouched", "upstream") if k in rep},
                     ensure_ascii=False))
    return 0 if not rep["errors"] and rep["blend_untouched"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
