"""只读回读 324 批次五份臂件：刚体数、mask_wired、is_baked、fps、窗口、动作。

目的：把「臂件仍是 324 件」从结构性推断抬成实测读数。
一个 Blender 进程里循环 open_mainfile（只读，不 save）。
`coordination.lock.assert_owner` 是 `import bpy` 之前的第一句（D-188）。
"""
import sys
import os
import json

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

from coordination import lock as lock_mod   # noqa: E402

OWNER = "模块负责3|A3"
lock_mod.assert_owner(OWNER)                # D-188 入口闸：不是锁主就不许起 Blender

import bpy                                  # noqa: E402

BATCH = os.path.join(ROOT, "out", "subai", "M05", "arms", "20261116_324")
FILES = ["C@W1.blend", "C@W1-rerun.blend", "C@W2.blend", "D.blend", "D-_.blend"]


def plain(v, depth=0):
    """IDPropertyGroup/Array -> 纯 Python（只读，不改件）。字符串原样返回，不拆成字符表。"""
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if depth > 4:
        return str(v)
    try:
        keys = list(v.keys())
    except AttributeError:
        try:
            return [plain(x, depth + 1) for x in v]
        except TypeError:
            return v if isinstance(v, (int, float, str, bool)) or v is None else str(v)
    return {k: plain(v[k], depth + 1) for k in keys}


def count_fcurves(a):
    """Blender 5.2 的 `Action` 不再保证有 `.fcurves`（分层/槽位动作）。

    返回 `(数, 走的是哪条路)` —— 两条路都不通就写 `(None, 原因)`，不拿 0 冒充。
    """
    try:
        return len(a.fcurves), "action.fcurves"
    except AttributeError as exc:
        first = str(exc)
    n = 0
    hit = "layers.strips.channelbags"
    for layer in getattr(a, "layers", []):
        for strip in layer.strips:
            bags = getattr(strip, "channelbags", None)
            if bags is None:
                continue
            for cb in bags:
                n += len(cb.fcurves)
    if n == 0:
        try:
            slot = a.slots[0]
            n = len(a.layers[0].strips[0].channelbag(slot).fcurves)
            hit = "channelbag(slots[0])"
        except (AttributeError, IndexError) as exc:
            return None, "无法计数：%s / %s" % (first, exc)
    return n, hit


def read_one(path):
    bpy.ops.wm.open_mainfile(filepath=path)
    sc = bpy.context.scene
    rbw = sc.rigidbody_world
    pc = rbw.point_cache if rbw is not None else None
    u324 = sum(1 for o in sc.objects if getattr(o, "rigid_body", None) is not None)
    def _jsonish(v):
        if isinstance(v, str) and v.strip()[:1] in ("{", "["):
            try:
                return json.loads(v)
            except ValueError:
                return v
        return v

    props = {}
    for key in sc.keys():
        if key == "_RNA_UI":
            continue
        try:
            val = _jsonish(plain(sc[key]))
        except (KeyError, TypeError) as exc:
            val = "<unreadable: %s>" % exc
        if isinstance(val, str) and len(val) > 2000:
            val = val[:2000] + "...<truncated>"
        props[key] = val
    mask = props.get("mask_wired_record") or props.get("mask_wired")
    acts = []
    for a in bpy.data.actions:
        n, how = count_fcurves(a)
        acts.append({"name": a.name, "users": a.users, "fcurves": n, "fcurves_via": how,
                     "frame_range": [round(x, 3) for x in a.frame_range]})
    active = None
    for o in sc.objects:
        if getattr(o, "animation_data", None) and o.animation_data.action:
            active = {"object": o.name, "action": o.animation_data.action.name,
                      "nla_tracks": len(o.animation_data.nla_tracks)}
            break
    rec = {
        "file": os.path.basename(path),
        "bytes": os.path.getsize(path),
        "rigids_u324_rigid_body_attr": u324,
        "bodies_in_mask_record": (mask or {}).get("bodies") if isinstance(mask, dict) else None,
        "mask_wired": mask,
        "scene_props": props,
        "is_baked": bool(pc.is_baked) if pc is not None else None,
        "is_outdated": bool(pc.is_outdated) if pc is not None else None,
        "point_cache_range": [int(pc.frame_start), int(pc.frame_end)] if pc is not None else None,
        "fps": int(sc.render.fps),
        "frame_start": int(sc.frame_start),
        "frame_end": int(sc.frame_end),
        "actions": acts,
        "active_action": active,
    }
    return rec


def main():
    out = {"schema": "m05_arms_readback/1", "batch": "20261116_324",
           "owner": OWNER, "read_only": True, "arms": []}
    for name in FILES:
        p = os.path.join(BATCH, name)
        if not os.path.exists(p):
            out["arms"].append({"file": name, "error": "missing"})
            continue
        rec = read_one(p)
        out["arms"].append(rec)
        print("  %-16s u324=%-4d fps=%-3d end=%-4s baked=%-5s actions=%d mask=%s"
              % (name, rec["rigids_u324_rigid_body_attr"], rec["fps"], rec["frame_end"],
                 rec["is_baked"], len(rec["actions"]),
                 (rec["mask_wired"] or {}).get("verdict")))
    dst = os.path.join(BATCH, "readback_arms.json")
    # 这份读数是**报告引用的物证**，而它在 `out/` 里、git 看不见 —— 被重跑覆盖掉就只剩「记忆」。
    # 所以默认拒绝覆盖：目标已存在就 exit 2，要重测必须显式 --force（`D-225`：不可逆的用拒绝）。
    if os.path.exists(dst) and "--force" not in sys.argv:
        # 在 `blender -b` 里 `SystemExit` **不改变退出码**（实测 exit 0），要非零必须抛异常
        # 交给 `--python-exit-code`。所以这里用 RuntimeError，不用 `return 2`。
        raise RuntimeError("REFUSE 已有读数：%s（确需重测加 --force）" % dst)
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2, sort_keys=True)
    print("WROTE %s" % dst)
    sys.stdout.flush()


main()
