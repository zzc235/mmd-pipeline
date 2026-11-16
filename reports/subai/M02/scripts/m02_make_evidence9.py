"""M02 attempt 9 的 evidence/1 生成器（**直接调规范实现** `coordination.evidence`）。

本笔只有一件事：把「subprocess 文本解码没钉 UTF-8」这一类缺陷在我这两个文件上修掉——
main 在 `PYTHONIOENCODING=utf-8` 下红过，就是这一类。

    python m02_make_evidence9.py <out.json>
"""
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, r"E:\code\mmdpipe-ai\A1")
from coordination import evidence  # noqa: E402

ROOT = r"E:\dsh pr\woker2"
A1 = r"E:\code\mmdpipe-ai\A1"
HEAD = "071ec3c"
TEXT_EXT = {".py", ".json", ".md", ".jsonl", ".txt"}


def art(rel):
    path = os.path.join(ROOT, rel)
    data = open(path, "rb").read()
    if os.path.splitext(rel)[1].lower() in TEXT_EXT:
        data = data.replace(b"\r\n", b"\n")
    return {"path": rel.replace("\\", "/"), "sha256": hashlib.sha256(data).hexdigest(),
            "version": "1"}


def blob(rel):
    data = subprocess.run(["git", "-C", A1, "show", "%s:%s" % (HEAD, rel)],
                          capture_output=True).stdout
    return {"path": rel, "sha256": hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest(),
            "tracked": True}


def main():
    out_path = sys.argv[1]
    interface = {
        "module": "mmdpipe.cache_state",
        "change": "CLI 输出与测试解码显式钉 UTF-8",
        "cli": {"stdout_reconfigure_utf8": True,
                "precedent": "mmdpipe/measure.py main() 同一做法"},
        "tests": {"helper": "TestCli.run_cli(args)",
                  "explicit": "encoding='utf-8', errors='replace'",
                  "new": "test_cli_emits_utf8_even_under_gbk_locale（子进程 PYTHONIOENCODING=gbk，"
                         "父进程按 UTF-8 解码必须成功且含中文 reason）"},
        "counts": {"test_cache_state": 35, "full_suite": 327, "skipped": 15},
        "environments_checked": ["PYTHONIOENCODING=utf-8", "默认（未设该变量）"],
    }
    ev = {
        "spec": "evidence/1",
        "task_id": "M02",
        "attempt": 9,
        "status": "PASS",
        "hash_basis": "lf_normalized_v1",
        "files": [blob("mmdpipe/cache_state.py"), blob("tests/test_cache_state.py")],
        "tests": [
            {"cmd": "python -m unittest discover -s tests -t tests -p test_*.py"
                    "（PYTHONIOENCODING=utf-8，A1 @%s）" % HEAD,
             "exit": 0, "passed": 312, "failed": 0, "skipped": 15},
            {"cmd": "python -m unittest discover -s tests -t tests -p test_*.py"
                    "（默认环境，A1 @%s）" % HEAD,
             "exit": 0, "passed": 312, "failed": 0, "skipped": 15},
            {"cmd": "python -m unittest discover -s tests -t tests -p test_cache_state.py"
                    "（默认环境）",
             "exit": 0, "passed": 35, "failed": 0, "skipped": 0},
        ],
        "artifacts": [art("reports/subai/M02/encoding_fix_log.txt")],
        "known_risks": [
            "本笔只修「我这三个 subprocess.run(text=True) 没给 encoding」+ `cache_state.main()` 的"
            "stdout/stderr 显式 UTF-8；**没有改动判据逻辑**（七态、行为证据、plan 动作全不变）。",
            "全仓同一类缺陷共 12 处，其余 9 处（tests/test_coordination.py 六处、mmdpipe/stage.py 三处、"
            "coordination/paths.py、coordination/gate.py、make_report.py）归 4号，本笔不碰。",
            "`test_coordination.py:550/551` 那条「两次跑输出相同」的确定性测试在 `None == None` 上"
            "**是假绿**——两个子进程都解码失败时断言会通过。这是 4号 那笔要加的护栏（`stdout` 先断言非空）"
            "覆盖面里最要紧的一条，本笔仅记录。",
            "`passed` 数是 327 总数减 15 skipped 得 312；不含任何 Blender 侧运行，本笔纯 Python。",
            "**7b/8b 更正**：attempt 7（`024fe351…`）与 attempt 8（`10e3414e…`）用 `coordination.evidence` "
            "复算会抛 `EvidenceError: interface 必须是字符串或 null`——我把 interface 写成了 dict。"
            "内容未变，重新按规范实现出成 `846ec787…`（7b）与 `1b13498d…`（8b），前两笔作废。",
        ],
        "interface": json.dumps(interface, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    }

    normalized = evidence.normalize(ev)
    data = evidence.canonical_bytes(normalized)
    with open(out_path, "wb") as fh:
        fh.write(data)
    digest_hex = hashlib.sha256(data).hexdigest()
    again = evidence.digest(json.loads(data))
    print("evidence/1:" + digest_hex)
    print("bytes=%d artifacts=%d files=%d tests=%d" % (len(data), len(normalized["artifacts"]),
                                                       len(normalized["files"]),
                                                       len(normalized["tests"])))
    print("file_sha256=%s rederive=%s match=%s"
          % (hashlib.sha256(open(out_path, "rb").read()).hexdigest(), again,
             again == "evidence/1:" + digest_hex))


main()
