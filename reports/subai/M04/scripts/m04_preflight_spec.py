# -*- coding: utf-8 -*-
"""生成 C@W1 / C@W2 / D 三臂的 `coordination.preflight` 请求（M04）。

**两个数都不许凭记忆取**（4号 2026-11-16 18:02 抓到的「两棵树拼数」）：

* `needs` = 这次要补的条数（`constraints_to_add`）；
* `cap` = `stage.constraint_limit()` 的返回值（与建场同一个函数）。

取数只有两条路，都不许有默认值：

```
--spec-source <场景自己的 stage_mask 记录 json>      # 首选：needed/already/skipped/verdict 全部读它
--needed N --already M --note-source "<这数从哪来>"  # 手给时必须写出处，缺 note 直接停
```

两者都不给、或 hand-given 缺出处 ⇒ **退出 4**（不是「用默认值凑一个」）。
理由：`8298`/`10111` 是 324 刚体树的数，`8499`/`1813`/`6686` 是 312 刚体树的数——把两棵树的数拼进同一份请求，
`READY` 会变成一句没意义的话（偏保守也仍是错的），下一个人会以为这轮要补 8298 条。

跑法（在哪个树里跑就传哪个树；C/D 由我在 A2 跑）：

    python reports/subai/M04/scripts/m04_preflight_spec.py \
        --worktree E:\\code\\mmdpipe-ai\\A2 \
        --spec-source <场景的 stage_mask json>
    python -m coordination.preflight --spec <out>/subai/M04/preflight_cd_spec.json --worktree .

技术要点（与 4号 的 M00 生成器同法）：`stage.py` 顶层 `import bpy`，本次只调纯函数，给 `bpy` /
`mathutils` 两个空壳就够——**不开 Blender、不占锁**。`--worktree` 会插到 `sys.path[0]`，所以
`constraint_limit()` 来自那棵树，不是安装版。
"""
import argparse
import hashlib
import io
import json
import os
import sys
import types

DEFAULT_WORKTREE = r"E:\code\mmdpipe-ai\A2"


def _parse(argv):
    ap = argparse.ArgumentParser(description="生成 C/D 三臂的 preflight 请求")
    ap.add_argument("--worktree", default=DEFAULT_WORKTREE)
    ap.add_argument("--out", default=None, help="输出 JSON（默认 <worktree>/out/subai/M04/）")
    ap.add_argument("--spec-source", default="",
                    help="场景自己的 stage_mask 记录（读 constraints_needed / _already / skipped）")
    ap.add_argument("--needed", default=None, type=int)
    ap.add_argument("--already", default=None, type=int)
    ap.add_argument("--note-source", default="", help="手给数时的出处；缺它即停")
    ap.add_argument("--batch-id", default="round2",
                    help="产物批次名（D-189 版本化落盘，与 m04_run_cd.py 的 --batch-id 对应）")
    return ap.parse_args(argv)


class Stop(Exception):
    """「停」的原因（缺记录 / 缺出处）都走这一条，统一退出码 4。"""


def _sha(path):
    with io.open(path, "rb") as fh:
        raw = fh.read()
    lf = raw.replace(b"\r\n", b"\n")
    return {"path": path, "bytes": len(raw),
            "sha256_raw": hashlib.sha256(raw).hexdigest(),
            "sha256_lf_normalized": hashlib.sha256(lf).hexdigest()}


def _record_branch(rec):
    """场景记录有两种形状，两种都认，但要说清用的是哪一种。

    * `top_level` —— `stage_mask()` 直接落盘的记录（顶层就是掩码数）；
    * `mask_wired_record` —— 回读件里的形状（`m02_m08_readback.py` 把
      `scene["mask_wired"]` 原样放在这个键下）；同一个数只有一个来源，不另算一遍。

    都找不到 ⇒ 返回 `("none")`，由调用方停下：`mask_triple` 那种「WIRED + 三个 null」
    不许被当成数（`4号` 18:51 也点了同一条）。
    """
    if rec.get("constraints_needed") is not None:
        return rec, "top_level"
    nested = rec.get("mask_wired_record")
    if isinstance(nested, dict) and nested.get("constraints_needed") is not None:
        return nested, "mask_wired_record"
    return rec, "none"


def numbers_from_scene_record(path):
    """从场景自己的 `stage_mask()` 记录里取数（`utf-8-sig`：PS 写出来的会带 BOM）。"""
    if not os.path.exists(path):
        raise Stop("缺场景记录：%s（不许凭记忆取数）" % path)
    with io.open(path, "r", encoding="utf-8-sig") as fh:
        raw = json.load(fh)
    rec, shape = _record_branch(raw)
    if shape == "none":
        raise Stop("场景记录里找不到 constraints_needed：%s（顶层与 mask_wired_record 都没有；"
                   "mask_triple 的 null 不算数）" % path)
    for key in ("constraints_needed", "constraints_already_blocked"):
        if rec.get(key) is None:
            raise Stop("场景记录缺 %r：%s" % (key, path))
    to_add = rec.get("constraints_to_add")
    if to_add is None:
        to_add = int(rec["constraints_needed"]) - int(rec["constraints_already_blocked"])
    source = _sha(path)
    source["shape"] = shape
    return {
        "needed": int(rec["constraints_needed"]),
        "already": int(rec["constraints_already_blocked"]),
        "to_add": int(to_add),
        "skipped": int(rec.get("skipped_count") or 0),
        "verdict": rec.get("verdict"),
        "capped": rec.get("constraints_capped"),
        "source": source,
    }


def numbers_hand_given(a):
    if a.note_source.strip() == "":
        raise Stop("手给 --needed/--already 时必须带 --note-source（这数从哪来），"
                         "否则停——不许凭记忆构造样例")
    return {"needed": int(a.needed), "already": int(a.already),
            "to_add": int(a.needed) - int(a.already),
            "skipped": 0, "verdict": None, "capped": None,
            "source": {"note": a.note_source.strip()}}


def _pick_numbers(a):
    if a.spec_source:
        return numbers_from_scene_record(a.spec_source)
    if a.needed is not None and a.already is not None:
        return numbers_hand_given(a)
    raise Stop("两个数不许凭记忆取：给 --spec-source <场景记录>，"
               "或 --needed/--already 且带 --note-source")


def main(argv=None):
    a = _parse(argv)
    try:
        numbers = _pick_numbers(a)
    except Stop as exc:
        print("[停] %s" % exc, file=sys.stderr)
        return 4

    worktree = os.path.abspath(a.worktree)
    sys.path.insert(0, worktree)
    sys.modules.setdefault("bpy", types.ModuleType("bpy"))
    _mathutils = types.ModuleType("mathutils")
    _mathutils.Vector = object
    sys.modules.setdefault("mathutils", _mathutils)

    from mmdpipe import stage                      # noqa: E402

    wired = {
        "constraints_needed": numbers["needed"],
        "constraints_already_blocked": numbers["already"],
        "constraints_to_add": numbers["to_add"],
        "skipped_count": numbers["skipped"],
    }
    fields = stage.mask_preflight_fields(wired)
    limit, guardrail = stage.constraint_limit(numbers["needed"])

    spec = {
        "task_id": "M04_CD_measure",
        "worktree": worktree,
        "provenance": {
            "mmdpipe/stage.py": os.path.join(worktree, "mmdpipe", "stage.py"),
            "mmdpipe/mask.py": os.path.join(worktree, "mmdpipe", "mask.py"),
        },
        # 租约这条不在生成时判：真跑前套锁、开跑前 `coordination.lock` 会说清楚。
        "lease": False,
        "outputs": [
            "out/subai/M04/penetration/%s/C_W1.meta.json" % a.batch_id,
            "out/subai/M04/penetration/%s/C_W2.meta.json" % a.batch_id,
            "out/subai/M04/penetration/%s/D.meta.json" % a.batch_id,
        ],
        **fields,
        "_derivation": {
            "batch_id": a.batch_id,
            "numbers_source": numbers["source"],
            "scene_record_verdict": numbers["verdict"],
            "scene_record_capped": numbers["capped"],
            "needed_pairs": numbers["needed"],
            "already_blocked": numbers["already"],
            "to_add": numbers["to_add"],
            "code_from": stage.__file__,
            "cap_from": "stage.constraint_limit(%d) -> (%d, guardrail_hit=%s)"
                        % (numbers["needed"], limit, guardrail),
            "DEFAULT_MAX_CONSTRAINTS": stage.mask_mod.DEFAULT_MAX_CONSTRAINTS,
            "note": "cap 由建场同一函数现算；needs/cap 的输入全部来自**这份场景记录**，不跨树拼数",
        },
    }
    out = a.out or os.path.join(worktree, "out", "subai", "M04", "preflight_cd_spec.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with io.open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(spec, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    print("written %s" % out)
    print("needs=%s cap=%s skipped=%s  (%s)"
          % (spec.get("needs"), spec.get("cap"), spec.get("skipped"), spec["_derivation"]["cap_from"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
