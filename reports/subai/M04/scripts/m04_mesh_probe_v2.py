"""M04 穿透探针 · 网格口径 v2（岛隔离 + 最近面法向符号的 signed distance）

v1 为什么死（`known_limits.md` 第四轮），三条都是**机制**层面的错：
  1. 奇偶射线法在开放/非流形网格上不成立（本网格 boundary_edges = 15712、non_manifold = 4187）；
  2. `find_nearest` 铺在整网格上，最近面被裙摆自己的双层薄壳吃掉 → 深度恒定偏小 ~1.7 cm；
  3. 三种错都长成「稳定的小负数」，看起来很像真穿入。

v2 只改这两处：
  A. **岛隔离**：本交付物里裙摆与身体在同一个 mesh 对象里（885 个连通岛），
     所以「双网格口径」落成「双岛集口径」：目标面 = 不含任何裙摆骨权重的岛。
     并对目标面集做**结构断言**（`target_has_skirt_polys` 必须为 0）——v1 的第 2 条错误
     被结构性排除，而不是靠统计。
  B. **符号用最近面法向**：`signed = dot(p − q, n_q)`，不依赖网格封闭性 ⇒ 第 1 条错误被排除。
     它只对浅穿入（毫米–厘米）局部有效，正是 M04 要判的量级。

自检口径（重要，别再拿「真实网格上做 ±法向偏移」当自检）：
  真实网格上「p − 3 cm·n 是否在体内」根本不是良定义的——薄于 6 cm 的部位、凹折处、
  开放边界都会让这个问题的答案与判据无关地翻面。**实测：按几何只筛不判，870 个候选里
  670 个（77%）连「能否计分」都不成立。** 所以自检分两段，各验一件事：

  * **判据正确性**（`--selftest-geometry synthetic`，默认）：在**闭流形解析实体**（UV 球 r=4 cm）
    上按同一段代码路径判：外推 10 cm 判外率、内推 3 cm 判内率、内推深度中位误差。
    这条验的是「实现与判据本身对不对」，不受真实网格拓扑污染。
  * **输入劣度**（同一份真实网格）：只报**不可计分比例**与目标面集的结构断言，
    不设阈值、不判 PASS——那个比例是这份输入的性质，不是方法的成绩。

  **鉴别力控制**（必须被判不过，否则说明自检没牙）：
    `flipped` 符号取反（在合成实体上跑）→ 必须判不过；
    `realm_parity` v1 的奇偶整网格判据（在真实网格上跑）→ 必须判不过（那是它死因的复现）。

顺序求值（P12/D-063）：帧序一律从 `scene.frame_start` 连续步进，冷跳不提供。

用法：
  blender --background --factory-startup --python m04_mesh_probe_v2.py -- \
      --blend <path> --meta <json> [--frames 1:20] [--measure]
  默认只出自检/控制读数（`status = METHOD_OK_NO_SCENE_NUMBERS`），不出场景数字。
"""
import argparse
import json
import math
import sys

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, r"E:\code\mmdpipe-ai\A2")
from mmdpipe.measure import SequentialEvalError, plan_sequential_eval  # noqa: E402

SKIRT_KEY = "\u4e0b\u64fa"  # 下擺


def _args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--blend", required=True)
    p.add_argument("--out", default="")
    p.add_argument("--meta", required=True)
    p.add_argument("--pattern", default=SKIRT_KEY + "_0_")
    p.add_argument("--frames", default="1:20")
    p.add_argument("--samples", type=int, default=300)
    p.add_argument("--selftest-min", type=float, default=0.95)
    p.add_argument("--depth-tol", type=float, default=0.005)
    p.add_argument("--outward-m", type=float, default=0.10)
    p.add_argument("--inward-m", type=float, default=0.03)
    p.add_argument("--sphere-radius-m", type=float, default=0.10)
    p.add_argument("--measure", action="store_true",
                   help="自检与控制都通过后才允许跑场景数字（默认只出自检读数）")
    return p.parse_args(argv)


# ---------------------------------------------------------------- 几何与判据


def uv_sphere(center=(0.0, 0.0, 0.0), radius=0.04, seg=48, ring=24):
    """闭流形 UV 球：顶点 + 四边形/三角形索引。用解析实体做自检，不依赖场景。"""
    cx, cy, cz = center
    verts = [Vector((cx, cy, cz + radius))]
    for j in range(1, ring):
        phi = math.pi * j / ring
        for i in range(seg):
            th = 2.0 * math.pi * i / seg
            verts.append(Vector((cx + radius * math.sin(phi) * math.cos(th),
                                 cy + radius * math.sin(phi) * math.sin(th),
                                 cz + radius * math.cos(phi))))
    verts.append(Vector((cx, cy, cz - radius)))
    polys = []
    for i in range(seg):
        polys.append((0, 1 + i, 1 + (i + 1) % seg))
    for j in range(ring - 2):
        base = 1 + j * seg
        nxt = base + seg
        for i in range(seg):
            a, b = base + i, base + (i + 1) % seg
            polys.append((a, b, nxt + (i + 1) % seg, nxt + i))
    last = len(verts) - 1
    base = 1 + (ring - 2) * seg
    for i in range(seg):
        polys.append((last, base + (i + 1) % seg, base + i))
    # 绕序必须是**外法向**：自检就是靠这一点判「法向符号对不对」，
    # 反向绕序会让「外面判成里面」——2026-11-16 第一次跑就这么被自检抓住（outward 0.0）。
    return verts, [tuple(reversed(p)) for p in polys]


def sphere_samples(radius, n, outward_m, inward_m):
    """球面上均匀取 n 点，返回 [(p, n̂, kind)]：已知外点 / 已知内点。"""
    golden = math.pi * (3.0 - math.sqrt(5.0))
    out = []
    for k in range(n):
        z = 1.0 - 2.0 * (k + 0.5) / n
        r = math.sqrt(max(0.0, 1.0 - z * z))
        th = golden * k
        nrm = Vector((r * math.cos(th), r * math.sin(th), z))
        p = nrm * radius
        out.append((p + nrm * outward_m, nrm, "out"))
        out.append((p - nrm * inward_m, nrm, "in"))
    return out


def sdf(bvh, p, flip=False):
    """最近面法向符号的 signed distance：负 = 在面内侧（穿入）。"""
    loc, nor, idx, dist = bvh.find_nearest(p)
    if loc is None:
        return None
    n = nor.normalized()
    signed = (p - loc).dot(n)
    return -signed if flip else signed


def parity_inside(bvh, co, direction):
    """v1 的奇偶法——只作为「应当被否」的对照判据保留。"""
    hits, origin, guard = 0, co.copy(), 0
    while guard < 32:
        guard += 1
        loc, nor, idx, dist = bvh.ray_cast(origin, direction)
        if loc is None:
            break
        hits += 1
        origin = loc + direction * 1e-4
    return hits % 2 == 1


def selftest_sdf(bvh, points, cfg, flip=False):
    """在解析实体上判：已知外点必须判外，已知内点必须判内且深度对。"""
    out_ok = in_ok = 0
    n_out = n_in = 0
    errs = []
    for p, nrm, kind in points:
        s = sdf(bvh, p, flip)
        if s is None:
            continue
        if kind == "out":
            n_out += 1
            if s > 0.0:
                out_ok += 1
        else:
            n_in += 1
            if s < 0.0:
                in_ok += 1
                errs.append(abs(s) - cfg["inward_m"])
    errs.sort()
    return {
        "outward_rate": round(out_ok / float(n_out), 4) if n_out else 0.0,
        "inward_rate": round(in_ok / float(n_in), 4) if n_in else 0.0,
        "inward_depth_median_err_m": round(errs[len(errs) // 2], 6) if errs else None,
        "n_out": n_out, "n_in": n_in,
    }


def selftest_parity(bvh, points, cfg):
    direction = Vector((1.0, 0.0, 0.0))
    out_ok = in_ok = 0
    n_out = n_in = 0
    errs = []
    for p, nrm, kind in points:
        if kind == "out":
            n_out += 1
            if not parity_inside(bvh, p, direction):
                out_ok += 1
        else:
            n_in += 1
            if parity_inside(bvh, p, direction):
                in_ok += 1
                loc, _, _, d = bvh.find_nearest(p)
                if loc is not None:
                    errs.append(d - cfg["inward_m"])
    errs.sort()
    return {
        "outward_rate": round(out_ok / float(n_out), 4) if n_out else 0.0,
        "inward_rate": round(in_ok / float(n_in), 4) if n_in else 0.0,
        "inward_depth_median_err_m": round(errs[len(errs) // 2], 6) if errs else None,
        "n_out": n_out, "n_in": n_in,
    }


# ---------------------------------------------------------------- 真实网格


class DSU(object):
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, a):
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def islands_of(me):
    dsu = DSU(len(me.vertices))
    for e in me.edges:
        dsu.union(e.vertices[0], e.vertices[1])
    groups = {}
    for v in me.vertices:
        groups.setdefault(dsu.find(v.index), []).append(v.index)
    return list(groups.values())


def manifold_stats(me):
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    out = {"boundary_edges": sum(1 for e in bm.edges if len(e.link_faces) == 1),
           "non_manifold_edges": sum(1 for e in bm.edges if len(e.link_faces) > 2)}
    bm.free()
    return out


def scoreable(bvh, p, n, min_thick, outward_m):
    """样本能否计分——只按几何筛，不看判据的答案。

    厚度不足（内推会穿到对面）或正上方 outward_m 内有别的面（外推会落进身体另一块）
    的样本是「测不了」，不是「测错了」。
    """
    eps = 1e-4
    loc, nor, idx, d = bvh.ray_cast(p - n * eps, -n, 0.5)
    if loc is None or (d + eps) < min_thick:
        return False
    loc2, nor2, idx2, d2 = bvh.ray_cast(p + n * eps, n, outward_m * 1.2)
    if loc2 is not None:
        return False
    return True


def evaluated_snapshot(ob, dg):
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    mw = ev.matrix_world
    co = [mw @ v.co for v in me.vertices]
    polys = [tuple(p.vertices) for p in me.polygons]
    ev.to_mesh_clear()
    return co, polys


def write_meta(path, doc):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)


def main():
    a = _args()
    cfg = {"outward_m": a.outward_m, "inward_m": a.inward_m}
    t0_meta = {"basis": "mesh", "method": "mesh_v2_island_sdf", "blend": a.blend,
               "not_equal_to": "刚体胶囊：胶囊只覆盖有刚体的骨，网格口径看的是顶点本身"}

    # ---- 1. 判据正确性：解析闭流形实体（不碰场景文件）----
    sverts, spolys = uv_sphere(radius=a.sphere_radius_m)
    bvh_s = BVHTree.FromPolygons(sverts, spolys, all_triangles=False, epsilon=0.0)
    pts = sphere_samples(a.sphere_radius_m, max(32, a.samples // 2),
                         a.outward_m, a.inward_m)
    syn = selftest_sdf(bvh_s, pts, cfg)
    syn.update({"mode": "sdf_on_synthetic_sphere", "sphere_radius_m": a.sphere_radius_m,
                "note": "球半径默认 10 cm：外推 10 cm 落在球外、内推 3 cm 仍在球内，两条都良定义"})
    ctrl_flip = selftest_sdf(bvh_s, pts, cfg, flip=True)
    ctrl_flip.update({"mode": "flipped_on_synthetic_sphere"})

    def fails(c):
        if c["outward_rate"] < a.selftest_min or c["inward_rate"] < a.selftest_min:
            return True
        err = c["inward_depth_median_err_m"]
        return err is None or abs(err) > a.depth_tol

    syn["pass"] = not fails(syn)
    ctrl_flip["rejected_as_designed"] = fails(ctrl_flip)
    print("[meshv2] selftest " + json.dumps(syn, ensure_ascii=True), flush=True)
    print("[meshv2] control_flipped " + json.dumps(ctrl_flip, ensure_ascii=True), flush=True)

    # ---- 2. 输入劣度：真实网格的岛隔离 + 结构断言 + 可计分比例 ----
    bpy.ops.wm.open_mainfile(filepath=a.blend)
    sc = bpy.context.scene
    dg = bpy.context.evaluated_depsgraph_get()
    cands = [o for o in bpy.data.objects if o.type == "MESH"
             and any(SKIRT_KEY in g.name for g in o.vertex_groups)]
    ob = max(cands, key=lambda o: len(o.data.vertices)) if cands else None
    realm = {"object": ob.name if ob else None}
    ctrl_realm = {}
    if ob is not None:
        me = ob.data
        gidx = {g.index: g.name for g in ob.vertex_groups}
        skirt_idx = {i for i, n in gidx.items() if SKIRT_KEY in n}
        roi_idx = {i for i, n in gidx.items() if a.pattern in n}
        vert_skirt, roi_bone = set(), {}
        for v in me.vertices:
            for ge in v.groups:
                if ge.group in skirt_idx and ge.weight > 1e-6:
                    vert_skirt.add(v.index)
                if ge.group in roi_idx and ge.weight >= 0.5:
                    roi_bone[v.index] = gidx[ge.group]
        isl = islands_of(me)
        body_islands = [g for g in isl if not any(i in vert_skirt for i in g)]
        body_vert = set()
        for g in body_islands:
            body_vert.update(g)

        sc.frame_set(sc.frame_start)
        dg.update()
        co, polys = evaluated_snapshot(ob, dg)
        body_polys = [p for p in polys if all(i in body_vert for i in p)]
        bvh_body = BVHTree.FromPolygons(co, body_polys, all_triangles=False, epsilon=0.0)
        bvh_whole = BVHTree.FromPolygons(co, polys, all_triangles=False, epsilon=0.0)

        # 结构断言：目标面集里不许出现带裙摆权重的顶点（v1 的深度偏置就是它们造成的）
        skirt_polys_in_target = sum(1 for p in body_polys if any(i in vert_skirt for i in p))

        # 可计分比例（只报数，不判 PASS）
        step = max(1, len(body_vert) // max(1, a.samples * 6))
        cand = scan = 0
        samples = []
        min_thick = a.inward_m + 0.01
        for i in sorted(body_vert)[::step]:
            loc, nor, idx, dist = bvh_body.find_nearest(co[i])
            if loc is None:
                continue
            cand += 1
            scan += 1
            if not scoreable(bvh_body, co[i], nor.normalized(), min_thick, a.outward_m):
                continue
            if len(samples) >= a.samples:
                break
            samples.append((co[i], nor.normalized()))
        # 真实网格上的同一套构造点（3 元组，带已知标签）
        realm_pts = []
        for p, n in samples:
            realm_pts.append((p + n * a.outward_m, n, "out"))
            realm_pts.append((p - n * a.inward_m, n, "in"))
        realm.update({
            "frame_start": int(sc.frame_start),
            "roi_pattern": a.pattern, "roi_bones": sorted(set(roi_bone.values())),
            "roi_verts": len(roi_bone), "skirt_verts": len(vert_skirt),
            "island_count": len(isl), "body_islands": len(body_islands),
            "body_polys": len(body_polys), "manifold": manifold_stats(me),
            "target_has_skirt_polys": skirt_polys_in_target,
            "scoreable_candidates": cand, "scoreable_kept": len(samples),
            "unscoreable_rate": round(1.0 - len(samples) / float(cand), 4) if cand else None,
            "unscoreable_note": "厚度 < %.3f m 或正上方 %.3f m 内有别的面 → 不可计分；"
                                "这是输入的性质，不是方法的成绩" % (min_thick, a.outward_m),
        })
        ctrl_realm = selftest_parity(bvh_whole, realm_pts, cfg)
        ctrl_realm.update({"mode": "parity_whole_mesh_on_realm",
                           "rejected_as_designed": fails(ctrl_realm),
                           "note": "v1 的判据在同一批可计分样本上的表现；必须判不过"})
        diag_realm = selftest_sdf(bvh_body, realm_pts, cfg)
        diag_realm.update({"mode": "sdf_on_realm_body_islands",
                           "note": "只作诊断读数、不设阈值：真实网格的薄/凹处会让"
                                   "「±法向偏移」本身不良定义（见 unscoreable_rate）"})

    ok = syn["pass"] and ctrl_flip["rejected_as_designed"] and ctrl_realm.get(
        "rejected_as_designed", True)
    doc = dict(t0_meta)
    doc.update({
        "status": "METHOD_OK_NO_SCENE_NUMBERS" if ok else "NOT_MEASURED",
        "reason": None if ok else "自检或鉴别力控制未过，拒绝出数",
        "thresholds": {"outward_min_rate": a.selftest_min, "inward_min_rate": a.selftest_min,
                       "inward_depth_tol_m": a.depth_tol,
                       "outward_m": a.outward_m, "inward_m": a.inward_m},
        "selftest": syn, "controls": {"flipped": ctrl_flip, "realm_parity": ctrl_realm},
        "realm_diag": diag_realm, "realm": realm,
    })
    if not ok:
        write_meta(a.meta, doc)
        print("[meshv2] ABORT selftest/control failed -> NOT_MEASURED", flush=True)
        sys.exit(3)
    if not a.measure:
        doc["note"] = "自检与控制都过；按派活边界，场景数字等新交付物再取"
        write_meta(a.meta, doc)
        print("[meshv2] METHOD_OK（未测量场景，--measure 才跑）", flush=True)
        sys.exit(0)

    # ---- 3. 场景数字（需 --measure）----
    f0, f1 = [int(x) for x in a.frames.split(":")]
    f0, f1 = max(f0, sc.frame_start), min(f1, sc.frame_end)
    try:
        plan = plan_sequential_eval(int(sc.frame_start), f0, f1)
    except SequentialEvalError as exc:
        doc.update({"status": "NOT_MEASURED", "reason": "顺序求值计划不可满足：%s" % exc})
        write_meta(a.meta, doc)
        sys.exit(3)
    if realm["target_has_skirt_polys"]:
        doc.update({"status": "NOT_MEASURED",
                    "reason": "目标面集里含 %d 个裙摆多边形——v1 的深度偏置机制没有被排除"
                              % realm["target_has_skirt_polys"]})
        write_meta(a.meta, doc)
        sys.exit(3)

    rows = []
    for f in plan["visited_frames"]:
        sc.frame_set(f)
        dg.update()
        if f < f0:
            continue
        co_f, polys_f = evaluated_snapshot(ob, dg)
        body_polys_f = [p for p in polys_f if all(i in body_vert for i in p)]
        bvh_f = BVHTree.FromPolygons(co_f, body_polys_f, all_triangles=False, epsilon=0.0)
        worst, worst_bone = 0.0, None
        for i, bone in roi_bone.items():
            s = sdf(bvh_f, co_f[i])
            if s is not None and s < worst:
                worst, worst_bone = s, bone
        rows.append({"frame": f, "roi": "18_skirt_mesh_v2",
                     "max_depth_m": round(worst, 6), "bone": worst_bone})
    with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    doc.update({"status": "MEASURED_UNVALIDATED", "eval_policy": plan["policy"],
                "frames": [f0, f1], "frames_measured": len(rows),
                "deepest": min(rows, key=lambda r: r["max_depth_m"]) if rows else None})
    write_meta(a.meta, doc)
    print("[meshv2] done frames=%d" % len(rows), flush=True)
    sys.exit(0)


main()
