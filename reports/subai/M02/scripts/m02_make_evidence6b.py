"""M02 attempt 6b 的 evidence/1 canonical 生成器（补正：脚本最终哈希 + P11）。

本笔三件事：① P10 空跑修正后重跑（只隔离 11 个 `$name_j` 占位刚体 → 下摆 5.7146 mm）；
② `cache_state.plan()` 修法决策（`ai/a1` `f0c8b2a`，18 条测试）；③ 重烘焙修法与变体 `design` 登记。

    python m02_make_evidence6b.py <out.json>
"""
import hashlib
import json
import os
import subprocess
import sys

ROOT = r"E:\dsh pr\woker2"
A1 = r"E:\code\mmdpipe-ai\A1"
HEAD = "f0c8b2a"


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def art(rel):
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        raise SystemExit("artifact 缺失：%s" % rel)
    return {"path": rel.replace("\\", "/"), "sha256": sha(p), "version": "1"}


def blob_sha(rel):
    data = subprocess.run(["git", "-C", A1, "show", "%s:%s" % (HEAD, rel)],
                          capture_output=True).stdout
    return {"path": rel, "sha256": hashlib.sha256(data).hexdigest(), "tracked": True}


ARTIFACTS = [
    "out/subai/M02/s8/H_nobake.blend",
    "reports/subai/M02/s8_P11_make.json",
    "reports/subai/M02/s8_P11_probe.json",
    "reports/subai/M02/s8_P11_result.json",
    "reports/subai/M02/s8_P11_seq_vs_P0.json",
    "reports/subai/M02/cache_gate_H_nobake.json",
    "out/subai/M02/s8/P11seq/meta.json",
    "out/subai/M02/s8/P11seq/frames.jsonl",
    "out/subai/M02/s8/P11seq/collections.json",
    "reports/subai/M02/scripts/m02_s8_p11.py",
    "reports/subai/M02/scripts/m02_cache_gate.py",
    "reports/subai/M02/scripts/m02_rebuild_scene.py",
    "out/subai/M02/s8/P10/meta.json",
    "out/subai/M02/s8/P10/collections.json",
    "out/subai/M02/s8/P10/frames.jsonl",
    "reports/subai/M02/s8_P10_placeholder_isolated.json",
    "reports/subai/M02/s8_index_v3.json",
    "reports/subai/M02/variant_designs.json",
    "reports/subai/M02/rebake_fix.md",
    "reports/subai/M02/binding_probe.json",
    "reports/subai/M02/bone_rigid_map.json",
    "reports/subai/M02/pmx_skirt_rigids.json",
    "reports/subai/M02/scripts/m02_binding_probe.py",
    "reports/subai/M02/scripts/m02_bone_rigid_map.py",
    "reports/subai/M02/m02_cache_finding.md",
    "reports/subai/M02/s2_cachefree_limit_05.json",
    "reports/subai/M02/result_attempt4.md",
    "reports/subai/M02/result_attempt3.md",
    "reports/subai/M02/s8_hypothesis.md",
    "reports/subai/M02/handoff.md",
    "reports/subai/M02/cache_gate_inventory.json",
    "reports/subai/M02/evidence_m02_attempt5.json",
    "reports/subai/M02/cache_state.json",
    "reports/subai/M02/scripts/m02_cache_gate.py",
    "reports/subai/M02/scripts/m02_s8_ab.py",
    "reports/subai/M02/scripts/m02_s8_index.py",
    "reports/subai/M02/s8_index_v2.json",
]


def main():
    out_path = sys.argv[1]
    ev = {
        "spec": "evidence/1",
        "task_id": "M02",
        "attempt": 6,
        "attempt_label": "6b（补正：脚本最终哈希 + P11 不烘焙交付验证）",
        "status": "PARTIAL",
        "files": [blob_sha("mmdpipe/cache_state.py"), blob_sha("tests/test_cache_state.py")],
        "tests": [
            {"cmd": "python -m unittest tests.test_cache_state (A1 @%s)" % HEAD, "exit": 0,
             "passed": 18, "failed": 0, "skipped": 0},
            {"cmd": "python -m unittest discover -s tests (A1 @%s)" % HEAD, "exit": 0,
             "passed": 146, "failed": 0, "skipped": 15},
            {"cmd": "blender -b -P m02_s8_ab.py -- G_base.blend P10（修正分支顺序后重跑）",
             "exit": 0, "passed": 1, "failed": 0, "skipped": 0},
            {"cmd": "blender -b -P m02_s8_p11.py -- make G_base.blend H_nobake.blend",
             "exit": 0, "passed": 1, "failed": 0, "skipped": 0},
            {"cmd": "blender -b -P m02_s8_p11.py -- probe H_nobake.blend 109（新进程）",
             "exit": 0, "passed": 1, "failed": 0, "skipped": 0},
            {"cmd": "blender -b -P m02_cache_gate.py -- H_nobake.blend", "exit": 0,
             "passed": 1, "failed": 0, "skipped": 0},
            {"cmd": "blender -b -P m02_s8_ab.py -- H_nobake.blend A（不烘焙按序重算 240 帧）",
             "exit": 0, "passed": 1, "failed": 0, "skipped": 0},
            {"cmd": "blender -b -P m02_cache_gate.py -- B_from_blend1.blend prepared_baseline.blend"
                    "（应当被拒的输入：baked+outdated）", "exit": 3,
             "passed": 1, "failed": 0, "skipped": 0},
            {"cmd": "blender -b -P m02_cache_gate.py -- <out 下全部 15 个 .blend>",
             "exit": 3, "passed": 15, "failed": 0, "skipped": 0},
        ],
        "artifacts": [art(a) for a in ARTIFACTS],
        "known_risks": [
            "attempt 6 的 artifacts 里 `m02_s8_ab.py` 登记的是 420abfa4…，而该文件在证据生成后又被编辑"
            "（P10 分支修正、design 字段、direct_changed、REQUIRE_CHANGE 护栏），盘上为 76d4429b…。"
            "本笔按最终脚本重算并重新生成证据；此后不再编辑任何已登记文件。",
            "P11 的 probe 用「单帧跳转」得到第三条轨迹（与 A1 差 2.30 m、与 P0 差 1.92 m）："
            "不烘焙文件冷跳到中间帧时，解算从该帧起算，不是从第 1 帧。"
            "按序重算（`P11seq`，1→240 逐帧）与 P0 **逐位 0.000000** ⇒ 渲染/顺序求值路径就是重算那条。",
            "因此「不烘焙交付」的契约必须写死：打开后不要直接跳到中间帧再渲染，"
            "按 scene.frame_start 起顺序求值（渲染默认即如此）。",
            "P10 第一次（13:17:19–13:17:46）是空跑：`elif variant == \"P10\"` 被写在了已有的 "
            "`elif variant in (…, \"P10\")` no-op 分支之后，实际未改动任何对象，`changed_bodies=0`。"
            "修正后重跑（13:18:0x–13:18:27，`changed_bodies=11`）才给出真实差异。旧目录已被覆盖，"
            "此处保留两次的时间与计数作为审计线索；D0 13:18 那句「P0 vs P10 逐位 0」即基于空跑。",
            "P10 修正后：`D_hem = 5.714589 mm`、`D_all = 1.652268 m`（324 刚体 × 240 帧）。"
            "⇒ 8.24 mm 里最大的一块来自那 11 个跨骨架静态占位刚体，不是飞霄骨架内部。",
            "本笔修改了两个已在 attempt 4 里登记的产物，旧 sha256 不再等于盘上文件：",
            "s2_cachefree_limit_05.json：fd08e55d…c4e9709 → b0b433f4…d8018206（D0 裁决："
            "UNKNOWN 是「没测出来」的专用词，本条测出来了，改用 comparison_kind=mechanism_probe + "
            "verdict=BELOW_CRITERION）",
            "result_attempt4.md：987b51bc…b399d95d4 → 72fc969b…f39d8018206（同上，并把「位移出现在链的下游」"
            "写进正文：最大位移骨 043_下擺_0_1，被削的是 下擺_0_11/0_12）",
            "attempt 3 的 result_attempt3.md 删掉了「再收紧到 0.5 rad 同样是零效果」这句未测推断，"
            "改为指向 attempt 4 的实测；其余内容与 s8 判据未动。",
            "cache_gate_inventory.json 是 out/ 下全部 15 个 .blend 的缓存状态快照（6 个 DEFECT、9 个 OK），"
            "随工程增删会变，不是稳态事实。",
            "cache_state.py 只做判据，不含任何 bpy 观测代码；观测侧仍由 m02_cache_gate.py 提供，"
            "stage.py 的调用由 4号 接（D0 定的 A+ 边界）。",
            "重烘焙（is_baked=true && is_outdated=false）需要 `bpy.ops.ptcache.bake_all()`，被 10 §6 禁用，"
            "所以修法只能取「解烘焙后保存」，不是待办。",
            "`variant_designs.json` 是事后补写（晚于各次运行），未回改任何 meta.json；meta 里的四个改动计数"
            "与 `placeholder_bodies` 是身份指纹。",
        ],
        "interface": {
            "module": "mmdpipe.cache_state",
            "verdicts": ["OK_UNBAKED", "OK_BAKED_CONSISTENT", "OK_NO_PHYSICS",
                         "DEFECT_BAKED_OUTDATED", "UNREADABLE"],
            "exit_codes": {"OK_*": 0, "DEFECT_BAKED_OUTDATED": 3, "UNREADABLE": 4},
            "input_record": {"exists": "bool", "has_physics": "bool",
                             "is_baked": "bool|null", "is_outdated": "bool|null"},
            "fail_closed": "字段缺失或类型不对 → UNREADABLE(4)，不退化成 OK",
            "cli": "python -m mmdpipe.cache_state records.json → 退出码 = 最坏的一条",
            "p11": {"unbake_saved": "H_nobake.blend", "is_baked": False, "gate": "OK_UNBAKED(0)",
                    "sequential_vs_P0": "0.000000 m（逐位相同）",
                    "cold_jump_vs_A1_m": 2.303467718, "cold_jump_vs_P0_m": 1.922861494,
                    "verdict": "不烘焙交付可行，但必须按序求值"},
            "p10": {"verdict": "EFFECTIVE", "D_hem_m": 0.005714589, "D_all_m": 1.652268506,
                    "changed_bodies": 11, "expectation": "应当改变（跨骨架静态碰撞体）"},
            "rebake_fix": {"chosen": "解烘焙后保存（is_baked=false）",
                           "rejected": "重烘焙（被 10 §6 的 bake_all 禁令挡死）"},
            "p8_classification": {"comparison_kind": "mechanism_probe", "verdict": "BELOW_CRITERION",
                                  "D_hem_m": 0.000385, "D_all_m": 0.469992,
                                  "statements": ["限位变量是活的（0.385 mm ≠ 0）",
                                                 "按 18 根下摆 1.0 mm 判据不达阈值",
                                                 "D_all 是混沌放大，不得读成偏转量"]},
        },
    }
    canonical = json.dumps(ev, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    data = canonical.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    with open(out_path, "wb") as fh:
        fh.write(data)
    print("evidence/1:" + digest)
    print("bytes=%d artifacts=%d files=%d file_sha=%s"
          % (len(data), len(ev["artifacts"]), len(ev["files"]), sha(out_path)))


main()
