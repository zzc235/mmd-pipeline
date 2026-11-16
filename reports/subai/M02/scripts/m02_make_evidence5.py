"""M02 attempt 5 的 evidence/1 canonical 生成器。

本笔两件事：① 按 D0 的裁决更正 P8 的状态词（`UNKNOWN` → `comparison_kind + BELOW_CRITERION`）；
② 把缓存一致性判据落进包里（`mmdpipe/cache_state.py` + 15 条测试，`ai/a1` `f33e032`）。

    python m02_make_evidence5.py <out.json>
"""
import hashlib
import json
import os
import subprocess
import sys

ROOT = r"E:\dsh pr\woker2"
A1 = r"E:\code\mmdpipe-ai\A1"
HEAD = "f33e032"


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
    "reports/subai/M02/s2_cachefree_limit_05.json",
    "reports/subai/M02/result_attempt4.md",
    "reports/subai/M02/result_attempt3.md",
    "reports/subai/M02/s8_hypothesis.md",
    "reports/subai/M02/handoff.md",
    "reports/subai/M02/cache_gate_inventory.json",
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
        "attempt": 5,
        "status": "PARTIAL",
        "files": [blob_sha("mmdpipe/cache_state.py"), blob_sha("tests/test_cache_state.py")],
        "tests": [
            {"cmd": "python -m unittest tests.test_cache_state (A1 @%s)" % HEAD, "exit": 0,
             "passed": 15, "failed": 0, "skipped": 0},
            {"cmd": "python -m unittest discover -s tests (A1 @%s)" % HEAD, "exit": 0,
             "passed": 143, "failed": 0, "skipped": 15},
            {"cmd": "blender -b -P m02_cache_gate.py -- B_from_blend1.blend prepared_baseline.blend"
                    "（应当被拒的输入：baked+outdated）", "exit": 3,
             "passed": 1, "failed": 0, "skipped": 0},
            {"cmd": "blender -b -P m02_cache_gate.py -- <out 下全部 15 个 .blend>",
             "exit": 3, "passed": 15, "failed": 0, "skipped": 0},
        ],
        "artifacts": [art(a) for a in ARTIFACTS],
        "known_risks": [
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
