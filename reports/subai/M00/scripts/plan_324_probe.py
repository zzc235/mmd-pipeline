# -*- coding: utf-8 -*-
"""在真 Blender 上跑一次 `mask.plans()`：给出 324 刚体口径的 `constraints_*` 三件套。

1号 18:17 要的那份产物（他的重建窗口要靠它给 `needs_planned / cap`，不许手写）。
**只读**：不写位、不建约束、不存 .blend——只调 `plans()` 与 `disabled_pairs()`。

    blender -b --factory-startup --python-exit-code 3 --python plan_324_probe.py -- \
        --blend <324 刚体场景.blend> --out <产物.json>

三件套的定义照 `stage.apply_collision_masks()` 的算法，不另立一套：

* `constraints_needed` = `plans()["constraints_needed"]` 的对数（PMX 语义下必须靠约束分开的总对数）；
* `constraints_already_blocked` = 其中**场景里已经挡对**的那些（`disabled_pairs()` 命中数）；
* `constraints_to_add` = 前两者之差。

`needed` 只取决于刚体的组号/掩码（拓扑），`already` 取决于场景里已有的约束（场景状态）——
报告里这两个数要各自标源，不能拼成一句话。
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))))         # .../out/subai/M00/scripts -> worktree 根
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bpy                                                  # noqa: E402
from mmdpipe import mask as mask_mod                        # noqa: E402
from mmdpipe import stage                                   # noqa: E402


def _args() -> dict:
    argv = sys.argv
    if "--" not in argv:
        raise SystemExit("参数要写在 `--` 之后")
    items = argv[argv.index("--") + 1:]
    if len(items) % 2:
        raise SystemExit("参数必须成对：%r" % (items,))
    return {items[n][2:]: items[n + 1] for n in range(0, len(items), 2)}


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git(tree: str) -> dict:
    """在哪棵树量的：分支、HEAD、是否干净（总控 18:18 要的 `tree`/`repo`）。"""
    import subprocess

    def run(*args):
        try:
            proc = subprocess.run(["git", "-C", tree] + list(args), capture_output=True,
                                  timeout=30)
            return proc.stdout.decode("utf-8", "replace").strip()
        except Exception as exc:                    # 没装 git / 不是仓库：如实记，不猜
            return "ERROR:%s" % type(exc).__name__

    return {"path": tree,
            "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
            "head": run("rev-parse", "HEAD"),
            "dirty": bool(run("status", "--porcelain")),
            "common_dir": run("rev-parse", "--git-common-dir")}


def plan_fields(plan: dict, bodies, already) -> dict:
    """把 `mask.plans()` 的输出折成三件套 + 上下文（纯函数，离屏可测）。

    **键名与类型都照 `plans()` 实际返回**：`asymmetric_pairs` 是**整数**（明细在
    `asymmetric_examples` 里）,第一版我按 list 处理 ⇒ 真跑时 `TypeError` 白占一次窗口。
    """
    needed_pairs = [mask_mod.pair_key(a, b) for a, b in plan["constraints_needed"]]
    already_needed = sum(1 for pair in needed_pairs if pair in already)
    needed = len(needed_pairs)
    out = {
        "rigids": len(bodies),
        "constraints_needed": needed,
        "constraints_already_blocked": already_needed,
        "constraints_to_add": needed - already_needed,
        "disabled_pairs_in_scene": len(already),
        "release_pairs": len(plan.get("release_pairs") or []),
        "unexpressible": len(plan.get("unexpressible") or []),
        "skipped_count": len(plan.get("skipped") or []),
        "pairs_total": len(bodies) * (len(bodies) - 1) // 2,
        # `groups_seen` / `mask_histogram` 是上下文；读的时候对不上键就会静默成空，所以单列
        "groups_seen": plan.get("groups_seen"),
        "mask_histogram": {str(k): v for k, v in (plan.get("mask_histogram") or {}).items()},
        "asymmetric_pairs": plan.get("asymmetric_pairs"),
        "asymmetric_examples": len(plan.get("asymmetric_examples") or []),
    }
    for key in ("pmx_collide", "pmx_nocollide", "separated_by_bits", "blocked_before"):
        out[key] = plan.get(key)
    return out


def expectations_of(res: dict) -> dict:
    needed = res["constraints_needed"]
    return {
        "rigids_positive": res["rigids"] > 0,
        "needed_ge_to_add": needed >= res["constraints_to_add"],
        "to_add_consistent": res["constraints_to_add"] >= 0,
        "identity_holds": needed == (res["constraints_already_blocked"]
                                     + res["constraints_to_add"]),
        "nothing_unexpressible": res["unexpressible"] == 0,
        # 上下文不能静默为空：有刚体就必须有组分布，否则这份产物说不清「量的是什么」
        "groups_seen_not_empty": bool(res["rigids"] == 0 or res["groups_seen"]),
    }


def probe(blend: str) -> dict:
    res = {"blend": os.path.abspath(blend), "blender": bpy.app.version_string,
           "truth_tier": "T3", "tree": HERE, "repo": _git(HERE)}
    res["blend_sha256"] = _sha256_file(blend)
    res["bench_blend_sha256"] = res["blend_sha256"]        # 同一个值，两个键名都留着
    bpy.ops.wm.open_mainfile(filepath=blend)
    res["scene"] = bpy.context.scene.name
    # fps 一并记：`D-192` 定了 import_vmd 会把 24 改成 30，跨 dt 比较不成立；
    # plan() 的数与 fps 无关，但读的人要能据此判断这份 blend 属于哪个 dt。
    res["fps"] = int(getattr(bpy.context.scene.render, "fps", 0) or 0)

    # `mmd_rigid` 是 mmd_tools 注册的属性组：不启用插件，`getattr(obj, "mmd_rigid")`
    # 恒为 None ⇒ `collision_scope()` 会静默给 0 个刚体（18:20 第一次跑就这么空转的）。
    # 所以先按生产路径启用插件，再用它自己的判据确认「真的可用了」。
    res["addons"] = dict(stage.ensure_addons(names=("mmd_tools",)))
    res["mmd_rigid_objects"] = sum(1 for o in bpy.data.objects
                                   if getattr(o, "mmd_rigid", None) is not None)
    if not res["addons"].get("mmd_tools"):
        res["failed"] = ["mmd_tools_not_ready"]
        res["ok"] = False
        return res

    bodies, outside = stage.collision_scope()
    already = mask_mod.disabled_pairs(bpy.data.objects)
    plan = mask_mod.plans(bodies, blocked=already)

    res["rigids_u324"] = sum(1 for o in bpy.data.objects
                             if getattr(o, "rigid_body", None) is not None)
    res["exception_bodies"] = stage.exception_rows(bodies, outside)
    res.update(plan_fields(plan, bodies, already))
    res["rigids_verified_by"] = (
        "U323 = stage.collision_scope() 逐对象 mmd_type=='RIGID_BODY'（本产物 %d 个）；"
        "U324 = rigid_body is not None（%d 个）；两者差集逐条落 exception_bodies（%d 条）"
        % (res["rigids"], res["rigids_u324"], len(res["exception_bodies"] or [])))

    needed = res["constraints_needed"]
    limit, guardrail = stage.constraint_limit(needed)
    res["cap"] = limit
    res["guardrail_hit"] = bool(guardrail)
    res["cap_fits"] = limit >= res["constraints_to_add"]
    res["DEFAULT_MAX_CONSTRAINTS"] = getattr(mask_mod, "DEFAULT_MAX_CONSTRAINTS", None)

    # 代码身份：函数级 + 文件级都给，读的人能自己核对用的是哪份实现
    res["function_sha256"] = _sha256_text(inspect.getsource(stage.constraint_limit))
    res["functions"] = {
        "stage.constraint_limit": _sha256_text(inspect.getsource(stage.constraint_limit)),
        "mask.plans": _sha256_text(inspect.getsource(mask_mod.plans)),
        "mask.disabled_pairs": _sha256_text(inspect.getsource(mask_mod.disabled_pairs)),
    }
    res["files"] = {
        "mmdpipe/stage.py": {"path": stage.__file__, "sha256": _sha256_file(stage.__file__)},
        "mmdpipe/mask.py": {"path": mask_mod.__file__,
                            "sha256": _sha256_file(mask_mod.__file__)},
    }
    res["expectations"] = expectations_of(res)
    res["failed"] = [k for k, v in res["expectations"].items() if not v]
    res["ok"] = not res["failed"]
    return res


def main() -> int:
    opts = _args()
    blend = opts.get("blend") or ""
    out_path = opts.get("out") or ""
    if not blend or not out_path:
        raise SystemExit("缺参数：--blend / --out")
    payload = {"ok": False}
    code = 0
    try:
        payload = probe(blend)
        code = 0 if payload.get("ok") else 3
    except Exception:
        payload = {"ok": False, "failed": ["exception"], "traceback": traceback.format_exc()}
        code = 3
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
