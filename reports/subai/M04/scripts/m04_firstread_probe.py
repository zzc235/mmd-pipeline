# -*- coding: utf-8 -*-
"""M04 · 「开件后第一次求值」对**基线**有没有偏差（`D-223` 派工件，`总控` 19:42 第 IV 条）

问题
----
`1号` 在引擎层坐实：开件后第一次求值 ≠ 顺序重算（四簇姿态差 `1.856515 / 1.863228 /
1.994664 / 1.994782 m`，与 `is_baked` 无关）。我的**每臂基线**就是「开件后立刻读窗口首帧」，
所以必须先答一个问题：**f1 的 5076 对基线，首读与走完一段再读，一样吗？**

- 一样 ⇒ 本轮基线不作废，不重测（省 12 分钟）；
- 不一样 ⇒ 三份基线全重取、重跑比较，并把差值记档。

`总控` 的要求：**用 5 分钟的量定 12 分钟的事，结果先报，不许先重跑。**
另：不许拿 `f417` 的姿态差推断 `f1` 的深度差 —— 量纲、帧都不同，必须在本帧上量。

四次读数（同一进程、同一份臂件、只读不 save）
---------------------------------------------
- `A`  开件后第一次求值：`frame_set(frame_start)` → 读 5076 对；
- `A2` 紧接着对同一帧再 `frame_set` 一次 → 再读（分离「首次求值」与「步进后状态」）；
- `A3` 不碰帧，直接再读一次（纯重复读，确定性的下界）；
- `B`  顺序步进 `frame_start..frame_end`（与测量路径同样的走帧方式）后回来读 `frame_start`。

另外把 `A` 与**冻结批次里那份真基线**逐对比一次：那份基线就是本轮所有穿透数字的零点，
能对上的话，「基线要不要重取」这个问题就地闭合。

用法（必须经 `coordination.lock guard` 代持锁）
----------------------------------------------
    blender -b --python m04_firstread_probe.py -- \
        --blend <C@W1.blend> --targets <roi_align_cd.json> --bones 下擺_0_0,... \
        --frames 1:240 --frozen-baseline <baseline_C_W1.json> --out <json>
"""
import argparse
import io
import json
import os
import sys
import time

# ---- 前置守卫：判目标 → 判输入，**都发生在 import bpy 之前** --------------------
# `3号` 20:09 的教训：他第一版把守卫排在测量之后，负控崩在更早的 `bpy.data.filepath == ''`
# 上、拿到 `rc=3` —— 那「不是守卫有效，是守卫根本没被走到」。而且 rc 非零会把「崩了」
# 读成「拒绝了」。所以顺序是：判目标 → 判输入身份 → 干活 → 落盘，前三步在 import bpy 之前。
EXIT_NOT_MEASURED = 10
EXIT_BAD_INPUT = 11
EXIT_REFUSED_OVERWRITE = 10


def _opt(argv, name):
    for i, tok in enumerate(argv):
        if tok == name and i + 1 < len(argv):
            return argv[i + 1]
        if tok.startswith(name + "="):
            return tok.split("=", 1)[1]
    return None


def _utf8_stdio():
    """编码契约是两头的：父进程按 UTF-8 解码 ⇒ 子进程必须按 UTF-8 写。

    `PYTHONIOENCODING=gbk` 时子进程的 `stderr` 是 GBK，父进程解码成 UTF-8 就变成乱码，
    于是「REFUSE 的文案里有没有那个路径」这类断言会**在三环境中的一档里假红**。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001  Blender 的流未必支持 reconfigure
            pass


def preflight(argv):
    """目标/输入前置检查；不通过就带语义码退出（Blender 不必参与）。"""
    _utf8_stdio()
    out = _opt(argv, "--out")
    blend = _opt(argv, "--blend")
    force = "--force" in argv
    if not out:
        sys.stderr.write("REFUSE 缺 --out\n")
        raise SystemExit(EXIT_BAD_INPUT)
    if blend and not os.path.exists(blend):
        sys.stderr.write("REFUSE 输入件不在：%s\n" % blend)
        raise SystemExit(EXIT_BAD_INPUT)
    if os.path.exists(out) and not force:
        sys.stderr.write("REFUSE 已有读数：%s（确需重测加 --force）\n" % out)
        raise SystemExit(EXIT_REFUSED_OVERWRITE)
    return {"out": out, "blend": blend, "force": force}


_PREFLIGHT = preflight(sys.argv[sys.argv.index("--") + 1:]) if "--" in sys.argv else None

import addon_utils  # noqa: E402
import bpy  # noqa: E402

sys.path.insert(0, r"E:\dsh pr\woker2")
sys.path.insert(0, r"E:\code\mmdpipe-ai\A2")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from m04_capsule_probe import (  # noqa: E402
    as_clearance, bone_of, pair_key, rigid_objs, roi_bones, selftest)

from mmdpipe import clearance as C  # noqa: E402

EPS = 1e-12

# Blender 侧探针自己的语义码从 10 起（`4号` 20:08 实测 + 建议）：
# `coordination.lock` 用 2/3/4/5（用法/冲突/不可判定/guard 丢锁），guard 又透传命令 rc；
# 若探针也用 3 报「自检没过」，一次读数就分不出「脚本拒绝」和「锁被别人占着」。
# `--python-exit-code 3` 仍是意外异常的兜底。
EXIT_NOT_MEASURED = 10


def _args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blend", required=True)
    ap.add_argument("--targets", required=True)
    ap.add_argument("--bones", required=True)
    ap.add_argument("--frames", required=True, help="start:end（只用来定步进范围）")
    ap.add_argument("--frozen-baseline", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--selftest-tol", type=float, default=0.05)
    return ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])


def _sha_pairs(pairs):
    items = sorted((k, "%.12f" % v) for k, v in pairs.items())
    blob = json.dumps(items, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _compare(a, b):
    keys = sorted(set(a) | set(b))
    diffs = []
    for k in keys:
        va, vb = a.get(k), b.get(k)
        if va is None or vb is None:
            diffs.append({"pair": k, "a": va, "b": vb, "delta": None, "missing": True})
            continue
        d = abs(float(va) - float(vb))
        if d > EPS:
            diffs.append({"pair": k, "a": va, "b": vb, "delta": d})
    diffs.sort(key=lambda r: (-1.0 if r["delta"] is None else -r["delta"]))
    return {
        "pairs_a": len(a), "pairs_b": len(b),
        "common": sum(1 for k in keys if k in a and k in b),
        "differing": len(diffs),
        "max_abs_delta_m": (max((r["delta"] for r in diffs
                                 if r["delta"] is not None), default=0.0)),
        "top": diffs[:8],
        "all_diffs": diffs,
        "identical": not diffs,
    }


def main():
    a = _args()
    _utf8_stdio()
    t0 = time.time()
    for mod in ("bl_ext.user_default.mmd_tools", "mmd_tools"):
        try:
            addon_utils.enable(mod, default_set=False, handle_error=None)
            print("[firstread] addon enabled: " + mod, flush=True)
            break
        except Exception:  # noqa: BLE001
            continue

    chk = selftest(a.selftest_tol)
    print("[firstread] selftest " + json.dumps(chk, ensure_ascii=True), flush=True)
    if not chk["pass"]:
        json.dump({"status": "NOT_MEASURED", "reason": "胶囊口径自检未过", "selftest": chk},
                  open(a.out, "w", encoding="utf-8", newline="\n"),
                  ensure_ascii=False, indent=2)
        sys.exit(EXIT_NOT_MEASURED)

    # 这一次 `open_mainfile` 之后的第一帧求值就是被质疑的那一次，中途不许再开件。
    bpy.ops.wm.open_mainfile(filepath=a.blend)
    sc = bpy.context.scene
    cache_state = {}
    pc = sc.rigidbody_world.point_cache if sc.rigidbody_world else None
    if pc is not None:
        cache_state = {"is_baked": bool(pc.is_baked),
                       "is_outdated": bool(pc.is_outdated),
                       "use_disk_cache": bool(getattr(pc, "use_disk_cache", False)),
                       "info": getattr(pc, "info", None)}

    names = [x.strip() for x in a.bones.split(",") if x.strip()] or roi_bones(a.targets)
    objs = rigid_objs()
    named = {}
    for ob in objs:
        named.setdefault(bone_of(ob), []).append(ob)
    roi_objs = [ob for n in names for ob in named.get(n, [])]
    roi_ids = set(id(o) for o in roi_objs)
    others = [o for o in objs if id(o) not in roi_ids]

    f0, f1 = [int(x) for x in a.frames.split(":")]
    bf = max(f0, int(sc.frame_start))

    def read_pairs():
        roi_rbs = [(o, as_clearance(o)) for o in roi_objs]
        other_rbs = [(o, as_clearance(o)) for o in others]
        out = {}
        for o, rb_a in roi_rbs:
            ba = bone_of(o) or o.name
            for o2, rb_b in other_rbs:
                pen, _ = C.penetration(rb_a, rb_b)
                out[pair_key(ba, bone_of(o2) or o2.name)] = max(0.0, float(pen))
        return out

    passes = {}
    # A：开件后第一次求值
    sc.frame_set(bf)
    passes["A"] = read_pairs()
    print("[firstread] A read (first evaluation after open): %d pairs" % len(passes["A"]),
          flush=True)
    # A2：同一帧再求值一次
    sc.frame_set(bf)
    passes["A2"] = read_pairs()
    # A3：不碰帧，纯重复读
    passes["A3"] = read_pairs()
    # B：顺序步进整段后再回来
    twalk = time.time()
    for f in range(int(sc.frame_start), f1 + 1):
        sc.frame_set(f)
    print("[firstread] walked %d..%d in %.1fs"
          % (int(sc.frame_start), f1, time.time() - twalk), flush=True)
    sc.frame_set(bf)
    passes["B"] = read_pairs()

    doc = {
        "status": "MEASURED",
        # `D-225` 规则第九条②：求值层读数必须声明层、并带 `first_eval_after_open` 与
        # `warmup_frames`。本探针**故意的**不热身（A 就是「开件后第一次求值」），所以
        # 它是一份判别用读数，不是可交付的姿态读数。
        "layer": "eval",
        "layer_note": "数据层字段（rigid_body/mask/is_baked…）与姿态/深度无关；本条读的是求值层",
        "purpose": "开件后第一次求值对每臂基线（f1 的 5076 对）有没有偏差",
        "blend": a.blend,
        "frames": [f0, f1],
        "baseline_frame": bf,
        "frame_start": int(sc.frame_start),
        "walked": [int(sc.frame_start), f1],
        "roi_bones": names,
        "roi_objs": len(roi_objs),
        "other_objs": len(others),
        "cache_state": cache_state,
        "passes": {k: {"pairs": len(v), "zero_overlap": sum(1 for x in v.values() if x == 0.0),
                       "sha256": _sha_pairs(v),
                       "warmup_frames": 0 if k in ("A", "A2", "A3") else (f1 - int(sc.frame_start) + 1),
                       "first_eval_after_open": k == "A"}
                   for k, v in passes.items()},
        "compare": {
            "A_vs_A3": _compare(passes["A"], passes["A3"]),
            "A_vs_A2": _compare(passes["A"], passes["A2"]),
            "A_vs_B": _compare(passes["A"], passes["B"]),
            "A2_vs_B": _compare(passes["A2"], passes["B"]),
        },
        "elapsed_s": round(time.time() - t0, 1),
        "selftest": chk,
        "caveats": [
            "胶囊口径：刚体近似体，不是网格；这里只判「基线这两份深度表是否相同」",
            "只在 C@W1 上量（总控指定的廉价判别）；换臂件不能推断",
        ],
    }

    if a.frozen_baseline and os.path.exists(a.frozen_baseline):
        with open(a.frozen_baseline, encoding="utf-8") as fh:
            froz = json.load(fh)
        base = {k: float(v) for k, v in froz.get("baseline_m", {}).items()}
        doc["frozen_baseline"] = {
            "path": a.frozen_baseline,
            "pairs": froz.get("pairs"),
            "frame": froz.get("baseline_frame"),
            "sha256_file": hashlib.sha256(open(a.frozen_baseline, "rb").read()).hexdigest(),
            "A_vs_frozen": _compare(passes["A"], base),
            "B_vs_frozen": _compare(passes["B"], base),
        }
        print("[firstread] A vs frozen: identical=%s differing=%d max=%.12f"
              % (doc["frozen_baseline"]["A_vs_frozen"]["identical"],
                 doc["frozen_baseline"]["A_vs_frozen"]["differing"],
                 doc["frozen_baseline"]["A_vs_frozen"]["max_abs_delta_m"]), flush=True)

    json.dump(doc, open(a.out, "w", encoding="utf-8", newline="\n"),
              ensure_ascii=False, indent=2, sort_keys=True)
    print("[firstread] done: A_vs_A2 identical=%s  A_vs_B identical=%s  A_vs_B max=%.12f m"
          % (doc["compare"]["A_vs_A2"]["identical"], doc["compare"]["A_vs_B"]["identical"],
             doc["compare"]["A_vs_B"]["max_abs_delta_m"]), flush=True)
    sys.stdout.flush()
    sys.exit(0)


if __name__ == "__main__":
    main()
