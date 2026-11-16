# -*- coding: utf-8 -*-
"""生成 C@W1 / C@W2 / D 三臂的 `coordination.preflight` 请求（M04）。

**`cap` 不许手写**：由 `stage.constraint_limit()` 现算，与建场用的是同一个函数；`needs` 取
`apply_collision_masks()` 那套读数（`mask_preflight_fields()` 给）。本脚本只读已记录的读数
（`reports/subai/M00/evidence_m00_attempt10.json` + `result_attempt11.md`），不在这里手写 1813 / 8298。

跑法（在哪个树里跑就传哪个树；C/D 由我在 A2 跑）：

    python reports/subai/M04/scripts/m04_preflight_spec.py --worktree E:\\code\\mmdpipe-ai\\A2
    python -m coordination.preflight --spec <out>/subai/M04/preflight_cd_spec.json --worktree .

技术要点（与 4号 的 M00 生成器同法）：`stage.py` 顶层 `import bpy`，本次只调纯函数，
给 `bpy` / `mathutils` 两个空壳就够——**不开 Blender、不占锁**。
`--worktree` 会插到 `sys.path[0]`，所以 `constraint_limit()` 来自那棵树，不是安装版。
"""
import argparse
import json
import os
import re
import sys
import types

DEFAULT_WORKTREE = r"E:\code\mmdpipe-ai\A2"


def _parse(argv):
    ap = argparse.ArgumentParser(description="生成 C/D 三臂的 preflight 请求")
    ap.add_argument("--worktree", default=DEFAULT_WORKTREE)
    ap.add_argument("--out", default=None, help="输出 JSON（默认 <worktree>/out/subai/M04/）")
    return ap.parse_args(argv)


def recorded_numbers(worktree):
    """只读已记录的读数：不手写。缺文件就停，不许猜。"""
    ev = os.path.join(worktree, "reports", "subai", "M00", "evidence_m00_attempt10.json")
    rp = os.path.join(worktree, "reports", "subai", "M00", "result_attempt11.md")
    for p in (ev, rp):
        if not os.path.exists(p):
            raise SystemExit("缺已记录读数：%s" % p)
    with open(ev, "r", encoding="utf-8") as fh:
        evidence = json.load(fh)
    already = evidence["measurements"]["delivery_scene_before"]["blocked_and_should_not_collide"]
    with open(rp, "r", encoding="utf-8") as fh:
        text = fh.read()
    match = re.search(r"交付场景要补\s*(\d+)\s*条", text)
    if match is None:
        raise SystemExit("报告里找不到「交付场景要补 N 条」——别在这儿手写数字")
    return int(already), int(match.group(1))


def main(argv=None):
    args = _parse(argv)
    worktree = os.path.abspath(args.worktree)
    sys.path.insert(0, worktree)
    sys.modules.setdefault("bpy", types.ModuleType("bpy"))
    _mathutils = types.ModuleType("mathutils")
    _mathutils.Vector = object
    sys.modules.setdefault("mathutils", _mathutils)

    from mmdpipe import stage                      # noqa: E402

    already, to_add = recorded_numbers(worktree)
    needed = already + to_add
    fields = stage.mask_preflight_fields({
        "constraints_needed": needed,
        "constraints_already_blocked": already,
        "constraints_to_add": to_add,
        "skipped_count": 0,
    })
    limit, guardrail = stage.constraint_limit(needed)

    spec = {
        "task_id": "M04_CD_measure",
        "worktree": worktree,
        "provenance": {
            "mmdpipe/stage.py": os.path.join(worktree, "mmdpipe", "stage.py"),
            "mmdpipe/mask.py": os.path.join(worktree, "mmdpipe", "mask.py"),
        },
        # 租约这条不在生成时判：真跑前套锁、开跑前 `coordination.lock` 会说清楚。
        # 这里给 False 是**声明「本次前置检查只验其余四项」**，不是假装有锁。
        "lease": False,
        # 三臂的产物路径：`_check_outputs` 会拦「目标已存在且没 run_id/overwrite」的旧产物。
        "outputs": [
            "out/subai/M04/penetration/C_W1.meta.json",
            "out/subai/M04/penetration/C_W2.meta.json",
            "out/subai/M04/penetration/D.meta.json",
        ],
        **fields,
        "_derivation": {
            "already_blocked": already,
            "to_add": to_add,
            "needed_pairs": needed,
            "code_from": stage.__file__,
            "cap_from": "stage.constraint_limit(%d) -> (%d, guardrail_hit=%s)"
                        % (needed, limit, guardrail),
            "DEFAULT_MAX_CONSTRAINTS": stage.mask_mod.DEFAULT_MAX_CONSTRAINTS,
            "note": "cap 不是手写的；needs/cap 由 mask_preflight_fields() 给出",
        },
    }
    out = args.out or os.path.join(worktree, "out", "subai", "M04", "preflight_cd_spec.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(spec, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    print("written %s" % out)
    print("needs=%s cap=%s skipped=%s  (%s)"
          % (spec.get("needs"), spec.get("cap"), spec.get("skipped"), spec["_derivation"]["cap_from"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
