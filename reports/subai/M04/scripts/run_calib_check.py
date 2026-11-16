"""用合成坏样本验证「门禁会不会按设计响应」——**只验响应，不验门限有效性**。

对 out/subai/M04/calib/ 下四个合成样本各跑一次 measure + gate，输出一张期望/实测对照表。
"""
import json
import os
import subprocess
import sys

A2 = r"E:\code\mmdpipe-ai\A2"
MAIN = r"E:\dsh pr\woker2"
CALIB = os.path.join(MAIN, "out", "subai", "M04", "calib")
OUT = os.path.join(MAIN, "out", "subai", "M04", "calib_results")

expect = {
    "B1_overshoot_spike": {"overshoot": "FAIL"},
    "B2_overshoot_tail": {"overshoot": "FAIL"},
    "B3_frozen": {"frozen": "FAIL"},
    "B4_penetration_deep": {"penetration": "FAIL"},
}


def run(cmd):
    return subprocess.run(cmd, cwd=A2, capture_output=True, text=True, encoding="utf-8")


os.makedirs(OUT, exist_ok=True)
rows = []
for name, want in expect.items():
    dy = os.path.join(CALIB, name + ".dynamics.jsonl")
    if name == "B4_penetration_deep":
        # 只换穿透输入：dynamics 必须用回干净基线，否则一次两变、FAIL 无法归因
        dy = os.path.join(MAIN, "out", "subai", "M02", "dyn", "B2_baseline", "frames.jsonl")
    args = [sys.executable, "-m", "mmdpipe.measure", "--dynamics", dy,
            "--assembly", os.path.join("presets", "physics_gate", "assembly_v1.json"),
            "--sample-id", name, "--evidence-mode", "synthetic",
            "--frame-start", "1", "--frame-end", "240",
            "--out", os.path.join(OUT, name + ".measurement.json")]
    if name == "B4_penetration_deep":
        args += ["--penetration", os.path.join(CALIB, name + ".penetration.jsonl"),
                 "--penetration-basis", "capsule", "--roi", "18_skirt_capsule"]
    m = run(args)
    if m.returncode != 0:
        rows.append({"sample": name, "stage": "measure", "exit": m.returncode,
                     "stderr": m.stderr[-400:]})
        continue
    g = run([sys.executable, "-m", "mmdpipe.physics_gate",
             "--measurement", os.path.join(OUT, name + ".measurement.json"),
             "--profile", os.path.join("presets", "physics_gate", "exploratory_v0.json"),
             "--out", os.path.join(OUT, name + ".gate.json")])
    gate = json.load(open(os.path.join(OUT, name + ".gate.json"), encoding="utf-8"))
    got = {k: v["status"] for k, v in gate["gate_results"].items()}
    ok = all(got.get(k) == v for k, v in want.items())
    rows.append({"sample": name, "expect": want, "got": got, "aggregate": gate["status"],
                 "exit": g.returncode, "as_designed": ok,
                 "reason": {k: v["reason"] for k, v in gate["gate_results"].items()
                            if v["status"] == "FAIL"}})

print(json.dumps({"note": "合成样本只验门禁响应，不验门限有效性", "results": rows},
                 ensure_ascii=True, indent=1))
