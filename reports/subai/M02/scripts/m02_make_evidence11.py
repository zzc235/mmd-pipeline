"""M02 attempt 11：把 attempt 7 与 attempt 8 合并成一笔记录（D-078/D-079 指定的退件重出）。

按 D-080：**`interface` 只放版本串**，结构化内容一律进 `measurements`（D-072）。

    python m02_make_evidence11.py <out.json>

安全性：先探 `coordination.evidence.normalize()` 是否真的把 `measurements` 收进 canonical。
**不收就拒绝出记录**——否则这批数又一次落在哈希之外，等于重演退件理由。
"""
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.environ.get("M02_EVIDENCE_TREE") or r"E:\code\mmdpipe-ai\A1")
from coordination import evidence  # noqa: E402

ROOT = r"E:\dsh pr\woker2"
A1 = r"E:\code\mmdpipe-ai\A1"
COMMIT = "628ba3c"          # 这两笔实测所对应的代码提交（判据七态的提交）
INTERFACE = "cache_state/1"
TEXT_EXT = {".py", ".json", ".md", ".jsonl", ".txt"}


def dropped_keys(ev, norm):
    """我声明了的键 − normalize() 之后还在的键。

    只逐个查那三个可选键会漏掉以后新增的 schema 字段，所以直接比键集合；
    空集才允许落盘——「声明了但没进哈希」正是 attempt 11 被退的形状。
    """
    return sorted(set(ev) - set(norm))


def probe_schema():
    """探 `coordination.evidence.normalize()` 到底收了哪些可选键（D-072 measurements + 两个出处键）。

    三个都不支持就拒绝出记录——否则这批数/这些出处又一次落在哈希之外，重演退件理由。
    """
    probe = {"spec": "evidence/1", "task_id": "PROBE", "attempt": 0, "status": "PARTIAL",
             "files": [], "tests": [], "artifacts": [], "known_risks": [],
             "interface": None, "measurements": {"probe": 1},
             "commit": "0" * 7, "scope": "probe"}
    try:
        norm = evidence.normalize(probe)
    except Exception as exc:
        return {}, "normalize() 拒绝：%s: %s" % (type(exc).__name__, exc)
    missing = dropped_keys(probe, norm)
    if missing:
        return {}, "normalize() 接受但丢掉了 %s（9 键白名单未扩）" % "/".join(missing)
    return {key: norm[key] for key in ("measurements", "commit", "scope")}, "ok"


def sha_text(data):
    return hashlib.sha256(data).hexdigest()


def art(rel):
    path = os.path.join(ROOT, rel)
    data = open(path, "rb").read()
    if os.path.splitext(rel)[1].lower() in TEXT_EXT:
        data = data.replace(b"\r\n", b"\n")
    return {"path": rel.replace("\\", "/"), "sha256": sha_text(data), "version": "1"}


def blob(rel):
    data = subprocess.run(["git", "-C", A1, "show", "%s:%s" % (COMMIT, rel)],
                          capture_output=True).stdout
    return {"path": rel, "sha256": sha_text(data.replace(b"\r\n", b"\n")), "tracked": True}


def main():
    out_path = sys.argv[1]
    predict = "--predict" in sys.argv
    supported, why = probe_schema()
    if not supported and not predict:
        print("REFUSED: coordination.evidence 还缺可选键 —— %s" % why)
        print("（D-072/D-080 落地后重跑；现在出记录等于让这批数与出处继续落在哈希之外）")
        return 3
    if not supported:
        print("PREDICT 模式：%s" % why)
        print("PREDICT 口径 = 规范 normalize() + 把 measurements/commit/scope 原样塞回 canonical")

    a7 = json.load(open(os.path.join(ROOT, "reports/subai/M02/evidence_m02_attempt7.json"),
                        encoding="utf-8"))
    a8 = json.load(open(os.path.join(ROOT, "reports/subai/M02/evidence_m02_attempt8.json"),
                        encoding="utf-8"))

    artifacts = {}
    for src in (a7, a8):
        for row in src["artifacts"]:
            row = dict(row)
            row.pop("sha256_raw", None)      # D0：下一笔起只留三键
            artifacts[(row["path"], row["version"])] = row
    tests = {}
    for src in (a7, a8):
        for row in src["tests"]:
            tests[(row["cmd"], row["exit"])] = row
    # D0（第五节）：产生结论的脚本本身必须进哈希，否则半个月后没人知道这些数是哪个脚本出的。
    # 少一份都说明「结论可复现」这句话缺一条腿，所以这里不写默认、写死清单。
    for rel in ("reports/subai/M02/scripts/m02_recheck_measurements.py",
                "reports/subai/M02/scripts/m02_scan_subprocess_encoding.py",
                "reports/subai/M02/scripts/m02_scan_subprocess_encoding_v2.py",
                "reports/subai/M02/scripts/m02_scope_empty_pair.py"):
        row = art(rel)
        artifacts[(row["path"], row["version"])] = row
    risks = []
    for src in (a7, a8):
        risks.extend(src.get("known_risks") or [])
    risks.extend([
        "本笔是 D-078/D-079 指定的「7 + 8 合并重出」：内容一笔不减，形式按 D-080 改——"
        "`interface` 只放版本串 %r，结构化内容（七态判据、P12/P13、重建三数、P9 拒绝、掩码四条读数、"
        "addon 判据对照）全部进 `measurements`。旧编号 attempt 7 `024fe351…` / attempt 8 `10e3414e…` "
        "以及中间那两笔 7b `846ec787…` / 8b `1b13498d…` 全部作废，不再引用。" % INTERFACE,
        "`files[]` 按代码提交 `%s` 的两个 blob 取——**这是这两笔实测所对应的提交**，不是当前分支头。"
        "合并后三点式会变空，属正常（「该空却非空」才是错）。" % COMMIT,
        "`measurements` 里所有浮点均为有限值（已过 `_check_floats`）；本笔无 NaN/Inf。",
    ])

    measurements = {
        "verdicts": {
            "names": ["OK_UNBAKED", "OK_NO_PHYSICS", "OK_BAKED_CONSISTENT", "OK_BAKED_VERIFIED",
                      "DEFECT_BAKED_OUTDATED", "SUSPECT_BAKED_OUTDATED", "UNREADABLE"],
            "exit_codes": {"OK_UNBAKED": 0, "OK_NO_PHYSICS": 0, "OK_BAKED_CONSISTENT": 0,
                           "OK_BAKED_VERIFIED": 0, "DEFECT_BAKED_OUTDATED": 3,
                           "SUSPECT_BAKED_OUTDATED": 4, "UNREADABLE": 4},
            "batch_worst": "任一 DEFECT ⇒ 3；否则任一 SUSPECT/UNREADABLE ⇒ 4；否则 0",
            "behavior_field": {"cold_jump_frame": "int",
                               "cold_jump_vs_recompute_m": "float >= 0",
                               "tolerance_m": "float >= 0，缺省 1e-6"},
            "behavior_overrides_flags": True,
            "plan_actions": ["none", "probe_behavior", "rebake", "inspect", "sequential_delivery"],
            "rejected_actions": ["rebake_by_stepping", "unbake"],
            "tests": {"test_cache_state": 34, "full_suite": 148, "full_suite_skipped": 15},
        },
        "p12_rebake_by_stepping": {
            "verdict": "REJECTED",
            "seq_at_109_vs_P0_m": 0.0, "seq_at_240_vs_P0_m": 0.0, "seq_nonzero_bodies": 0,
            "cold_jump_109_vs_P0_m": 1.922861, "cold_jump_109_vs_A1_m": 2.303467,
            "cache_after_walk": {"is_baked": False, "is_outdated": False},
            "cache_at_reopen": {"is_baked": False, "is_outdated": True},
            "use_disk_cache": False, "dst_blend_bytes": 11173852,
        },
        "p13_bake_all": {
            "api": "bpy.ops.ptcache.bake_all(bake=True)", "exit": 0,
            "seconds_total": 33.19, "seconds_bake": 32.201, "frames_baked": 326,
            "use_disk_cache": False, "bodies": 324, "dst_blend_bytes": 11940653,
            "cache_after_bake": {"is_baked": True, "is_outdated": False},
            "cache_at_reopen": {"is_baked": True, "is_outdated": True},
            "cold_jump_109_vs_P0_m": 0.0, "cold_jump_240_vs_P0_m": 0.0,
            "cold_jump_109_vs_A1_m": 1.5867,
            "trajectory_sha256": "80819da0c14a84efedefce423126c526119720ca029de977ef357d23d9bc9df7",
            "trajectory_equal_P0": True,
        },
        "rebuild": {
            "pmx_sha256": "2db720a2281a9ea954082fc4d7f42f0d50a6ca72235d345566fbf5a28549a267",
            "rigids_after_import": 312, "rigids_after_build": 312,
            "name_j_hits": 0, "xia_bai_0_bodies": 18, "xia_bai_11_bodies": 0,
            "bones": 482, "vertices": 25506, "objects_added": 706, "skirt_bodies": 147,
            "gate_import": "OK_UNBAKED", "gate_built": "OK_UNBAKED", "gate_exit": 0,
            "delivered_rigids": 324, "delivered_name_j": 11,
            "conclusion": "交付场景不在当前代码的产出空间内",
            "silent_failure_forensic": {"blend": "rebuild_import.blend1", "bytes": 93719,
                                        "objects": 0, "rigids": 0, "rigidbody_world": False,
                                        "frame_end": 250},
        },
        "p9_disable_collisions": {
            "variant": "P9", "exit": 1, "refused": True,
            "disable_collisions_changed_count": 0,
            "constraint_types_total": {"GENERIC": 3651, "GENERIC_SPRING": 389},
            "constraint_types_disable_collisions": 0,
        },
        "s8_mask": {
            "structurally_unwired": True,
            "objects_with_mmd_rigid": 324, "rigid_objects": 324, "distinct_masks": 28,
            "collision_collections_all_bit0": True, "collision_collections_width": 20,
            "disable_collisions_constraints": 0,
            "pmx_rigids": 312, "pmx_unique_names": 296, "pmx_groups": 9,
            "pmx_ignored_pairs": 19191, "pmx_pairs": 48516, "pmx_ignored_fraction": 0.3956,
        },
        "addon_gate": {
            "hasattr_is_discriminating": False, "enable_return_is_discriminating": False,
            "get_rna_type_ok": "MMD_TOOLS_OT_import_model",
            "get_rna_type_absent": "KeyError: get_rna_type(...) not found",
            "poll_absent": "AttributeError: ... could not be found",
        },
        "inventory_v2": {"defect": 1, "suspect": 6, "ok": 10, "total": 17,
                         "only_defect": "B_from_blend1.blend",
                         "only_defect_behavior_m": 1.5867},
        "provenance": {"commit": COMMIT, "branch": "ai/a1",
                       "merged_attempts": [7, 8], "supersedes_digests":
                       ["024fe3516e00efde57b7865c039b9918d0df6b26a095cd877076b45d2c34501a",
                        "10e3414ed5477914239391ecc191eb130eb2117d1d1fec405e68f287afcbf429"]},
    }

    ev = {
        "spec": "evidence/1",
        "task_id": "M02",
        "attempt": 11,
        "status": "PARTIAL",
        "hash_basis": "lf_normalized_v1",
        "files": [blob("mmdpipe/cache_state.py"), blob("tests/test_cache_state.py")],
        "tests": sorted(tests.values(), key=lambda r: (r["cmd"], r["exit"])),
        "artifacts": sorted(artifacts.values(), key=lambda r: r["path"]),
        "known_risks": risks,
        "interface": INTERFACE,
        "measurements": measurements,
        "commit": COMMIT,
        "scope": "M02 缓存判据（mmdpipe/cache_state 七态）+ P12/P13 缓存修法实测 + 交付场景重建三数",
    }

    normalized = evidence.normalize(ev)
    dropped = dropped_keys(ev, normalized)
    if dropped:
        if not predict:
            print("REFUSED: normalize() 丢了 %s —— 声明了却没进哈希，落盘就是 attempt 11 被退的形状"
                  % "/".join(dropped))
            return 3
        print("PREDICT 注入被丢的键: %s（预演值对「注入」这一步是敏感的，落地后必须原样复现）"
              % "/".join(dropped))
        normalized = dict(normalized)
        for key in dropped:
            normalized[key] = ev[key]
    if predict:
        data = evidence.canonical_bytes(normalized)
        digest = hashlib.sha256(data).hexdigest()
        print("PREDICT evidence/1:" + digest)
        print("PREDICT bytes=%d measurements_bytes=%d（**没有写文件**）"
              % (len(data), len(json.dumps(normalized["measurements"], sort_keys=True,
                                           separators=(",", ":"), ensure_ascii=False))))
        return 0
    data = evidence.canonical_bytes(normalized)
    with open(out_path, "wb") as fh:
        fh.write(data)
    digest = hashlib.sha256(data).hexdigest()
    again = evidence.digest(json.loads(data))
    print("evidence/1:" + digest)
    print("bytes=%d artifacts=%d files=%d tests=%d risks=%d"
          % (len(data), len(normalized["artifacts"]), len(normalized["files"]),
             len(normalized["tests"]), len(normalized["known_risks"])))
    print("measurements_bytes=%d" % len(json.dumps(normalized["measurements"], sort_keys=True,
                                                   separators=(",", ":"), ensure_ascii=False)))
    print("file_sha256=%s rederive=%s match=%s"
          % (hashlib.sha256(open(out_path, "rb").read()).hexdigest(), again,
             again == "evidence/1:" + digest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
