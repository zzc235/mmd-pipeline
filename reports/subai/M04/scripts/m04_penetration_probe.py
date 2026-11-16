"""M04 穿透探针 ⚠ 本方法未通过自检，数字不可用于判合格

2026-11-16 自检（`m04_probe_selftest.py`，`out/subai/M04/penetration/probe_selftest.json`）：
  * 外推 10 cm 的点只有 **82.6%** 被判为外部（17.4% 假阳）
  * 内推 3 cm 的点只有 **56.6%** 被判为内部（43.4% 假阴），且最近面距离比真值小 **1.7 cm**
=> 奇偶判内外对开放/自相交网格不可靠；最近面距离受薄壳双层影响系统性偏小。
=> 它量出的 −0.0171 m 落在方法偏置内，**不能**当作「没有 2 cm 穿入」的证据（thresholds.md 已撤回）。
   保留脚本是为了改进方法（manifold 子集 / signed distance），不是因为它能用。

原方法（自相交，网格级）：
  1. 取 evaluated mesh（armature 变形后）顶点世界坐标；
  2. ROI 顶点 = 顶点组权重 >= 0.5 落在 ROI 骨上的顶点；
  3. 用「不含任何 ROI 顶点」的面建 BVHTree（非 ROI 几何）；
  4. 判内外用射线奇偶法（+X 方向连续 ray_cast 计数，奇=在内部）；
  5. 深度 = -到最近非 ROI 面的距离（负值=穿入，与门禁口径一致）。

输出 JSONL：{"frame":int,"roi":str,"max_depth_m":float,"bone":str}
另落一份 meta（方法、参数、顶点数、耗时），不改源 .blend（不保存）。

用法：
  blender --background --python m04_penetration_probe.py -- \
      --blend <path> --targets <s2_targets.json> --out <jsonl> --meta <json>
      [--frames 1:240] [--max-verts 400]
"""
import argparse
import json
import math
import os
import sys
import time

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROI_LABEL = "18_skirt_rigid"


def _args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--blend", required=True)
    p.add_argument("--targets", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--meta", required=True)
    p.add_argument("--bones", default="", help="逗号分隔的骨名；给了就覆盖 --targets 的 ROI（对照组用）")
    p.add_argument("--pattern", default="", help="按子串自动取骨名（对照组用，例如 髪）")
    p.add_argument("--label", default="", help="ROI 标签")
    p.add_argument("--frames", default="1:240")
    p.add_argument("--require-selftest", action="store_true", default=True,
                   help="先跑自检，不达标就不出数字（默认开）")
    p.add_argument("--reproduce-unvalidated-v1", dest="require_selftest", action="store_false",
                   help="跳过自检，仅用于复现 v1 的不可信数字；产物 status=UNVALIDATED_REPLAY")
    p.add_argument("--selftest-min", type=float, default=0.95,
                   help="自检通过阈值：外推/内推各自的判对率下限")
    p.add_argument("--max-verts", type=int, default=400)
    p.add_argument("--stride", type=int, default=1)
    return p.parse_args(argv)


def roi_bones(path):
    d = json.load(open(path, encoding="utf-8"))
    names = []
    for t in d.get("targets", []):
        n = t.get("joint_name") or (t.get("rigid_b") or {}).get("bone")
        if n:
            names.append(n)
    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out, d.get("stage"), (d.get("source") or {}).get("path")


def find_mesh(arm_names):
    best, best_n = None, -1
    for ob in bpy.data.objects:
        if ob.type != "MESH":
            continue
        groups = {g.name for g in ob.vertex_groups}
        hit = len(groups & arm_names)
        if hit > best_n:
            best, best_n = ob, hit
    return best, best_n


def roi_vertices(ob, names, max_verts):
    idx_of = {}
    for g in ob.vertex_groups:
        if g.name in names:
            idx_of[g.index] = g.name
    verts = {}
    for v in ob.data.vertices:
        for ge in v.groups:
            if ge.group in idx_of and ge.weight >= 0.5:
                verts[v.index] = idx_of[ge.group]
                break
    picked = sorted(verts)
    if max_verts and len(picked) > max_verts:
        step = len(picked) / float(max_verts)
        picked = [picked[int(i * step)] for i in range(max_verts)]
    return {i: verts[i] for i in picked}


def inside_by_parity(bvh, co, direction):
    hits, origin, guard = 0, co.copy(), 0
    while guard < 32:
        guard += 1
        loc, nor, idx, dist = bvh.ray_cast(origin, direction)
        if loc is None:
            break
        hits += 1
        origin = loc + direction * 1e-5
    return hits % 2 == 1


def self_check(bvh_of, co, nor_of, samples=200):
    """自检：已知内外的构造点能不能判对。

    bvh_of(points, polys) -> BVHTree；这里对整网格做一次，然后：
      * p + 0.10·n 必须判「外部」；
      * p - 0.03·n 必须判「内部」，且最近面距离 ≈ 0.03 m。
    返回 (outward_rate, inward_rate, median_err)。达不到阈值就不许出数字。
    """
    n = len(co)
    step = max(1, n // samples)
    out_ok = in_ok = 0
    errs = []
    bvh = bvh_of(co)
    direction = Vector((1.0, 0.0, 0.0))
    for i in range(0, n, step):
        p = co[i]
        loc, nor, idx, dist = bvh.find_nearest(p)
        if loc is None:
            continue
        if not inside_by_parity(bvh, p + nor * 0.10, direction):
            out_ok += 1
        q = p - nor * 0.03
        if inside_by_parity(bvh, q, direction):
            in_ok += 1
            loc2, nor2, idx2, dist2 = bvh.find_nearest(q)
            if dist2 is not None:
                errs.append(dist2 - 0.03)
    tried = len(range(0, n, step))
    errs.sort()
    return {
        "samples": tried,
        "outward_10cm_rate": round(out_ok / tried, 4) if tried else 0.0,
        "inward_3cm_rate": round(in_ok / tried, 4) if tried else 0.0,
        "inward_depth_median_err_m": round(errs[len(errs) // 2], 6) if errs else None,
    }


def main():
    a = _args()
    t0 = time.time()
    names, stage, pmx_src = roi_bones(a.targets)
    bpy.ops.wm.open_mainfile(filepath=a.blend)
    sc = bpy.context.scene
    arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if a.bones:
        names = [x.strip() for x in a.bones.split(",") if x.strip()]
    elif a.pattern and arm:
        names = [b.name for b in arm.data.bones if a.pattern in b.name]
    roi_label = a.label or ROI_LABEL
    ob, hits = find_mesh(set(names))
    if ob is None or hits == 0:
        json.dump({"status": "NOT_MEASURED", "reason": "场景里没有同时带 ROI 顶点组的网格"},
                  open(a.meta, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("[probe] NOT_MEASURED no mesh with ROI groups")
        sys.exit(3)

    # 自检闸门：先证明方法在这份网格上量得准，再谈场景数字。
    # 2026-11-16 的教训就是顺序反了：先出 −0.0171 m，后自查发现偏置 1.7 cm，只好撤回。
    if a.require_selftest:
        sc.frame_set(sc.frame_start)
        dg = bpy.context.evaluated_depsgraph_get()
        ev0 = ob.evaluated_get(dg)
        me0 = ev0.to_mesh()
        mw0 = ev0.matrix_world
        co0 = [mw0 @ v.co for v in me0.vertices]
        polys0 = [tuple(p.vertices) for p in me0.polygons]
        chk = self_check(
            lambda pts: BVHTree.FromPolygons(pts, polys0, all_triangles=False, epsilon=0.0),
            co0, None)
        ev0.to_mesh_clear()
        chk["thresholds"] = {"outward_min_rate": a.selftest_min,
                             "inward_min_rate": a.selftest_min}
        ok = (chk["outward_10cm_rate"] >= a.selftest_min
              and chk["inward_3cm_rate"] >= a.selftest_min)
        chk["pass"] = ok
        print("[probe] selftest " + json.dumps(chk, ensure_ascii=True), flush=True)
        if not ok:
            json.dump({"status": "NOT_MEASURED",
                       "reason": "探针自检未过阈值，拒绝出数（见 selftest）",
                       "selftest": chk, "blend": a.blend, "roi": roi_label,
                       "elapsed_s": round(time.time() - t0, 1)},
                      open(a.meta, "w", encoding="utf-8", newline="\n"),
                      ensure_ascii=False, indent=2)
            print("[probe] ABORT selftest failed -> NOT_MEASURED")
            # 退出码 3 = UNKNOWN/NOT_MEASURED：只看退出码的自动化也必须知道这次没有可用数字
            sys.exit(3)
    else:
        chk = {"skipped": True}

    present = sorted({g.name for g in ob.vertex_groups} & set(names))
    roi = roi_vertices(ob, set(names), a.max_verts)
    f0, f1 = [int(x) for x in a.frames.split(":")]
    f0 = max(f0, sc.frame_start)
    f1 = min(f1, sc.frame_end)

    dg = bpy.context.evaluated_depsgraph_get()
    direction = Vector((1.0, 0.0, 0.0))
    rows, now = [], time.time()
    frames_done = 0
    per_frame = []
    for f in range(f0, f1 + 1, a.stride):
        sc.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        ev = ob.evaluated_get(dg)
        me = ev.to_mesh()
        mw = ev.matrix_world
        co = [mw @ v.co for v in me.vertices]
        roi_v = set(roi)
        faces = [tuple(p.vertices) for p in me.polygons
                 if all(vi not in roi_v for vi in p.vertices)]
        if not faces:
            ev.to_mesh_clear()
            continue
        used = sorted({vi for fc in faces for vi in fc})
        remap = {vi: i for i, vi in enumerate(used)}
        verts = [co[vi] for vi in used]
        polys = [tuple(remap[vi] for vi in fc) for fc in faces]
        bvh = BVHTree.FromPolygons(verts, polys, all_triangles=False, epsilon=0.0)
        worst, worst_bone, n_in = 0.0, None, 0
        for vi, bone in roi.items():
            p = co[vi]
            loc, nor, idx, dist = bvh.find_nearest(p)
            if loc is None or dist is None:
                continue
            if not inside_by_parity(bvh, p, direction):
                continue
            n_in += 1
            depth = -float(dist)
            if depth < worst:
                worst, worst_bone = depth, bone
        ev.to_mesh_clear()
        per_frame.append({"frame": f, "inside_verts": n_in, "max_depth_m": round(worst, 6),
                          "bone": worst_bone})
        rows.append({"frame": f, "roi": roi_label, "max_depth_m": round(worst, 6),
                     "bone": worst_bone})
        frames_done += 1
        if frames_done % 20 == 0:
            print("[probe] %d frames  %.1fs" % (frames_done, time.time() - now), flush=True)

    with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    deepest = min(rows, key=lambda r: r["max_depth_m"]) if rows else None
    touched = sum(1 for r in rows if r["max_depth_m"] < 0)
    meta = {
        "status": ("NOT_MEASURED" if not rows
                   else ("UNVALIDATED_REPLAY" if not a.require_selftest
                         else "MEASURED_UNVALIDATED")),
        "warning": (None if a.require_selftest else
                    "跳过自检产出的 v1 复现数据，仅用于复现旧数字，不得作为结论"),
        "selftest": chk,
        "method": "mesh-level self-intersection: evaluated vertices inside non-ROI geometry, "
                  "ray-parity inside test, depth = -distance to nearest non-ROI face",
        "blend": os.path.abspath(a.blend),
        "pmx_source_of_roi": pmx_src,
        "roi": roi_label,
        "roi_note": "s2_targets.json 的 18 根有刚体的下摆骨；历史 S4 行 11 那批骨 11/11 无刚体、"
                    "其工程已不存在，故不是 row11，与历史 -0.202 m 无可比性",
        "roi_bones_declared": names,
        "roi_bones_present": present,
        "mesh": ob.name,
        "mesh_vertices": len(ob.data.vertices),
        "roi_vertices_total": len(roi),
        "armature": arm.name if arm else None,
        "frames": [f0, f1, a.stride],
        "frames_measured": frames_done,
        "frames_with_penetration": touched,
        "deepest": deepest,
        "per_frame": per_frame,
        "elapsed_s": round(time.time() - t0, 1),
        "caveats": [
            "射线奇偶法对开放网格（裙摆单面片）可能把「背面」算成内部，深度只作下界参考",
            "自相交测量会把裙摆与腿/躯干的正常贴合也算成穿入，阈值侧仍按 epsilon 判",
        ],
    }
    json.dump(meta, open(a.meta, "w", encoding="utf-8", newline="\n"),
              ensure_ascii=False, indent=2)
    print("[probe] done frames=%d deepest=%s elapsed=%.1fs"
          % (frames_done, deepest, time.time() - t0))


main()
