"""预检命令行 —— 不启动 Blender。

    python -m mmdpipe.preflight 模型.pmx
    python -m mmdpipe.preflight 模型.pmx 动作.vmd --json report.json

回答三个问题：这个模型有没有物理、掩码语义对不对、这个动作套得上去吗。
"""
from __future__ import annotations

import argparse
import sys

from . import match as match_mod
from . import physics as physics_mod
from . import pmx as pmx_mod
from . import preset as preset_mod
from . import vmd as vmd_mod


def preflight(pmx_path: str, vmd_path: str | None = None,
              preset_path: str | None = None, verbose: bool = True) -> dict:
    preset = preset_mod.load(preset_path)
    model = pmx_mod.load(pmx_path)
    cen = pmx_mod.census(model)
    out: dict = {"pmx_census": cen, "preset_import_scale": preset["import"]["scale"]}

    if verbose:
        print("PMX  %s" % model.name)
        print("  PMX %.1f | 编码 %s | 附加UV %d | 顶点 %d | 骨 %d | 材质 %d | 表情 %d"
              % (model.version, model.encoding, model.additional_uvs,
                 cen["vertices"], cen["bones"], cen["materials"], cen["morphs"]))
        print("  刚体 %d | 关节 %d | mode 分布 %s | 碰撞组 %s"
              % (cen["rigids"], cen["joints"], cen["mode_distribution"], cen["group_distribution"]))
        print("  掩码：同组自撞 bit=1 碰撞 %d 对 / bit=1 忽略 %d 对  → 判定：%s"
              % (cen["same_group_pairs_bitset"], cen["same_group_pairs_inverted"],
                 cen["resolved_semantics"]))
        print("  被关节引用刚体 %d | 伪冻结嫌疑 %d"
              % (cen["joint_referenced_rigids"], len(cen["frozen_suspects"])))
        if cen["tail_error"]:
            print("  !! 尾段解析失败（刚体/关节数据不可信）：%s" % cen["tail_error"])
        if cen["bytes_consumed"] != cen["bytes_total"]:
            print("  !! 解析未对齐：读了 %d / 共 %d 字节"
                  % (cen["bytes_consumed"], cen["bytes_total"]))

    phys = physics_mod.classify(model)
    out["physics"] = phys.as_dict()
    if verbose:
        print()
        print(physics_mod.render_text(phys))

    if vmd_path:
        motion = vmd_mod.load(vmd_path)
        rep = match_mod.build(model, motion)
        out["match"] = rep.as_dict()
        if verbose:
            print()
            print(match_mod.render_text(rep))

    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mmdpipe.preflight")
    ap.add_argument("pmx")
    ap.add_argument("vmd", nargs="?")
    ap.add_argument("--preset")
    ap.add_argument("--json")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    try:
        out = preflight(args.pmx, args.vmd, args.preset, verbose=not args.quiet)
    except (pmx_mod.PMXError, vmd_mod.VMDError, OSError) as exc:
        print("预检失败：%s" % exc, file=sys.stderr)
        return 1

    if args.json:
        from .report import dump
        dump(out, args.json)
        if not args.quiet:
            print("\n报告已写入 %s" % args.json)

    verdict = out.get("match", {}).get("verdict", "pass")
    return {"pass": 0, "warn": 0, "block": 2}.get(verdict, 0)


if __name__ == "__main__":
    raise SystemExit(main())
