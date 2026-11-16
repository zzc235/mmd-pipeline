"""M02 attempt 7 的 evidence/1 canonical 生成器。

本笔四件事：
  ① `cache_state` 判据重写（旗标只筛选 + 行为探针定结论，七态；`plan()` 增 probe_behavior / rebake；
     `sidecar()` 供交付随件）——`ai/a1` `628ba3c`；
  ② P12：解烘焙 → 顺序步进 1→240 → 存盘，**救不回**冷跳（`rebake_by_stepping` 已证伪）；
  ③ P13：`bake_all()` 一次受控实测——exit 0 / 32.2 s / 冷跳逐位等于 `P0` / 整段 240 帧逐字节相同；
  ④ 重建：今天的代码产出 **312** 刚体 / `$name_j` **0** / row 11 刚体 **0**，交付物 324 ⇒ 不在产出空间内；
     附带两条 `stage.py` 静默失败缺陷与 v2 产物的尸检（`OK_NO_PHYSICS`）。

    python m02_make_evidence7.py <out.json>

哈希基数：`hash_basis = "lf_normalized_v1"`（D0 13:24 定的全队口径）——文本先 `\\r\\n → \\n` 再 sha256，
二进制按原字节。已知有 CRLF 的文件会在 `known_risks` 里点名。
"""
import hashlib
import json
import os
import subprocess
import sys

ROOT = r"E:\dsh pr\woker2"
A1 = r"E:\code\mmdpipe-ai\A1"
HEAD = "628ba3c"
HASH_BASIS = "lf_normalized_v1"

TEXT_EXT = {".py", ".json", ".md", ".jsonl", ".txt", ".toml", ".cfg"}


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def normalize(data, ext):
    """文本按 LF 归一后再哈希；二进制原样。"""
    if ext.lower() in TEXT_EXT and b"\r\n" in data:
        return data.replace(b"\r\n", b"\n"), True
    return data, False


def art(rel):
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        raise SystemExit("artifact 缺失：%s" % rel)
    data = read_bytes(p)
    norm, had_crlf = normalize(data, os.path.splitext(p)[1])
    entry = {"path": rel.replace("\\", "/"), "sha256": sha_bytes(norm), "version": "1"}
    if had_crlf:
        entry["sha256_raw"] = sha_bytes(data)
    return entry


def blob_sha(rel):
    data = subprocess.run(["git", "-C", A1, "show", "%s:%s" % (HEAD, rel)],
                          capture_output=True).stdout
    if not data:
        raise SystemExit("git blob 读不到：%s" % rel)
    return {"path": rel, "sha256": sha_bytes(normalize(data, os.path.splitext(rel)[1])[0]),
            "tracked": True}


ARTIFACTS = [
    # ① 判据
    "reports/subai/M02/scripts/m02_cache_gate.py",
    "reports/subai/M02/cache_gate_inventory_v2.json",
    "reports/subai/M02/cache_behavior.json",
    "reports/subai/M02/cache_gate_rebuild.json",
    "reports/subai/M02/cache_gate_rebuild_v2.json",
    "reports/subai/M02/cache_gate_H_nobake.json",
    "reports/subai/M02/cache_state.json",
    "reports/subai/M02/cache_gate_inventory.json",
    # ② P12
    "reports/subai/M02/scripts/m02_s8_p12.py",
    "reports/subai/M02/scripts/m02_s8_p12_cmp.py",
    "reports/subai/M02/scripts/m02_frame_cmp.py",
    "reports/subai/M02/p12_make.json",
    "reports/subai/M02/p12_probe.json",
    "reports/subai/M02/p12_cmp.json",
    "out/subai/M02/s8/I_src.blend",
    "out/subai/M02/s8/I_fresh.blend",
    # ③ P13
    "reports/subai/M02/scripts/m02_s8_p13.py",
    "reports/subai/M02/P13_bake.json",
    "reports/subai/M02/P13_bake.timeline.jsonl",
    "reports/subai/M02/P13_probe.json",
    "reports/subai/M02/P13_probe_f240.json",
    "reports/subai/M02/P13_cmp.json",
    "reports/subai/M02/P13_cmp_f240.json",
    "out/subai/M02/s8/J_src.blend",
    "out/subai/M02/s8/J_baked.blend",
    "out/subai/M02/s8/P13run/frames.jsonl",
    "out/subai/M02/s8/P13run/meta.json",
    "out/subai/M02/s8/P13run/collections.json",
    # ④ 重建
    "reports/subai/M02/scripts/m02_rebuild_scene.py",
    "reports/subai/M02/scripts/m02_rebuild_scene_v2.py",
    "reports/subai/M02/scripts/m02_rebuild_scene_v3.py",
    "reports/subai/M02/scripts/m02_probe_blend.py",
    "reports/subai/M02/scripts/m02_addon_gate_probe.py",
    "reports/subai/M02/addon_gate_normal.json",
    "reports/subai/M02/addon_gate_isolated.json",
    "reports/subai/M02/rebuild/rebuild_import_blend1_content.json",
    "out/subai/M02/rebuild/rebuild_report.json",
    "out/subai/M02/rebuild/rebuild_import.blend",
    "out/subai/M02/rebuild/rebuild_built.blend",
    "out/subai/M02/rebuild/rebuild_import.blend1",
    "reports/subai/M02/rebuild_finding.md",
    # P11（笔内互相印证：不烘焙 + 顺序求值 == P0）
    "reports/subai/M02/scripts/m02_s8_p11.py",
    "reports/subai/M02/s8_P11_make.json",
    "reports/subai/M02/s8_P11_probe.json",
    "reports/subai/M02/s8_P11_result.json",
    "reports/subai/M02/s8_P11_seq_vs_P0.json",
    "out/subai/M02/s8/P11seq/frames.jsonl",
    "out/subai/M02/s8/P11seq/meta.json",
    "out/subai/M02/s8/P11seq/collections.json",
    "out/subai/M02/s8/H_nobake.blend",
    # 文档与索引
    "reports/subai/M02/rebake_fix.md",
    "reports/subai/M02/handoff.md",
    "reports/subai/M02/m02_cache_finding.md",
    "reports/subai/M02/s8_hypothesis.md",
    "reports/subai/M02/variant_designs.json",
    "reports/subai/M02/s8_index_v3.json",
    "reports/subai/M02/result_attempt4.md",
    "reports/subai/M02/evidence_m02_attempt6b.json",
]

TESTS = [
    {"cmd": "python -m unittest discover -s tests -t tests -p test_cache_state.py (A1 @%s)" % HEAD,
     "exit": 0, "passed": 34, "failed": 0, "skipped": 0},
    {"cmd": "python -m unittest discover -s tests -t tests -p test_*.py (A1 @%s)" % HEAD,
     "exit": 0, "passed": 147, "failed": 0, "skipped": 15},
    {"cmd": "blender -b -P m02_s8_p12.py -- make I_src.blend I_fresh.blend",
     "exit": 0, "passed": 1, "failed": 0, "skipped": 0},
    {"cmd": "blender -b -P m02_s8_p12.py -- probe I_fresh.blend 109（新进程，冷跳）",
     "exit": 0, "passed": 1, "failed": 0, "skipped": 0},
    {"cmd": "blender -b -P m02_s8_p13.py -- bake J_src.blend J_baked.blend（bake_all 单次）",
     "exit": 0, "passed": 1, "failed": 0, "skipped": 0},
    {"cmd": "blender -b -P m02_s8_p13.py -- probe J_baked.blend 109（新进程，冷跳）",
     "exit": 0, "passed": 1, "failed": 0, "skipped": 0},
    {"cmd": "blender -b -P m02_s8_p13.py -- probe J_baked.blend 240（新进程，冷跳）",
     "exit": 0, "passed": 1, "failed": 0, "skipped": 0},
    {"cmd": "blender -b -P m02_s8_ab.py -- J_baked.blend P13run A --allow-baked（整段 240 帧）",
     "exit": 0, "passed": 1, "failed": 0, "skipped": 0},
    {"cmd": "blender -b -P m02_cache_gate.py -- <out 下全部 17 个 .blend> --behavior cache_behavior.json",
     "exit": 3, "passed": 17, "failed": 0, "skipped": 0},
    {"cmd": "blender -b -P m02_rebuild_scene_v3.py -- <feiying.pmx>（重建交付场景）",
     "exit": 0, "passed": 1, "failed": 0, "skipped": 0},
    {"cmd": "blender -b -P m02_addon_gate_probe.py -- <normal|isolated>（假启用判据对照）",
     "exit": 0, "passed": 2, "failed": 0, "skipped": 0},
]


def main():
    out_path = sys.argv[1]
    artifacts = [art(a) for a in ARTIFACTS]
    crlf = [a["path"] for a in artifacts if "sha256_raw" in a]

    ev = {
        "spec": "evidence/1",
        "task_id": "M02",
        "attempt": 7,
        "attempt_label": "7（判据七态 + P12/P13 + 重建三数）",
        "status": "PARTIAL",
        "hash_basis": HASH_BASIS,
        "files": [blob_sha("mmdpipe/cache_state.py"), blob_sha("tests/test_cache_state.py")],
        "tests": TESTS,
        "artifacts": artifacts,
        "known_risks": [
            "**判据改了口径**：`is_baked && is_outdated` 不是缺陷证据（P13 里健康件 `J_baked.blend` "
            "重开后同样是 true && true）。因此 `DEFECT_BAKED_OUTDATED` 只在**有行为证据且不一致**时给出；"
            "没有行为证据判 `SUSPECT_BAKED_OUTDATED`(4)。`cache_gate_inventory.json`（旧盘点）里那 6 个"
            "「缺陷」按此全部降为 SUSPECT，`cache_gate_inventory_v2.json` 是现行盘点：1 DEFECT / 6 SUSPECT / 10 OK。",
            "`m02_cache_gate.py` 本笔重写：判据改为从 `mmdpipe.cache_state` import（不再保留第二份），"
            "import 不到直接 exit 4；新增 `--behavior`。因此 attempt 6b 里该文件的登记哈希已失效。",
            "P13 是 §6 的**单次**临时豁免实验（D0 13:27:36 批），`bake_all` exit 0、32.2 s、无段错误。"
            "「312 刚体段错误」记为今日不可复现，**禁令不删**，改为常驻豁免 + 四条条件（副本 / 单次 / "
            "崩溃只记码 / 成功也必须过行为探针）。",
            "P13 的冷跳证据是**两个帧点 + 一整段**（f109、f240 逐位 0；240 帧 `frames.jsonl` 与 `P0` 逐字节相同），"
            "不是「所有帧都验过」。未跳过的帧按同一机制推断。",
            "P12 证明「解烘焙 → 顺序步进 → 存盘」救不回冷跳（对新进程差 1.922861 m，与只解烘焙的 `H_nobake` 完全相同）："
            "内存 point cache 不落盘，落盘的只有 `info` 字符串。该修法已写入 `cache_state.REJECTED_ACTIONS`。",
            "`point_cache.info` 会随 `.blend` 落盘但帧数据不会：重开后 `info` 仍写「240 frames in memory」，"
            "而 `is_outdated` 已翻回 true。判据不得以 `info` 为依据。",
            "重建结论只覆盖这一个 PMX + 这一个预设（`presets/feiying.json`）：今天产出 **312** 刚体、"
            "`$name_j` 命中 **0**、`下擺_11_*` 刚体 **0**；交付物 `B_from_blend1.blend` 是 324。"
            "「交付场景不可由当前代码重建」据此成立，但**不**等于「任何 PMX 都缺第 11 行刚体」。",
            "`rebuild_import.blend1` 是 v3 覆盖保存时 Blender 轮转出来的上一版（93 719 B，13:22:31），"
            "探明是**空场景**：`objects: 0` / `rigids: 0` / 无 `rigidbody_world` / `frame_end: 250`（默认值），"
            "闸门判 `OK_NO_PHYSICS`——这是 v2 那次静默失败（0 刚体）的实物证据。"
            "它**不是**由 v2 直接命名保存的文件，归属依据是时间戳与保存顺序，文件内没有自述字段。",
            "更正我在 13:23 那条建议：断言 `hasattr(bpy.ops.mmd_tools, \"import_model\")` **不能**判插件是否真注册——"
            "空扩展仓库下它仍是 True（`addon_gate_isolated.json`）。可判的是 `get_rna_type()` 不抛（或 `poll()`）。",
            "`P13_run` 用的是 `m02_s8_ab.py` 的 `A` 变体 + `--allow-baked`（该脚本对 baked 输入默认拒绝），"
            "它逐帧 `frame_set(1..240)`，属顺序求值口径。",
            "本笔未跑 P9（`DISABLE_COLLISIONS` 变体的拒绝路径），S8 三层实验与掩码影响量仍是 `UNMEASURED`。",
            "`cache_state` 只做判据，不含 bpy 观测；`stage.py` 侧接入由 4号 按块 4 边界做。",
        ],
        "interface": {
            "module": "mmdpipe.cache_state",
            "verdicts": ["OK_UNBAKED", "OK_NO_PHYSICS", "OK_BAKED_CONSISTENT", "OK_BAKED_VERIFIED",
                         "DEFECT_BAKED_OUTDATED", "SUSPECT_BAKED_OUTDATED", "UNREADABLE"],
            "exit_codes": {"OK_*": 0, "DEFECT_BAKED_OUTDATED": 3,
                           "SUSPECT_BAKED_OUTDATED": 4, "UNREADABLE": 4},
            "batch_worst": "按严重度：任一 DEFECT ⇒ 3；否则任一 SUSPECT/UNREADABLE ⇒ 4；否则 0（不是取数值最大）",
            "input_record": {"exists": "bool", "has_physics": "bool", "is_baked": "bool|null",
                             "is_outdated": "bool|null",
                             "behavior": "{cold_jump_frame, cold_jump_vs_recompute_m, tolerance_m} 可选"},
            "behavior_priority": "有行为证据时压过旗标（量到的比声明的可信）",
            "default_tolerance_m": 1e-06,
            "plan_actions": ["none", "probe_behavior", "rebake", "inspect", "sequential_delivery"],
            "rejected_actions": ["rebake_by_stepping", "unbake"],
            "sidecar": "cache_state.sidecar(record) → *.cache_state.json（is_baked/is_outdated/info/bodies/"
                       "use_disk_cache + verdict/exit_code/spec/behavior）",
            "cli": "python -m mmdpipe.cache_state records.json → 退出码按严重度",
            "p12": {"verdict": "REJECTED（跑一遍再存盘救不回冷跳）",
                    "seq_vs_P0": "0.000000 / 0.000000（f109、f240，逐位）",
                    "cold_jump_vs_P0_m": 1.922861, "cold_jump_vs_A1_m": 2.303467,
                    "cache_after_walk": {"is_baked": False, "is_outdated": False},
                    "cache_at_reopen": {"is_baked": False, "is_outdated": True},
                    "use_disk_cache": False},
            "p13": {"api": "bpy.ops.ptcache.bake_all(bake=True)", "exit": 0, "seconds": 32.2,
                    "frames_baked": 326, "use_disk_cache": False,
                    "cache_after_bake": {"is_baked": True, "is_outdated": False},
                    "cache_at_reopen": {"is_baked": True, "is_outdated": True},
                    "cold_jump_f109_vs_P0": "0.000000（逐位）",
                    "cold_jump_f240_vs_P0": "0.000000（逐位）",
                    "trajectory_sha_equal_P0": "80819da0c14a84efedefce423126c526119720ca029de977ef357d23d9bc9df7",
                    "cold_jump_vs_A1_m": 1.5867},
            "rebuild": {"rigids": 312, "name_j_hits": 0, "xia_bai_0": 18, "xia_bai_11_bodies": 0,
                        "bones": 482, "vertices": 25506, "objects_added": 706,
                        "gate": "OK_UNBAKED(0)", "delivered_rigids": 324,
                        "verdict": "交付场景不在当前代码的产出空间内"},
            "addon_gate": {"hasattr_is_discriminating": False, "enable_return_is_discriminating": False,
                           "get_rna_type_ok": "MMD_TOOLS_OT_import_model",
                           "get_rna_type_absent": "KeyError: get_rna_type(...) not found",
                           "poll_absent": "AttributeError: ... could not be found"},
        },
    }
    canonical = json.dumps(ev, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    data = canonical.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    with open(out_path, "wb") as fh:
        fh.write(data)
    print("evidence/1:" + digest)
    print("bytes=%d artifacts=%d files=%d file_sha=%s crlf_artifacts=%s"
          % (len(data), len(artifacts), len(ev["files"]), sha_bytes(data), crlf or "none"))


main()
