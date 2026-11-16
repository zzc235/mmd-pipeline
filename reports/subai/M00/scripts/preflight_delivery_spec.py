"""生成「交付尺度重建」的 preflight 请求（`D-144③`：cap 不许手写）。

## 两条硬规矩

1. **`cap` 由 `stage.constraint_limit()` 现算** —— 与建场用的是同一个函数，不手抄
   （`DEFAULT_MAX_CONSTRAINTS=20000` 只是护栏，不是预算）。
2. **`needs` / `already` 必须来自某个产物**，要么给 `--spec-source <json>`（读
   `constraints_needed`），要么 `--needed/--already` + `--note-source` 写清出处。
   **什么都不给就停**——凭记忆构造样例是这一族缺陷的源头。

## 为什么删掉旧的「从 result_attempt11.md 正则取 8298」

`8298` 与 `10111` 是 **324 刚体**那棵树上的数（含 11 个模板命名静态占位体）；1号 这轮重建的
交付场景是 **312 刚体**，`constraints_needed = 8499`（added 6686 + already 1813）。旧正则会把
过期数带进新场景的 preflight，且**看起来一切正常**。所以现在只认显式来源。

跑法（在谁的工作树里跑就传谁的树；M08 重建那一步由 1号 用自己的树跑）：

    python out/subai/M00/scripts/preflight_delivery_spec.py --worktree E:\\\\code\\\\mmdpipe-ai\\\\A1 ^
        --spec-source reports/subai/M02/m08_round1/stage_mask_after_rebuild.json
    python -m coordination.preflight --spec out/subai/M00/preflight_delivery_spec.json --worktree .

生成与消费必须读**同一份代码**：脚本把 `--worktree` 插到 `sys.path[0]`，所以
`constraint_limit()` 来自那棵树，不是安装版。
"""
import argparse
import hashlib
import json
import os
import sys
import types

DEFAULT_WORKTREE = r"E:\\code\\mmdpipe-ai\\A4"


def _parse(argv):
    ap = argparse.ArgumentParser(description="生成交付尺度的 preflight 请求")
    ap.add_argument("--worktree", default=DEFAULT_WORKTREE, help="worktree 根（默认 A4）")
    ap.add_argument("--out", default=None, help="输出 JSON（默认 <worktree>/out/subai/M00/）")
    ap.add_argument("--spec-source", default=None,
                    help="从这份产物读 constraints_needed（如 stage_mask_after_rebuild.json）")
    ap.add_argument("--needed", type=int, default=None, help="总对数（必须配 --note-source）")
    ap.add_argument("--already", type=int, default=None, help="其中已经挡对的条数")
    ap.add_argument("--note-source", default="",
                    help="--needed/--already 的出处（一句话，缺了就不许跑）")
    return ap.parse_args(argv)


def _sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def numbers_from_source(path):
    """从产物里读 `constraints_needed`（缺就停，不猜）。"""
    with open(path, "r", encoding="utf-8-sig") as fh:
        data = json.load(fh)
    needed = data.get("constraints_needed")
    already = data.get("constraints_already_blocked")
    if needed is None:
        raise SystemExit("产物里没有 constraints_needed：%s —— 不在这里猜" % path)
    return int(needed), (None if already is None else int(already))


def recorded_numbers(args):
    """返回 (already, needed, 出处说明)。没有任何显式来源就停。"""
    if args.spec_source:
        path = os.path.abspath(args.spec_source)
        if not os.path.isfile(path):
            raise SystemExit("--spec-source 指的文件不存在：%s" % path)
        needed, already_from_file = numbers_from_source(path)
        already = already_from_file if already_from_file is not None else args.already
        if already is None:
            raise SystemExit(
                "产物里没有 constraints_already_blocked，请显式给 --already（并说明出处）")
        return int(already), needed, "spec_source=%s sha256=%s" % (path, _sha256(path))
    if args.needed is not None or args.already is not None:
        if args.needed is None or args.already is None:
            raise SystemExit("--needed 与 --already 必须一起给（只给一个不做推断）")
        if not args.note_source.strip():
            raise SystemExit("手给数字必须配 --note-source（写清这数从哪个产物来）")
        return int(args.already), int(args.needed), "manual: %s" % args.note_source.strip()
    raise SystemExit(
        "没有任何数字来源：给 --spec-source <产物 json>，或 --needed/--already + --note-source。"
        "凭记忆构造样例正是这一族缺陷的源头，脚本拒绝代劳。")


def main(argv=None):
    args = _parse(argv)
    worktree = os.path.abspath(args.worktree)
    sys.path.insert(0, worktree)
    # stage.py 顶层 `import bpy`；本次只调纯函数，给两个空壳就够（不开 Blender、不占锁）
    sys.modules.setdefault("bpy", types.ModuleType("bpy"))
    _mathutils = types.ModuleType("mathutils")
    _mathutils.Vector = object
    sys.modules.setdefault("mathutils", _mathutils)

    from mmdpipe import stage                      # noqa: E402

    already, needed, source = recorded_numbers(args)
    if needed < already:
        raise SystemExit("needed(%d) < already(%d) —— 两个数来自不同场景？先核出处" % (needed, already))
    to_add = needed - already
    fields = stage.mask_preflight_fields({
        "constraints_needed": needed,
        "constraints_already_blocked": already,
        "constraints_to_add": to_add,
        "skipped_count": 0,
    })
    limit, guardrail = stage.constraint_limit(needed)
    spec = {
        "task_id": "M08_delivery_rebuild",
        "worktree": worktree,
        "provenance": {
            "mmdpipe/stage.py": os.path.join(worktree, "mmdpipe", "stage.py"),
            "mmdpipe/mask.py": os.path.join(worktree, "mmdpipe", "mask.py"),
        },
        "lease": False,
        "outputs": [],
        # 下面三项由 mask_preflight_fields() 给出：cap 就是 constraint_limit() 的返回值
        **fields,
        "_derivation": {
            "already_blocked": already,
            "to_add": to_add,
            "needed_pairs": needed,
            "numbers_source": source,
            "code_from": stage.__file__,
            "cap_from": "stage.constraint_limit(%d) -> (%d, guardrail_hit=%s)"
                        % (needed, limit, guardrail),
            "DEFAULT_MAX_CONSTRAINTS": stage.mask_mod.DEFAULT_MAX_CONSTRAINTS,
            "note": "cap 不是手写的：上限由建场同一函数算出；needs/already 来自显式来源",
        },
    }
    out = args.out or os.path.join(worktree, "out", "subai", "M00",
                                   "preflight_delivery_spec.json")
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(spec, fh, ensure_ascii=False, indent=2)
    print(json.dumps(spec, ensure_ascii=False, indent=2))
    print("\nwrote:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
