"""M02 attempt 10 的 evidence/1 生成器（**直接调规范实现** `coordination.evidence`）。

本笔两件事，同一个缺陷类：
  ① `cache_state` 的 CLI 输出与测试解码显式钉 UTF-8（attempt 9 那一笔）；
  ② 那条「故意要字节」的新测试标注 `# noqa: subprocess-bytes` 豁免——
     否则它会被 4号 的全仓护栏判红（护栏判据是「capture_output=True 且无 encoding=」）。
     AST 扫描器同步实现豁免语义，并记下一条实现要点：**注释常落在跨行调用的最后一行**，
     护栏要查整段（`lineno..end_lineno`）而不是第一行。

    python m02_make_evidence10.py <out.json>
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
HEAD = "97ed8a0"
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
    interface = "cache_state/1"          # D-080：interface 只放版本串

    ev = {
        "spec": "evidence/1",
        "task_id": "M02",
        "attempt": 10,
        "status": "PASS",
        "hash_basis": "lf_normalized_v1",
        # main 已并入 071ec3c，三点式只剩 1 个文件
        "files": [blob("tests/test_cache_state.py")],
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
            {"cmd": "python m02_scan_subprocess_encoding.py <A1 树>（AST 扫 text=True/"
                    "capture_output=True 缺 encoding=；`sha256_raw` 那类豁免按整段调用判）",
             "exit": 1, "passed": 1, "failed": 0, "skipped": 0},
        ],
        "artifacts": [art("reports/subai/M02/encoding_fix_log.txt"),
                      art("reports/subai/M02/scripts/m02_scan_subprocess_encoding.py")],
        "known_risks": [
            "本笔只修「我这三个 subprocess.run(text=True) 没给 encoding」+ `cache_state.main()` 的"
            "stdout/stderr 显式 UTF-8；**没有改动判据逻辑**（七态、行为证据、plan 动作全不变）。",
            "全仓同一类缺陷共 12 处，其余 9 处（tests/test_coordination.py 六处、mmdpipe/stage.py 三处、"
            "coordination/paths.py、coordination/gate.py、make_report.py）归 4号，本笔不碰。",
            "`test_coordination.py:550/551` 那条「两次跑输出相同」的确定性测试在 `None == None` 上"
            "**是假绿**——两个子进程都解码失败时断言会通过。这是 4号 那笔要加的护栏（`stdout` 先断言非空）"
            "覆盖面里最要紧的一条，本笔仅记录。",
            "`passed` 数是 327 总数减 15 skipped 得 312；不含任何 Blender 侧运行，本笔纯 Python。",
            "**本笔的事实（D-080 前的写法是把它们塞在 interface 里；现在按新规矩改成正文/风险条目，"
            "等 D-072 的 `measurements` 落地后再搬进去参与哈希）**：改动 = CLI stdout/stderr 显式 "
            "reconfigure(encoding='utf-8') + 测试统一走 run_cli(encoding='utf-8', errors='replace') + 新增"
            "「子进程 PYTHONIOENCODING=gbk、父进程按 UTF-8 解码必须成功且含中文 reason」一条；计数 = "
            "test_cache_state 35、全量 327（skipped 15）；两个环境（PYTHONIOENCODING=utf-8 / 默认）都跑过，"
            "都是 OK。",
            "本笔的 `files[]` 只有 1 项（`tests/test_cache_state.py`）：`mmdpipe/cache_state.py` 那半边"
            "已在 main 里（`ae7f180 merge: ai/a1 → main（M02 attempt 9…）`），三点式因此只有 1 个文件。"
            "按 `97ed8a0` 取 blob。",
            "我按 AST 扫了 A1 树（`3c19fed` + 我的提交，**4号 那笔修复尚未合并**）：命中 13 处，"
            "全部在 4号 名下（`make_report.py` 1、`addon/mmd_pipeline/operators.py` 1、"
            "`coordination/gate.py` 1、`coordination/paths.py` 1、`mmdpipe/stage.py` 3、"
            "`tests/test_coordination.py` 6）。我的两份文件 0 命中（其中字节级那条走豁免）。",
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
