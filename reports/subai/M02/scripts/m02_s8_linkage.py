"""M02 · S8 阶段 E 的静态旁证：把「最近的碰撞对」按结构分成两类。

    python m02_s8_linkage.py <pmx> <s8_collide_pairs.json> <out.json>

为什么需要它：A/B 逐字节相同，意味着 Blender 层碰撞解算对 18 根下摆骨零贡献。零贡献有两种成因，
数据本身分不开：(i) 场景里根本没有两体接触；(ii) 该字段在本工程没被消费。
Blender 的刚体约束（MMD 关节导入后就是它）默认**关闭被约束连接的这对刚体之间的碰撞**（Bullet
`disableCollisionsBetweenLinkedBodies`），所以「结构上被关节连起来的对」本来就不可能互撞。
这里把碰撞对分成「有关节连接 / 无关节连接」两类，给出后者在静止姿态下的最小中心距——
它才是真正可能接触的那一批。

尺度：PMX size 是 PMX 单位，本脚本同时给 PMX 单位与「按 mmd_tools 默认 0.08 缩放」的米值，
后者标 `assumed_scale`，没有从工程里核实过，不作判据。
"""
import json
import math
import sys

sys.path.insert(0, r"E:\code\mmdpipe-ai\A1")
from mmdpipe import pmx  # noqa: E402

ASSUMED_SCALE = 0.08


def radius(r):
    """构型无关的保守半径上界：球=size[0]，胶囊=size[0]，箱=size 三轴的最大值×√3。"""
    if r.shape == 0:
        return abs(r.size[0])
    if r.shape == 2:
        return abs(r.size[0])
    return math.sqrt(sum(abs(v) ** 2 for v in r.size[:3]))


def main():
    pmx_path, pairs_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    m = pmx.load(pmx_path)
    links = set()
    for j in m.joints:
        links.add(frozenset((j.rigid_a, j.rigid_b)))

    data = json.load(open(pairs_path, encoding="utf-8"))
    pairs = data["collide_pairs"]
    linked, unlinked = [], []
    for p in pairs:
        key = frozenset((p["a_index"], p["b_index"]))
        (linked if key in links else unlinked).append(p)

    def enrich(p):
        ra, rb = m.rigids[p["a_index"]], m.rigids[p["b_index"]]
        rsum = radius(ra) + radius(rb)
        return {"a": p["a"], "b": p["b"], "a_index": p["a_index"], "b_index": p["b_index"],
                "distance_m": round(p["distance_m"], 6),
                "radius_sum_pmx": round(rsum, 6),
                "radius_sum_m_if_scale_0.08": round(rsum * ASSUMED_SCALE, 6),
                "gap_m_if_scale_0.08": round(p["distance_m"] - rsum * ASSUMED_SCALE, 6)}

    unlinked.sort(key=lambda p: p["distance_m"])
    near = [enrich(p) for p in unlinked[:10]]
    rest_touching = [q for q in near if q["gap_m_if_scale_0.08"] <= 0]

    out = {"pmx": pmx_path, "pairs_total": len(pairs),
           "joint_linked_pairs": len(linked), "unlinked_pairs": len(unlinked),
           "assumed_scale": ASSUMED_SCALE,
           "scale_note": "0.08 是 mmd_tools 默认导入缩放，未从本工程核实；只作量级参考",
           "closest_unlinked": near,
           "closest_unlinked_touching_at_rest": rest_touching,
           "min_gap_m_if_scale_0.08": (min(q["gap_m_if_scale_0.08"] for q in near) if near else None),
           "interpretation_boundary": "本文件只回答「静止姿态下哪些碰撞对在结构上可能互撞」，"
                                      "不证明运行中是否接触；运行中的结论由 A/B 逐帧数据给。"}
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("pairs=%d linked=%d unlinked=%d closest_unlinked=%.6f m min_gap=%.6f m"
          % (len(pairs), len(linked), len(unlinked),
             near[0]["distance_m"] if near else -1,
             out["min_gap_m_if_scale_0.08"] if near else -1))


main()
