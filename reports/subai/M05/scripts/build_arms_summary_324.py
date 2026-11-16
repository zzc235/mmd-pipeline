"""把 `out/subai/M05/arms/20261116_324/` 的七臂记录汇总成一份可提交的物证摘要。

只读 scratch，写 `reports/subai/M05/arms/20261116_324/summary.json`。
`readback_arms.json`（产物回读）存在就并进去，不存在就显式写 `null` 并注明为什么 —— 不许沉默。
"""
import io
import json
import os
import sys

def find_repo_root(start):
    """往上走到有 `coordination/` 与 `mmdpipe/` 的那一层；走不到就把起点打出来再死。

    不写死 `dirname` 次数：同一份脚本既可能在 `out/subai/M05/`（产物树）也可能在
    `reports/subai/M05/scripts/`（仓库），深度不同，写死必然有一边算错，而算错的样子是
    `ImportError`（看起来像「这个模块不存在」）。
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

SRC = os.path.join(ROOT, "out", "subai", "M05", "arms", "20261116_324")
DST_DIR = os.path.join(ROOT, "reports", "subai", "M05", "arms", "20261116_324")


def _has_flag(name):
    return name in sys.argv


def _arg_value(name):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def load(path):
    with io.open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def frozen_mode(path):
    if not path or not os.path.exists(path):
        return None
    return oct(os.stat(path).st_mode & 0o777)


def arm_row(name, d):
    a = d.get("action") or {}
    w = d.get("window") or {}
    sc = d.get("scene") or {}
    c = d.get("cache") or {}
    o = d.get("out_blend") or {}
    ib = d.get("in_blend") or {}
    return {
        "arm": name,
        "arm_role": d.get("arm_role"),
        "verdict": d.get("verdict"),
        "checks": {c.get("id"): c.get("ok") for c in (d.get("checks") or [])},
        "checks_detail": {c.get("id"): c.get("detail") for c in (d.get("checks") or [])},
        "artifact": {
            "path_rel": os.path.relpath(o["path"], ROOT) if o.get("path") else None,
            "basename": os.path.basename(o["path"]) if o.get("path") else None,
            "bytes": o.get("bytes"),
            "sha256": o.get("sha256"),
            "frozen_mode": frozen_mode(o.get("path")),
        },
        "action": {"name": a.get("name"), "fcurves": a.get("fcurves"),
                   "frame_range": a.get("frame_range"), "nla_tracks": a.get("nla_tracks")},
        "window": w,
        "scene": sc,
        "cache": c,
        "in_blend": {"path": ib.get("path"), "bytes": ib.get("bytes"), "sha256": ib.get("sha256")},
        "source": d.get("source"),
        "notes": d.get("notes"),
    }


def _cmp_fields(row):
    """回读字段（真实比较用的那六格），缺就返回 None —— 不许拿「差不多」当相同。"""
    if row is None:
        return None
    w = row.get("window") or {}
    a = row.get("action") or {}
    sc = row.get("scene") or {}
    c = row.get("cache") or {}
    vals = [w.get("frame_end"), a.get("fcurves"), a.get("frame_range"),
            sc.get("fps_after"), c.get("is_baked"), c.get("is_outdated")]
    return None if any(v is None for v in vals) else vals


def _is_manifest(name):
    """`*manifest*.json` 不是臂记录 —— 排除规则与 `coordination.artifact_audit` 对齐。

    不加这条会出事：批次目录后来放进了 `manifest.json`（冻结账本），而本脚本把目录里
    每个 `.json` 都当一条臂记录 ⇒ 重跑会多出一条 `{"arm": "manifest", ...全 None}` 的假记录，
    把已提交的物证摘要静默改写（实测 30 965 → 31 580 字节）。**账本混进输入**是这一类。
    """
    low = name.lower()
    return "manifest" in low and low.endswith(".json")


def main():
    batch = load(os.path.join(SRC, "batch_report.json"))
    names = sorted(n[:-5] for n in os.listdir(SRC)
                   if n.endswith(".json")
                   and not _is_manifest(n)
                   and n not in ("batch_report.json", "readback_arms.json"))
    arms = [arm_row(n, load(os.path.join(SRC, n + ".json"))) for n in names]

    rb_path = os.path.join(SRC, "readback_arms.json")
    if os.path.exists(rb_path):
        rb = load(rb_path)
        readback = {"status": "measured", "file": "readback_arms.json",
                    "read_only": rb.get("read_only"), "arms": rb.get("arms")}
    else:
        readback = {"status": "not_run",
                    "why": "产物回读被 4号 的 stage_bake 窗口占住，尚未执行；"
                           "臂件里 bodies=324 / mask_wired 完好这一条目前只是结构性推断，"
                           "任何按 bodies 判 READY 的用法都必须当「待验」。",
                    "arms": None}

    sha_a = next((x["artifact"]["sha256"] for x in arms if x["arm"] == "C_W1"), None)
    sha_b = next((x["artifact"]["sha256"] for x in arms if x["arm"] == "C_W1_rerun"), None)
    row_a = next((x for x in arms if x["arm"] == "C_W1"), None)
    row_b = next((x for x in arms if x["arm"] == "C_W1_rerun"), None)
    fa, fb = _cmp_fields(row_a), _cmp_fields(row_b)
    fields_identical = None if (fa is None or fb is None) else (fa == fb)

    out = {
        "schema": "m05_arms_summary/1",
        "batch_id": batch.get("batch_id"),
        "generated_from": "out/subai/M05/arms/20261116_324/*.json",
        "driver": {"rc": batch.get("rc"), "mismatched": batch.get("mismatched"),
                   "arms_expected": batch.get("expected")},
        "input": batch.get("in_blend"),
        "arms": arms,
        "artifact_readback": readback,
        "byte_reproducibility": {
            "what": "同一输入、同一脚本、两次跑出两份 C@W1（`C_W1` 与 `C_W1_rerun`）",
            "sha_a": sha_a,
            "sha_b": sha_b,
            "bytes_identical": bool(sha_a and sha_b and sha_a == sha_b),
            "readback_fields_identical": fields_identical,
            "readback_fields_compared": ["window.frame_end", "action.fcurves",
                                         "action.frame_range", "scene.fps_after",
                                         "cache.is_baked", "cache.is_outdated"],
            "readback_fields_a": fa,
            "readback_fields_b": fb,
            "meaning": "`.blend` 字节复现性不稳定；幂等/身份只能建在回读字段上，"
                       "「字节变了=有人改过」永远不成立。",
        },
    }
    os.makedirs(DST_DIR, exist_ok=True)
    dst = os.path.join(DST_DIR, "summary.json")
    # 默认输出是**已提交的物证摘要**：重跑一次就会静默改写交付证据，所以默认拒绝覆盖，
    # 要覆盖必须显式 `--force`；`--out` 只用于验证（写到临时路径，产物树不留东西）。
    override = _arg_value("--out")
    dst = override or dst
    if os.path.exists(dst) and not _has_flag("--force"):
        raise SystemExit("拒绝覆盖已有摘要：%s（确需重写加 --force）" % dst)
    with io.open(dst, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    print("WROTE %s" % dst)
    print("  arms=%d readback=%s" % (len(arms), readback["status"]))
    for row in out["arms"]:
        print("  %-16s %-8s end=%-4s fps=%s->%s baked=%-5s mode=%s"
              % (row["arm"], row["verdict"], (row["window"] or {}).get("frame_end"),
                 (row["scene"] or {}).get("fps_before"), (row["scene"] or {}).get("fps_after"),
                 (row["cache"] or {}).get("is_baked"), row["artifact"]["frozen_mode"]))


main()
