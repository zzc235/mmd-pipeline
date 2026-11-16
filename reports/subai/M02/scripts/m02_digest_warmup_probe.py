"""`matrix_world` 是否依赖「开件后有没有先走一遍」—— 直接打在 `content_digest_v1` 的原料上。

为什么必须量：`m02_m08_readback.py` 用 `m02_patch_bpy.digest_body()` 取每条刚体的
`matrix_world`，那是**摘要的原料**。如果开件后立刻读与「先顺序步进再读」不一致，
那么「同一个件 ⇒ 同一个摘要」这个前提就要加一条前序（`总控` `D-223` ②：开件后第一次求值 ≠ 顺序重算）。

    blender -b <file> --python m02_digest_warmup_probe.py -- <out.json> [warm_frame]

读法：`stable=true` ⇒ 摘要原料与求值顺序无关（当前用法没问题）；
     `stable=false` ⇒ 摘要必须带 `first_eval_after_open` 标注，回读要先热身。
"""

import hashlib
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

from mmdpipe import stage  # noqa: E402
import m02_patch_bpy as pb  # noqa: E402

TOL = 1e-6


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def matrices():
    out = {}
    for obj in stage.rigid_bodies():
        matrix = getattr(obj, "matrix_world", None)
        if matrix is None:
            continue
        out[obj.name] = [round(float(v), 9) for row in matrix for v in row]
    return out


def body_digests():
    """走与回读同一条路径（`digest_body`），载荷是摘要真正吃到的东西。"""
    out = {}
    for obj in sorted(stage.rigid_bodies(), key=lambda o: o.name):
        rec = pb.digest_body(obj)
        payload = json.dumps(rec, sort_keys=True, ensure_ascii=False, default=str)
        out[obj.name] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return out


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out_path = argv[0] if argv else "digest_warmup.json"
    warm_frame = int(argv[1]) if len(argv) > 1 else 417

    import addon_utils
    for name in ("bl_ext.user_default.mmd_tools", "mmd_tools"):
        try:
            addon_utils.enable(name, default_set=False, persistent=False)
        except Exception:  # noqa: BLE001
            pass
    scene = bpy.context.scene
    path = bpy.data.filepath
    bodies = stage.rigid_bodies()
    rec = {
        "stage": "digest-warmup-probe-v1",
        "blend": {"path": os.path.abspath(path), "sha256": sha256_file(path)},
        "bodies": len(bodies),
        "tol": TOL,
        "scene_frame": int(scene.frame_current),
        # 这一次读发生在任何 `frame_set` 之前 ⇒ 就是「开件后第一次读」
        "first_eval_after_open": True,
    }
    if not bodies:
        rec["verdict"] = "REFUSED"
        return finish(rec, out_path, 4)

    cold_mat = matrices()
    cold_dig = body_digests()
    rec["cold"] = {
        "matrices_sha": hashlib.sha256(
            json.dumps(cold_mat, sort_keys=True).encode("utf-8")).hexdigest(),
        "bodies_sha": hashlib.sha256(
            json.dumps(cold_dig, sort_keys=True).encode("utf-8")).hexdigest(),
        "first_eval_after_open": True,
    }

    # 热身：从 frame_start 顺序步进到 warm_frame
    start = int(scene.frame_start)
    for frame in range(start, warm_frame + 1):
        scene.frame_set(frame)
    warm_mat = matrices()
    warm_dig = body_digests()
    rec["warm"] = {
        "frame": warm_frame,
        "matrices_sha": hashlib.sha256(
            json.dumps(warm_mat, sort_keys=True).encode("utf-8")).hexdigest(),
        "bodies_sha": hashlib.sha256(
            json.dumps(warm_dig, sort_keys=True).encode("utf-8")).hexdigest(),
        "first_eval_after_open": False,
    }

    names = sorted(set(cold_mat) | set(warm_mat))
    diffs = []
    for name in names:
        a, b = cold_mat.get(name), warm_mat.get(name)
        if a is None or b is None:
            diffs.append({"name": name, "error": "缺一侧"})
            continue
        worst = max(abs(x - y) for x, y in zip(a, b))
        if worst > TOL:
            diffs.append({"name": name, "max_delta": round(worst, 9)})
    body_diffs = [n for n in names if cold_dig.get(n) != warm_dig.get(n)]
    rec["compare"] = {
        "bodies": len(names),
        "matrix_over_tol": len(diffs),
        "matrix_max_delta": max([d.get("max_delta", 0.0) for d in diffs] or [0.0]),
        "body_digest_diff": len(body_diffs),
        "sample": diffs[:5],
    }
    rec["verdict"] = "DIGEST_INPUT_STABLE" if not diffs and not body_diffs \
        else "DIGEST_INPUT_DEPENDS_ON_EVAL"
    return finish(rec, out_path, 0 if rec["verdict"] == "DIGEST_INPUT_STABLE" else 5)


def finish(rec, out_path, code):
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    c = rec.get("compare") or {}
    print("DIGESTWARM verdict=%s rc=%d matrix_over_tol=%r max_delta=%r body_digest_diff=%r"
          % (rec.get("verdict"), code, c.get("matrix_over_tol"),
             c.get("matrix_max_delta"), c.get("body_digest_diff")))
    sys.stdout.flush()
    os._exit(code)


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:                       # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("DIGESTWARM ERROR %s: %s" % (type(exc).__name__, exc))
        sys.stdout.flush()
        os._exit(9)
