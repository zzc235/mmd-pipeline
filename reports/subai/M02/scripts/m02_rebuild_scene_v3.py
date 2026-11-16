"""M02 · 「今天的代码能不能重建交付场景」v3：从 PMX 产一次最小场景（含算子注册断言）。

    blender -b -P m02_rebuild_scene_v3.py -- <preset.json> <model.pmx> <out_dir> [--build] [--patch <patch.json>]

与 v1/v2 的差别：
- **v1** 直接 `json.load(preset)` → `stage_import` 取 `preset["import"]` KeyError（预设是差分文件）。从未执行。
- **v2** 改用 `preset.load()`，但 `stage.ensure_addons()` 只报 `True` 就当成功，实际
  `bpy.ops.mmd_tools.import_model` **不存在**（本机扩展已装未启用、`opencc` 车轮未解包），
  结果是 `rigids=0` 的安静失败。
- **v3** 先按扩展模块名启用并**断言算子存在**（`hasattr(bpy.ops.mmd_tools, "import_model")`），
  拿不到就写 `NOT_MEASURED` 并退 3，不产出「0 刚体」的假结果。
- **v3.1**（总控 18:08 §二 选 A）加 `--patch`：把「PMX 没有的 12 个刚体」作为**具名步骤**
  `apply_input_patch` 装回去，装完在同一处回读验回来；补丁不合法就**不建场景**（退 4），
  绝不静默少 12 条（那正是 312 那个坑）。

回答的数：刚体总数 / `$name_j` 命中数 / `constraints_needed` / 补丁回读差异。
"""
import hashlib
import json
import os
import sys

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
_TREE = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
if _TREE not in sys.path:
    sys.path.insert(0, _TREE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from mmdpipe import preset as preset_mod  # noqa: E402
from mmdpipe import stage  # noqa: E402
import m02_patch_format as pf  # noqa: E402
import m02_patch_bpy as pb  # noqa: E402

MMD_CANDIDATES = ("bl_ext.user_default.mmd_tools", "mmd_tools")
NOT_MEASURED = 3
PATCH_REFUSED = 4


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def enable_mmd_tools():
    import addon_utils
    trace = []
    for name in MMD_CANDIDATES:
        try:
            addon_utils.enable(name, default_set=False, persistent=False)
            trace.append({"name": name, "error": None})
        except Exception as exc:  # noqa: BLE001
            trace.append({"name": name, "error": "%s: %s" % (type(exc).__name__, exc)})
        if hasattr(bpy.ops.mmd_tools, "import_model"):
            trace.append({"operator_present": True, "via": name})
            return True, trace
        trace.append({"operator_present": False, "after": name})
    return False, trace


def issues_of(res):
    return [str(i) for i in (getattr(res, "issues", []) or [])]


def apply_input_patch(patch_path, arm):
    """具名步骤：读补丁 → 校验 → 逐条造 → 逐条回读验回来。返回可写进报告的记录。

    任何一条装不上或回读不一致都抛异常（调用方写报告并以非 0 退出），不返回「差不多」。
    """
    patch, by_name, warnings = pf.load(patch_path)
    rec = {"step": "apply_input_patch", "patch": os.path.abspath(patch_path),
           "patch_file_sha256": sha256_file(patch_path),
           "patch_sha256": patch["patch_sha256"],
           "patch_version": patch["patch_version"],
           "source": {"blend": patch["source"]["blend"],
                      "blend_sha256": patch["source"]["blend_sha256"],
                      "extractor": patch["source"]["extractor"],
                      "rigids_total": patch["source"]["rigids_total"]},
           "warnings": warnings, "bodies": [], "created": [],
           "strict_mismatch": {}, "soft_mismatch": {}}
    # 来源件若在盘上，重算 sha 并与补丁里记的比；不在盘上就如实记「未复验」
    src_blend = patch["source"]["blend"]
    if os.path.isfile(src_blend):
        got = sha256_file(src_blend)
        rec["source"]["reverified"] = (got == patch["source"]["blend_sha256"])
        rec["source"]["reverified_sha256"] = got
        if not rec["source"]["reverified"]:
            raise pb.PatchApplyError("PATCH_SOURCE_SHA_MISMATCH",
                                     "补丁记录的来源 sha 与盘上文件不一致：记 %s，实测 %s"
                                     % (patch["source"]["blend_sha256"], got))
    else:
        rec["source"]["reverified"] = None
        rec["source"]["reverified_note"] = "来源件不在盘上，只复验补丁自身 sha（不假装验过来源）"

    rec["rigidbody_world_before"] = pb.rigidbody_world_snapshot()
    for spec in patch["bodies"]:
        obj = pb.create_body_from_spec(spec, arm_obj=arm)
        actual = pb.body_spec(obj)
        strict, soft = pf.split_diff(spec, actual)
        rec["bodies"].append(spec["name"])
        rec["created"].append(obj.name)
        if strict:
            rec["strict_mismatch"][spec["name"]] = strict
        if soft:
            rec["soft_mismatch"][spec["name"]] = soft
    rec["rigidbody_world_after"] = pb.rigidbody_world_snapshot()
    rec["count_created"] = len(rec["created"])
    rec["count_expected"] = len(patch["bodies"])
    if rec["count_created"] != rec["count_expected"]:
        raise pb.PatchApplyError("PATCH_COUNT_MISMATCH",
                                 "应装 %d 条，实际装上 %d 条"
                                 % (rec["count_expected"], rec["count_created"]))
    if rec["strict_mismatch"]:
        raise pb.PatchApplyError("PATCH_READBACK_MISMATCH",
                                 "装上了但回读对不上（硬字段）：%s"
                                 % json.dumps(rec["strict_mismatch"], ensure_ascii=False)[:800])
    return rec


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    do_build = "--build" in argv
    patch_path = None
    if "--patch" in argv:
        idx = argv.index("--patch")
        if idx + 1 >= len(argv):
            raise SystemExit("--patch 后面要给补丁路径")
        patch_path = argv[idx + 1]
        argv = argv[:idx] + argv[idx + 2:]
    argv = [a for a in argv if not a.startswith("--")]
    if len(argv) < 3:
        raise SystemExit("usage: m02_rebuild_scene_v3.py -- preset.json model.pmx out_dir "
                         "[--build] [--patch patch.json]")
    preset_path, pmx_path, out_dir = argv[0], argv[1], argv[2]
    os.makedirs(out_dir, exist_ok=True)

    preset = preset_mod.load(preset_path)
    ok, trace = enable_mmd_tools()
    report = {"stage": "rebuild-v3.1", "preset": preset_path, "pmx": pmx_path,
              "pmx_sha256": sha256_file(pmx_path), "build_physics": do_build,
              "operator_available": ok, "addon_trace": trace,
              "preset_has_import": "import" in preset, "import_cfg": preset.get("import"),
              "objects_reset": stage.reset_scene(),
              "input_patch_requested": patch_path}
    if not ok:
        report["status"] = "NOT_MEASURED"
        report["reason"] = ("mmd_tools 的 import_model 算子在本会话里注册不上；"
                            "不产出「0 刚体」的假结果")
        with open(os.path.join(out_dir, "rebuild_report.json"), "w", encoding="utf-8",
                  newline="\n") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
        print("REBUILD NOT_MEASURED operator_available=False")
        sys.stdout.flush()
        os._exit(NOT_MEASURED)

    res, root, arm, mesh = stage.stage_import(preset, pmx_path)
    report["import"] = {"ok": root is not None and arm is not None,
                        "root": getattr(root, "name", None),
                        "armature": getattr(arm, "name", None),
                        "issues": issues_of(res),
                        "metrics": dict(getattr(res, "metrics", {}))}

    def rigid_report():
        rigids = [o for o in bpy.data.objects if getattr(o, "rigid_body", None) is not None]
        names = sorted(o.name for o in rigids)
        bones_of = {}
        for o in rigids:
            mr = getattr(o, "mmd_rigid", None)
            bones_of[o.name] = mr.bone if mr is not None else None
        return {"rigid_count": len(rigids),
                "placeholder_count": sum(1 for n in names if "$name_j" in n),
                "placeholder_names": [n for n in names if "$name_j" in n][:20],
                "xia_bai_11_bodies": sorted(b for b in bones_of.values()
                                            if b and b.startswith("下擺_11_")),
                "xia_bai_0_count": sum(1 for b in bones_of.values()
                                       if b and b.startswith("下擺_0_")),
                "sample_names": names[:8]}

    def write_report(status, reason_code=None, reason=None):
        report["status"] = status
        if reason_code:
            report["reason_code"] = reason_code
        if reason:
            report["reason"] = reason
        with open(os.path.join(out_dir, "rebuild_report.json"), "w", encoding="utf-8",
                  newline="\n") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")

    if patch_path:
        try:
            report["input_patch"] = apply_input_patch(patch_path, arm)
        except (pb.PatchApplyError, pf.PatchError) as exc:
            report["input_patch_error"] = {
                "reason_code": getattr(exc, "reason_code", "PATCH_ERROR"),
                "message": getattr(exc, "message", str(exc)),
                "problems": getattr(exc, "problems", [])}
            write_report("PATCH_REFUSED", getattr(exc, "reason_code", "PATCH_ERROR"),
                         getattr(exc, "message", str(exc)))
            print("REBUILD PATCH_REFUSED %s" % (getattr(exc, "reason_code", "PATCH_ERROR")))
            sys.stdout.flush()
            os._exit(PATCH_REFUSED)               # 补丁没真装上就不建场景
    else:
        report["input_patch_warning"] = patch_present_warning()

    dump1 = os.path.join(out_dir, "rebuild_import.blend")
    bpy.ops.wm.save_as_mainfile(filepath=dump1)
    report["import_blend"] = {"path": dump1, "sha256": sha256_file(dump1),
                              "rigids": rigid_report()}

    if do_build and arm is not None and root is not None:
        res2 = stage.stage_build(preset, root, arm)
        report["build"] = {"issues": issues_of(res2),
                           "metrics": dict(getattr(res2, "metrics", {}))}
        dump2 = os.path.join(out_dir, "rebuild_built.blend")
        bpy.ops.wm.save_as_mainfile(filepath=dump2)
        report["built_blend"] = {"path": dump2, "sha256": sha256_file(dump2),
                                 "rigids": rigid_report()}
    report["status"] = "MEASURED"

    write_report(report["status"])
    print("REBUILD rigids=%d placeholder=%d built=%s patch=%s"
          % (report["import_blend"]["rigids"]["rigid_count"],
             report["import_blend"]["rigids"]["placeholder_count"], do_build,
             (report.get("input_patch") or {}).get("patch_sha256")))
    sys.stdout.flush()
    os._exit(0)


def patch_present_warning():
    """没给 --patch 时别装不知道：把「交付件有 12 个补丁刚体、本次没装」写进报告。"""
    return ("未提供 --patch：本次场景只有 PMX 带的刚体，"
            "与交付件相比少 12 个（11 个 $name_j* + 地面_物理），"
            "读数边界条件与交付件不一致")


main()
