"""M02 · 缓存一致性闸门：判定 `.blend` 的 rigidbody point cache 属于哪一态（观测侧）。

    blender -b -P m02_cache_gate.py -- <scene.blend> [...] [--out out.json] [--behavior b.json]

**判据本身不在这里**：它来自 `mmdpipe.cache_state`（纯 Python、包内、可进 CI）。本脚本只负责
用 bpy 取观测值并调它判——两处各留一份判据就一定会漂（这一版就是为这个改的）。

七态与退出码见 `mmdpipe/cache_state.py` 文档头。要点：

- **旗标不合只判 `SUSPECT_BAKED_OUTDATED`(4)**，不判缺陷：真烘焙件重开后也是
  `is_baked=true && is_outdated=true`（P13 实测 `J_baked.blend` 冷跳逐位等于重算）；
- 要判 `DEFECT_BAKED_OUTDATED`(3) 必须给行为证据（`--behavior`：冷跳 vs 顺序重算的距离）；
- 只读打开，绝不保存。

`--behavior` 文件形如 `{"<path>": {"cold_jump_frame": 109,
                                   "cold_jump_vs_recompute_m": 0.0, "tolerance_m": 1e-6}}`。
"""
import json
import os
import sys

import bpy

_CANDIDATES = (r"E:\code\mmdpipe-ai\A1",)
for _p in _CANDIDATES:
    if os.path.isdir(os.path.join(_p, "mmdpipe")) and _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from mmdpipe import cache_state
except ImportError as _exc:  # 判据拿不到就别判——不许用一份本地副本顶上
    print("GATE FATAL 无法 import mmdpipe.cache_state：%s" % _exc)
    sys.stdout.flush()
    os._exit(4)


def observe(path):
    """只读观测：返回喂给 `cache_state` 的记录。"""
    rec = {"path": path, "exists": os.path.exists(path)}
    if not rec["exists"]:
        return rec
    bpy.ops.wm.open_mainfile(filepath=path)
    rbw = bpy.context.scene.rigidbody_world
    if rbw is None:
        rec["has_physics"] = False
        return rec
    pc = rbw.point_cache
    rec.update(has_physics=True,
               bodies=len([o for o in bpy.data.objects
                           if getattr(o, "rigid_body", None) is not None]),
               is_baked=bool(pc.is_baked), is_outdated=bool(pc.is_outdated),
               info=str(pc.info), cache_frames=[pc.frame_start, pc.frame_end])
    try:
        rec["use_disk_cache"] = bool(pc.use_disk_cache)
    except AttributeError as exc:      # 记下来，不要猜
        rec["use_disk_cache_error"] = str(exc)
    return rec


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out_json = None
    behavior_path = None
    for flag in ("--out", "--behavior"):
        if flag in argv:
            i = argv.index(flag)
            value = argv[i + 1]
            argv = argv[:i] + argv[i + 2:]
            if flag == "--out":
                out_json = value
            else:
                behavior_path = value
    if not argv:
        raise SystemExit("usage: m02_cache_gate.py -- scene.blend [...] [--out out.json] [--behavior b.json]")

    behaviors = {}
    if behavior_path:
        with open(behavior_path, encoding="utf-8") as fh:
            behaviors = json.load(fh)

    records, sidecars = {}, {}
    for path in argv:
        rec = observe(path)
        key = os.path.normcase(os.path.abspath(path))
        stem = os.path.splitext(os.path.basename(path))[0]
        for bpath, behavior in behaviors.items():
            if str(bpath).startswith("_"):
                continue
            same_path = os.path.normcase(os.path.abspath(bpath)) == key
            same_name = os.path.splitext(os.path.basename(str(bpath)))[0] == stem
            if same_path or same_name:
                rec["behavior"] = behavior
        records[path] = rec
        sidecars[path] = cache_state.sidecar(rec)

    code, report = cache_state.evaluate_many(records)
    for path, judged in report.items():
        report[path].update(sidecars[path])

    if out_json:
        with open(out_json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
    for path, rec in report.items():
        print("GATE %-52s %-24s (exit %s)"
              % (os.path.basename(path), rec["verdict"], rec["exit_code"]))
    print(json.dumps({p: r["verdict"] for p, r in report.items()}, ensure_ascii=False))
    sys.stdout.flush()
    os._exit(code)


main()
