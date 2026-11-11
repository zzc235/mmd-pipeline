"""阶段编排 + 状态落盘。

用法（在 Blender 里跑）：
    blender -b -P runner.py -- --pmx 模型.pmx --vmd 动作.vmd --out 输出目录 [--frames 360] [--probe] [--force]

设计取舍：只做「稳定复现」。
  * 每阶段跑完立刻写 pipeline_state.json（崩了也留证据）
  * 任一 BLOCK 立即停，不带着错误往下渲
  * 指纹 = pmx hash + vmd hash + preset hash，用来判断"这是不是同一件事"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time

import bpy

from . import clearance as clearance_mod
from . import chainplan as chainplan_mod
from . import concatvmd as concatvmd_mod
from . import layout as layout_mod
from . import match as match_mod
from . import mergevmd as mergevmd_mod
from . import physics as physics_mod
from . import pmx as pmx_mod
from . import preset as preset_mod
from . import report as report_mod
from . import stage as stage_mod
from . import statefile as statefile_mod
from . import verify_pmx as verify_mod
from . import vmd as vmd_mod


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(pmx_path: str, vmd_path: str, preset: dict) -> dict:
    return {
        "pmx": {"path": pmx_path, "sha256": _sha256(pmx_path),
                "size": os.path.getsize(pmx_path)},
        "vmd": {"path": vmd_path, "sha256": _sha256(vmd_path),
                "size": os.path.getsize(vmd_path)},
        "preset_sha256": hashlib.sha256(
            json.dumps(preset, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
    }


def _write_state(path: str, state: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)


def _copy_textures(src_pmx: str, dst_pmx: str, textures) -> tuple:
    """把 PMX 引用的贴图按相对路径复制到 dst 所在目录。返回 (复制数, 缺失列表)。"""
    src_dir = os.path.dirname(os.path.abspath(src_pmx))
    dst_dir = os.path.dirname(os.path.abspath(dst_pmx))
    copied, missing = 0, []
    for name in textures:
        if not name:
            continue
        rel = name.replace("\\", "/").lstrip("/")
        src = os.path.join(src_dir, rel)
        dst = os.path.join(dst_dir, rel)
        if not os.path.exists(src):
            missing.append(name)
            continue
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(src):
            shutil.copy2(src, dst)
            copied += 1
    return copied, missing


def _parse_args(argv):
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    ap = argparse.ArgumentParser(prog="mmdpipe.runner")
    # 参数声明唯一来源：mmdpipe.params.PARAMS
    # 面板和 CLI 都从它生成，不要再往这里手写 add_argument。
    from . import params as params_mod
    params_mod.add_arguments(ap)
    return ap.parse_args(argv)


def _guard_state(path: str) -> bool:
    """开工前处理已存在的 state。

    三种情况，三种动作：
      * 能迁移（schema 2）→ 提示一句，继续（跑完覆盖成当前 schema）
      * 旧到读不懂（无 schema / <2）→ **改名归档**，不覆盖唯一的历史记录
      * 比插件新（> 当前）→ 拒绝运行：新字段什么意思不知道，覆盖等于销毁证据
    """
    if not os.path.exists(path):
        return True
    try:
        _, notes = statefile_mod.load_compatible(path)
    except statefile_mod.StateIncompatible as exc:
        if exc.newer:
            print("拒绝运行：%s" % exc)
            print("  → %s" % (exc.hint or "升级插件，或换一个 --out 目录"))
            return False
        try:
            old_schema = statefile_mod.schema_of(statefile_mod.read(path))
        except (OSError, ValueError):
            old_schema = "bad"
        bak = "%s.schema%s.bak" % (path, old_schema)
        os.replace(path, bak)
        print("旧 state 无法按当前语义读取，已归档为 %s" % bak)
        print("  → %s" % (exc.hint or "它只能由旧版工具读取"))
        return True
    for note in notes:
        print(note)
    return True


def run(args) -> int:
    if not args.vmd and not args.motions:
        print('需要 --vmd 或 --motions')
        return 1
    if not args.vmd:
        args.vmd = [p for p in args.motions.split(';') if p][0]
    preset = preset_mod.load(args.preset)
    if getattr(args, "fps", None):
        preset["render"]["fps"] = int(args.fps)
    if args.physics_policy:
        preset["physics"]["policy"] = args.physics_policy
    if args.clearance:
        preset["clearance"]["enabled"] = True
    if args.clearance_margin is not None:
        preset["clearance"]["margin"] = args.clearance_margin
    if args.force_static:
        preset["physics"]["force_static"] = args.force_static
    if args.prop:
        specs = []
        for item in args.prop:
            path, _, bone = item.rpartition("@")
            if not path:
                path, bone = item, "手首.R"
            specs.append({"pmx": path, "bone": bone})
        preset["props"] = specs
    if args.expression:
        preset["motion"]["expression"] = args.expression
    if args.force_physics:
        preset["physics"]["force_physics"] = args.force_physics
    if args.camera and os.path.exists(args.camera):
        with open(args.camera, "r", encoding="utf-8") as fh:
            frozen = json.load(fh)
        preset["camera"]["loc"] = frozen["loc"]
        preset["camera"]["rot"] = frozen["rot"]
        preset["camera"]["lens"] = frozen.get("lens", preset["camera"]["lens"])
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    paths = layout_mod.plan(os.path.abspath(args.out),
                            getattr(args, "layout", layout_mod.DEFAULT_LAYOUT),
                            started_at)
    out_dir = paths["work"]
    png_dir = os.path.join(out_dir, "frames")
    mp4_path = os.path.join(out_dir, "result.mp4")
    scene_path = os.path.join(out_dir, "scene.blend")
    # state 留在 --out 根目录，不跟着 run id 走：
    # 它是"最近一次运行"的记录，也是下次开跑时的兼容性检查点；产物才进 work/。
    state_path = os.path.join(paths["root"], "pipeline_state.json")
    os.makedirs(out_dir, exist_ok=True)
    if not _guard_state(state_path):
        return 4

    frame_start = 1
    frame_end = max(1, args.frames)
    state = {
        # 契约层：schema 变了必须显式迁移或拒绝，否则续跑会静默用错语义
        "schema": statefile_mod.SCHEMA,
        "run_id": paths["run_id"],
        "layout": paths["layout"],
        "paths": {"root": paths["root"], "work": paths["work"],
                  "final": paths["final"]},
        "env": {
            "blender": bpy.app.version_string,
            "mmdpipe": __import__("mmdpipe").__version__,
        },
        "started_at": started_at,
        "input": {"pmx": args.pmx, "vmd": args.vmd},
        "params": {"frame_start": frame_start, "frame_end": frame_end,
                   "fps": preset["render"]["fps"],
                   "resolution": preset["render"]["resolution"]},
        "stages": {},
        "ok": False,
        "blocked_by": [],
    }

    print("=" * 72)
    print("MMD 流水线 · 复现")
    print("  pmx %s" % args.pmx)
    print("  vmd %s" % args.vmd)
    print("  输出 %s" % out_dir)
    print("  %s" % layout_mod.describe(paths))
    print("  帧 %d..%d @ %d fps" % (frame_start, frame_end, preset["render"]["fps"]))
    print("=" * 72, flush=True)

    try:
        state["fingerprint"] = _fingerprint(args.pmx, args.vmd, preset)
        if args.motions:
            state["fingerprint"]["motions"] = [
                {"path": p, "sha256": _sha256(p)}
                for p in [x for x in args.motions.split(";") if x]]
    except OSError as exc:
        print("读不到输入文件：%s" % exc)
        return 1

    # 只读守卫：源 PMX 与 VMD 在整条流程里必须一个字节都不变。
    source_sha_before = {
        "pmx": state["fingerprint"]["pmx"]["sha256"],
        "vmd": state["fingerprint"]["vmd"]["sha256"],
    }
    state["source_readonly"] = True

    def record(result):
        state["stages"][result.stage] = result.as_dict()
        _write_state(state_path, state)
        print(result.text(), flush=True)
        if result.blocked:
            state["blocked_by"].append(result.stage)
        return not result.blocked or args.force

    def source_unchanged(label=""):
        now = {"pmx": _sha256(args.pmx), "vmd": _sha256(args.vmd)}
        changed = [k for k in now if now[k] != source_sha_before[k]]
        if not changed:
            return True
        st = report_mod.StageResult("S0_readonly")
        st.add("E-00", report_mod.BLOCK,
               "源文件在流程中被改动：%s（%s）" % (", ".join(changed), label),
               "所有改动必须落在副本上")
        record(st)
        return False

    # ---------------- S0 / S1：纯 Python 预检与普查
    mute_bones = []
    try:
        model = pmx_mod.load(args.pmx)
    except pmx_mod.PMXError as exc:
        model = None
        s0 = report_mod.StageResult("S0_preflight")
        s0.add("E-00", report_mod.WARN, "PMX 解析失败，交给 mmd_tools 兜底：%s" % exc)
        record(s0)
    if model is not None:
        census = pmx_mod.census(model)
        s1 = report_mod.StageResult("S1_census")
        s1.metrics.update(census)
        if census["rigids"] == 0:
            s1.add("G1", report_mod.BLOCK, "刚体数 0，这个模型没有物理")
        if census["tail_error"]:
            s1.add("E-00", report_mod.WARN,
                   "PMX 尾段解析失败，刚体/关节数据不可信", census["tail_error"])
        if not record(s1):
            state["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _write_state(state_path, state)
            return 2

        # 物理资格判断（纯结构，不看名字）
        phys = physics_mod.classify(model)
        s1p = report_mod.StageResult("S1_physics")
        s1p.metrics.update({
            "accessory": phys.accessory,
            "physics_bodies": phys.counts.get("physics", 0),
            "welded_feedback": phys.counts.get("welded", 0),
            "welded_collider": phys.counts.get("welded_collider", 0),
            "colliders": phys.counts.get("collider", 0),
            "unconstrained": phys.counts.get("free", 0),
            "units": len(phys.units),
            "suspect_units": len(phys.suspect_units),
            "mute_bones_welded": len(phys.mute_bones),
            "mute_bones_suspect": len(phys.suspect_bones),
        })
        if phys.accessory:
            s1p.add("G1", report_mod.WARN,
                    "刚体 0 / 骨 %d：判定为道具，不是角色模型" % phys.bones)
        if phys.suspect_units:
            s1p.add("E-05", report_mod.WARN,
                    "%d 个单元结构僵死（无 mode2 + 焊占比≥40%% + 有闭环），静音与否需看图确认"
                    % len(phys.suspect_units),
                    ", ".join(s["anchor_bone"] for s in phys.suspect_units[:4]))
        if phys.counts.get("free"):
            s1p.add("E-00", report_mod.WARN,
                    "%d 个刚体无关节却是 mode1/2：动态体缺约束，行为可疑"
                    % phys.counts["free"])
        record(s1p)
        mute_bones = physics_mod.bones_for_policy(phys, preset["physics"]["policy"])

        # 过约束动态单元（多刚体 + 有闭环 + 焊接多 + 无 mode2）默认关物理。
        # 实测卡芙卡袖子（25 刚体 / 24 闭环）配 LaLaLand 高速手臂：
        #   原始            → 逐帧转角突变 46.8°，画面甩成硬纸板
        #   只提求解预算    → 37.5°，仍是硬片
        #   只加阻尼        → 38.8°，仍是硬片
        #   静音约束 48 条  → 仍是硬片（刚体还在模拟）
        #   骨级静态        → 干净（刚体不参与解算，袖口跟手臂走）
        suspect_action = preset["physics"].get("suspect_units", "static")
        suspect_bones = []
        if suspect_action == "static":
            for u in getattr(phys, "units", []):
                bodies = getattr(u, "bodies", [])
                modes = getattr(u, "modes", set()) or set()
                if (len(bodies) >= 8 and getattr(u, "cycle_rank", 0) >= 3
                        and getattr(u, "welded_ratio", 0) >= 0.35 and 2 not in modes):
                    suspect_bones.extend(model.bones[b].name for b in
                                         {model.rigids[i].bone for i in bodies})
        if suspect_bones:
            mute_bones = sorted(set(mute_bones) | set(suspect_bones))
            s1p3 = report_mod.StageResult("S1_suspect_static")
            s1p3.metrics["suspect_bones"] = len(set(suspect_bones))
            s1p3.metrics["action"] = suspect_action
            record(s1p3)

        # 显式声明优先于推断：force_static 强制不做物理，force_physics 强制保留
        fs = preset["physics"].get("force_static") or []
        fp = preset["physics"].get("force_physics") or []
        if fs:
            extra = physics_mod.bones_by_pattern(model, fs)
            mute_bones = sorted(set(mute_bones) | set(extra))
        if fp:
            drop = set(physics_mod.bones_by_pattern(model, fp))
            mute_bones = [b for b in mute_bones if b not in drop]
        if fs or fp:
            s1p2 = report_mod.StageResult("S1_declared")
            s1p2.metrics["force_static_patterns"] = fs
            s1p2.metrics["force_physics_patterns"] = fp
            s1p2.metrics["mute_bones_total"] = len(mute_bones)
            record(s1p2)

        # 净空修复（导入前改 PMX）
        pmx_for_import = args.pmx
        if preset["clearance"]["enabled"]:
            plan = clearance_mod.plan_fix(model, margin=preset["clearance"]["margin"])
            sc = report_mod.StageResult("S1_clearance")
            sc.metrics.update({
                "margin_pmx": preset["clearance"]["margin"],
                "moved": plan["moved"],
                "joints_synced": len(plan["joint_pos"]),
                "rounds": plan["rounds"],
                "skipped": len(plan.get("skipped", [])),
                "group_moves": len(plan.get("group_moves", [])),
            })
            for s in plan.get("skipped", []):
                sc.add("E-00", report_mod.WARN,
                       "%s 无法安全外移（%s），保留原样"
                       % (s["name"], s.get("reason", "")), "%s mm" % s.get("depth_mm"))
            if plan["moved"]:
                stem = os.path.splitext(os.path.basename(args.pmx))[0]
                fixed_path = os.path.join(out_dir, "pmx", stem + "_fixH.pmx")
                pmx_mod.patch_save(model, fixed_path,
                                   plan["rigid_pos"], plan["joint_pos"])
                # 贴图必须跟着搬：PMX 里存的是相对路径，PMX 挪了目录图就断，
                # 后果是整片变成纯色（实测过：全紫剪影）。
                copied, missing = _copy_textures(args.pmx, fixed_path, model.textures)
                sc.metrics["textures_copied"] = copied
                if missing:
                    sc.add("E-00", report_mod.WARN,
                           "%d 张贴图在源目录找不到，材质会缺图" % len(missing),
                           ", ".join(missing[:4]))
                fixed = pmx_mod.load(fixed_path)
                vres = verify_mod.verify(pmx_mod.load(args.pmx), fixed, plan)
                sc.metrics["verify"] = "%d/%d" % (vres.passed, vres.total)
                sc.artifacts.append(fixed_path)
                if not vres.ok:
                    sc.add("E-00", report_mod.BLOCK,
                           "净空修复验证未通过（%d/%d）" % (vres.passed, vres.total),
                           "C 失败项见 pipeline_state.json")
                pmx_for_import = fixed_path
                print(vres.text(), flush=True)
            else:
                sc.add("E-00", report_mod.INFO, "无可碰撞侵入，PMX 不改")
            if not record(sc):
                state["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                _write_state(state_path, state)
                return 2
            if not source_unchanged("clearance 之后"):
                state["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                _write_state(state_path, state)
                return 2
        state["import_pmx"] = pmx_for_import

        # 道具挂接参数（在摄像机取景之前生效，让取景把道具算进去）
        if args.prop:
            specs = []
            for item in args.prop:
                path, _, bone = item.rpartition("@")
                if not path:
                    path, bone = item, "手首.R"
                specs.append({"pmx": path, "bone": bone})
            preset["props"] = specs

        # 多动作拼接：几段 VMD 首尾接成一条时间轴
        vmd_for_import = args.vmd
        chain_expr_offset = 0
        if args.motions:
            paths = [p for p in args.motions.split(";") if p]
            if len(paths) >= 2:
                chain_path = os.path.join(out_dir, "vmd", "chain.vmd")
                sr = report_mod.StageResult("S3_chain")
                try:
                    # 先只读体检：骨集差 / 交接姿态差 / 根链位移，不通过不写文件
                    cplan = chainplan_mod.plan(paths, pmx_path=args.pmx,
                                               gap=args.chain_gap,
                                               fps=preset["render"]["fps"])
                    sr.metrics["dryrun"] = {
                        "bone_union": cplan["bone_sets"].get("union"),
                        "bone_common": cplan["bone_sets"].get("common"),
                        "missing_counts": cplan["bone_sets"].get("missing_counts"),
                        "pose_over_threshold": sum(
                            1 for p_ in cplan["pose_diff"] if p_["severity"] != "info"),
                        "max_angle_deg": cplan["pose_diff"][0]["angle_deg"] if cplan["pose_diff"] else 0,
                        # 纯 Python 层没有世界位移；留空，由 measure_align 补
                        "local_root_delta": max(
                            (d["local_pos_delta"] for d in cplan.get("local_root_pos_delta", [])),
                            default=0.0),
                        "roots_per_segment": cplan.get("roots_per_segment"),
                    }
                    if cplan["pose_diff"]:
                        top = cplan["pose_diff"][:3]
                        sr.add("E-00", report_mod.WARN,
                               "交接姿态差未修：%d 根骨超阈值，最大 %s %.1f°"
                               % (sr.metrics["dryrun"]["pose_over_threshold"],
                                  top[0]["bone"], top[0]["angle_deg"]),
                               ", ".join("%s %.0f°" % (t["bone"], t["angle_deg"]) for t in top))
                    sr.metrics["dryrun"]["deg_per_frame"] = cplan.get("deg_per_frame")
                    sr.metrics["dryrun"]["recommended_gap"] = cplan.get("recommended_gap")
                    # 确认门：过渡明显不成立时不再"报一声就放行"。
                    # 判据来自实测——95.9° 压在 6 帧里是 13.7°/帧，肉眼就是一次甩手；
                    # 要么加 gap，要么显式 --force，不能默默渲完。
                    rec_gap = cplan.get("recommended_gap")
                    dpg = cplan.get("deg_per_frame") or 0.0
                    max_ang = cplan["pose_diff"][0]["angle_deg"] if cplan["pose_diff"] else 0.0
                    if rec_gap is not None and args.chain_gap < rec_gap and max_ang > 45:
                        sr.add("E-16", report_mod.BLOCK,
                               "过渡太快：最大骨差 %.1f° 压在 %d 帧里（%.1f°/帧），"
                               "建议 --chain-gap ≥ %d 或 --force 显式放行"
                               % (max_ang, args.chain_gap + 1, dpg, rec_gap))
                    elif rec_gap is not None and args.chain_gap < rec_gap:
                        sr.add("E-00", report_mod.WARN,
                               "过渡偏快：%.1f°/帧，建议 --chain-gap ≥ %d"
                               % (dpg, rec_gap))
                    crep = None
                    if getattr(args, "chain_mode", "splice") == "nla":
                        # NLA 路线（社区/官方能力）：分层 → 交叉淡化 → 烘焙 → export_vmd
                        from . import chain_nla as chain_nla_mod
                        if len(paths) != 2:
                            sr.add("E-00", report_mod.WARN,
                                   "NLA 模式一次只支持 2 段，当前 %d 段" % len(paths))
                        nrep = chain_nla_mod.concat_via_nla(
                            args.pmx, paths[0], paths[1], chain_path,
                            gap=args.chain_gap,
                            blend=getattr(args, "chain_blend", 0),
                            align=getattr(args, "align", "auto"), verbose=False)
                        sr.metrics.update({
                            "mode": "nla",
                            "segments": len(paths),
                            "gap": args.chain_gap,
                            "blend": getattr(args, "chain_blend", 0),
                            "frame_range": nrep["frame_range"],
                            "fcurves": nrep["fcurves"],
                            "align": nrep.get("align"),
                            "out": nrep["out"],
                        })
                        sr.artifacts.append(nrep["out"])
                        vmd_for_import = nrep["out"]
                        sr.metrics["spans"] = [[0, [0, nrep["a_last"] - 1]],
                                               [nrep["b_first"] - 1,
                                                [nrep["b_first"] - 1, nrep["frame_range"][1]]]]
                    else:
                        crep = concatvmd_mod.concat_vmd(
                            paths, chain_path, gap=args.chain_gap, verbose=False)
                        sr.metrics.update({
                            "mode": "splice",
                            "segments": len(paths),
                            "gap": args.chain_gap,
                            "frame_range": crep["final_range"],
                            "bone_records": crep["bone_records"],
                            "spans": [[s_["offset"], s_["dst_range"]] for s_ in crep["spans"]],
                            "out": crep["out"],
                        })
                        sr.artifacts.append(crep["out"])
                    if crep is not None and crep["overlaps"]:
                        sr.add("E-15", report_mod.BLOCK,
                               "拼接后时间轴有重叠段", str(crep["overlaps"]))
                    if crep is not None:
                        vmd_for_import = crep["out"]
                    # 表情属于哪一段：按"表情文件与该段动作同目录"判断
                    if args.expression and crep is not None:
                        expr_dir = os.path.dirname(os.path.abspath(args.expression))
                        for idx, pth in enumerate(paths):
                            if os.path.dirname(os.path.abspath(pth)) == expr_dir:
                                chain_expr_offset = crep["spans"][idx]["offset"]
                                sr.metrics["expression_segment"] = idx
                                break
                except Exception as exc:
                    sr.add("E-15", report_mod.BLOCK, "多动作拼接失败：%s" % exc)
                if not record(sr):
                    state["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    _write_state(state_path, state)
                    return 2
            else:
                vmd_for_import = paths[0]

        if args.expression:
            stem = os.path.splitext(os.path.basename(args.vmd))[0]
            merged_path = os.path.join(out_dir, "vmd", stem + "_merged.vmd")
            sx = report_mod.StageResult("S3_expression")
            try:
                mrep = mergevmd_mod.merge_vmd(vmd_for_import, args.expression, merged_path,
                                              pmx=args.pmx, verbose=False,
                                              offset=chain_expr_offset)
                sx.metrics.update({
                    "bone_tracks": mrep["bone_tracks"], "bone_frames": mrep["bone_frames"],
                    "morph_tracks": mrep["morph_tracks"], "morph_frames": mrep["morph_frames"],
                    "morph_coverage": mrep.get("morph_coverage"),
                    "out": merged_path,
                })
                sx.artifacts.append(merged_path)
                if not mrep["ok_bones"] or not mrep["ok_morphs"]:
                    sx.add("E-15", report_mod.BLOCK, "合并后轨道数与源文件不一致")
                cov = mrep.get("morph_coverage")
                if cov is not None and cov < 0.5:
                    sx.add("E-00", report_mod.WARN,
                           "表情对模型覆盖率只有 %.1f%%，多数表情不会生效" % (cov * 100),
                           ", ".join(mrep.get("morph_miss", [])[:4]))
                vmd_for_import = merged_path
            except (OSError, Exception) as exc:
                sx.add("E-15", report_mod.BLOCK, "表情 VMD 合并失败：%s" % exc)
            if not record(sx):
                state["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                _write_state(state_path, state)
                return 2
        state["import_vmd"] = vmd_for_import

        try:
            motion = vmd_mod.load(vmd_for_import)
            rep = match_mod.build(model, motion)
            s3_pre = report_mod.StageResult("S3_match")
            s3_pre.metrics.update({
                "verdict": rep.verdict,
                "coverage_frames": round(rep.coverage_frames, 4),
                "bone_names": rep.bone_names_total,
                "bone_miss": rep.bone_miss,
                "morph_total": rep.morph_total,
                "morph_miss": rep.morph_miss[:10],
                "ik_gap": rep.ik_gap,
                "frame_range": list(rep.frame_range),
                "additional_uvs": rep.additional_uvs,
            })
            if rep.verdict == "block":
                s3_pre.add("G3", report_mod.BLOCK,
                           "骨骼覆盖率 %.1f%% 太低，动作套不上" % (rep.coverage_frames * 100))
            elif rep.verdict == "warn":
                s3_pre.add("G3", report_mod.WARN,
                           "骨骼覆盖率 %.1f%%，%d 根骨会丢曲线"
                           % (rep.coverage_frames * 100, len(rep.bone_miss)))
            if rep.ik_gap:
                s3_pre.add("E-00", report_mod.WARN, "IK 缺口，脚会滑", ", ".join(rep.ik_gap))
            report_mod.dump({"pmx": census, "match": rep.as_dict()},
                            os.path.join(out_dir, "preflight.json"))
            if not record(s3_pre):
                state["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                _write_state(state_path, state)
                return 2
        except vmd_mod.VMDError as exc:
            s3_pre = report_mod.StageResult("S3_match")
            s3_pre.add("E-15", report_mod.BLOCK, "VMD 解析失败：%s" % exc)
            record(s3_pre)
            return 2

    # ---------------- Blender 侧
    scene = bpy.context.scene
    addons = stage_mod.ensure_addons()
    s_env = report_mod.StageResult("S0_env")
    s_env.metrics["addons"] = addons
    for name, ok in addons.items():
        if not ok:
            s_env.add("E-14", report_mod.BLOCK, "插件加载失败：%s" % name)
    if not record(s_env):
        return 2

    print("removed objects: %d" % stage_mod.reset_scene(), flush=True)

    st, root, arm, mesh = stage_mod.stage_import(preset, pmx_for_import)
    if not record(st):
        state["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _write_state(state_path, state)
        return 2
    if root is None or arm is None or mesh is None:
        return 2

    st = stage_mod.stage_build(preset, root, arm)
    if not record(st):
        state["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _write_state(state_path, state)
        return 2

    # 按物理单元加阻尼：覆盖袖子/头发/挂件这类"名字匹配不到"的过约束单元。
    # 必须在烘焙之前（这里就是），否则改参数不生效。
    if phys is not None:
        try:
            damp = stage_mod.apply_unit_damping(phys, preset)
            st_d = report_mod.StageResult("S2_damping")
            st_d.metrics.update(damp)
            record(st_d)
        except Exception as exc:                    # noqa: BLE001
            st_d = report_mod.StageResult("S2_damping")
            st_d.add("E-00", report_mod.WARN, "按单元加阻尼失败：%s" % exc)
            record(st_d)

    if mute_bones:
        st = stage_mod.stage_physics_policy(arm, mute_bones, preset["physics"]["policy"])
        if not record(st):
            state["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _write_state(state_path, state)
            return 2

    st, action_end = stage_mod.stage_motion(preset, root, arm, vmd_for_import, frame_end)
    if not record(st):
        state["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _write_state(state_path, state)
        return 2
    if action_end is not None and action_end < frame_end:
        s_len = report_mod.StageResult("S3_length")
        s_len.add("G3", report_mod.WARN,
                  "动作只有 %d 帧，短于请求的 %d 帧；按动作长度收尾"
                  % (action_end, frame_end))
        frame_end = max(action_end, 48)
        state["params"]["frame_end"] = frame_end
        record(s_len)

    st = stage_mod.stage_look(preset, mesh, arm)
    if not record(st):
        state["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _write_state(state_path, state)
        return 2

    st_props = stage_mod.stage_props(preset, arm)
    if not record(st_props):
        state["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _write_state(state_path, state)
        return 2

    st, cam = stage_mod.stage_camera(preset, frame_start, frame_end)
    if not record(st):
        state["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _write_state(state_path, state)
        return 2
    if cam is None:
        return 2
    cam_json = {
        "loc": [round(v, 6) for v in cam.location],
        "rot": [round(v, 6) for v in cam.rotation_euler],
        "lens": preset["camera"]["lens"],
        "source": state["stages"]["S6_camera"]["metrics"].get("source"),
    }
    cam_path = os.path.join(out_dir, "camera.json")
    with open(cam_path, "w", encoding="utf-8") as fh:
        json.dump(cam_json, fh, ensure_ascii=False, indent=2)
    state["camera"] = cam_json
    state.setdefault("artifacts", {})["camera"] = cam_path
    _write_state(state_path, state)
    if cam_json["source"] == "measured":
        print("相机已冻结，下次加 --camera %s 可跳过测量" % cam_path, flush=True)

    # 自包含：贴图打进货 .blend，换目录/换机器不丢（skill 模块 1 · 六）
    try:
        bpy.ops.file.pack_all()
        state["packed"] = True
    except Exception as exc:
        state["packed"] = False
        print("pack_all 跳过：%s" % exc, flush=True)

    bpy.ops.wm.save_as_mainfile(filepath=scene_path, compress=True)
    state["artifacts"] = {"scene": scene_path}
    _write_state(state_path, state)
    print("scene saved: %s" % scene_path, flush=True)

    # 渲前重新加载落盘产物：阶段隔离，保证渲的是文件而不是内存态。
    # 注意（实测）：这并不能消除残余抖动——两次纯步进不渲染、第 360 帧仍差 0.51/255，
    # 而第 180 帧两次完全相同。分叉来自 Blender 刚体求解器跨进程非位级一致，
    # 会随帧数累积放大，不是流程问题。
    bpy.ops.wm.open_mainfile(filepath=scene_path)
    state["reloaded_before_render"] = True
    _write_state(state_path, state)
    print("reloaded for render: %s" % scene_path, flush=True)

    st = stage_mod.stage_render(preset, png_dir, frame_start, frame_end, mp4_path)
    record(st)
    state.setdefault("artifacts", {})["frames_dir"] = png_dir
    state["artifacts"]["mp4"] = mp4_path
    _write_state(state_path, state)

    if args.probe:
        record(stage_mod.stage_probe(preset, frame_start))

    st_v = stage_mod.stage_verify(preset, png_dir, mp4_path, frame_start, frame_end)
    record(st_v)

    state["ok"] = not state["blocked_by"]
    state["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    source_unchanged("流程结束")

    # 成片落地：只有全流程 ok 才进 final/。没通过时 final/ 里一个文件都不该出现，
    # 免得"看着有 mp4 就当成了成品"。
    landed = []
    if state["ok"] and paths["final"]:
        landed = layout_mod.promote(out_dir, paths["final"])
        shutil.copy2(state_path, os.path.join(paths["final"], "pipeline_state.json"))
        landed.append("pipeline_state.json")
        state["final"] = {"dir": paths["final"], "files": landed}
    _write_state(state_path, state)

    print()
    print("=" * 72)
    print("结果：%s" % ("通过" if state["ok"] else "未通过"))
    if state["blocked_by"]:
        print("卡在：%s" % ", ".join(state["blocked_by"]))
    if landed:
        print("成片 %s" % os.path.join(paths["final"], "result.mp4"))
        print("落地 %s" % paths["final"])
    else:
        print("成片 %s" % mp4_path)
        if paths["final"]:
            print("未通过，未落地到 final/（产物留在 work/ 可复查）")
    print("状态 %s" % state_path)
    print("=" * 72, flush=True)
    return 0 if state["ok"] else 3


def main() -> int:
    args = _parse_args(sys.argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
