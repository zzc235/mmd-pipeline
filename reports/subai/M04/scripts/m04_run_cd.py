# -*- coding: utf-8 -*-
"""C@W1 / C@W2 / D 三臂测量的一次性驱动（M04，纯 Python 调 Blender）。

为什么要一支驱动而不是手敲六条命令：每一步的**退出码**与**产物完整性**都要落进台账，
而 Blender 5.2.2 在 `--background` 退出清理阶段会崩（`-1073741819`）却把产物写全——
「看退出码」和「看产物」这两件事必须同时记，不能二选一（`D-135` 那族）。

顺序（每步独立 Blender 进程，同一时刻只有一个）：

  1. `m04_rigid_mask_dump.py`   在 C@W1 上 dump 刚体→骨（新骨架 482 骨，旧的 dump 不能复用）
  2. 从 dump 取 `下擺_0_*` 骨名（这是 A0 那一轮用的同一支 ROI 口径）
  3. `m04_roi_align.py`         顶点组口径 vs 刚体口径对齐
  4. 探针 `--baseline-write`    在**无动作**的输入重建件上取静态基线（这一份给三臂共用）
  5. 探针 C@W1  `--frames 1:240`
  6. 探针 C@W2  `--frames 1:832`
  7. 探针 D     `--frames 1:832`

每一臂开跑前核一次输入 blend 的 sha256（第七条：跑前核），不同就停该臂。

用法：
    python reports/subai/M04/scripts/m04_run_cd.py --arms-dir <A3/out/subai/M05/arms> \
        --input <A1/out/subai/M08/rebuild_built.blend> --out-dir <out/subai/M04/penetration>
"""
import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import time

BLENDER = r"E:\code\Blender\blender-5.2.2-windows-x64\blender.exe"
HERE = os.path.dirname(os.path.abspath(__file__))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(name, cmd, log_path, want_product):
    """跑一个 Blender 进程；退出码原样记，成败看产物。"""
    t0 = time.time()
    with open(log_path, "wb") as log:
        rc = subprocess.call(cmd, stdout=log, stderr=subprocess.STDOUT)
    dt = time.time() - t0
    ok = os.path.exists(want_product) and os.path.getsize(want_product) > 0
    rec = {"step": name, "exit": rc, "seconds": round(dt, 1),
           "product": want_product.replace("\\", "/"),
           "product_bytes": (os.path.getsize(want_product) if os.path.exists(want_product) else None),
           "ok_by_product": bool(ok), "log": log_path.replace("\\", "/")}
    print("[%s] exit=%s %.1fs product=%s" % (name, rc, dt, "ok" if ok else "MISSING"), flush=True)
    return rec


def check_frames(meta_path, f0, f1):
    with io.open(meta_path, encoding="utf-8") as fh:
        meta = json.load(fh)
    got = len(meta.get("per_frame") or [])
    want = f1 - f0 + 1
    return {"frames_want": want, "frames_got": got, "complete": got == want,
            "frames_measured": meta.get("frames_measured"),
            "eval_policy": meta.get("eval_policy"),
            "is_baked": (meta.get("cache_state") or {}).get("is_baked"),
            "pairs_without_baseline": sum(int(r.get("pairs_without_baseline") or 0)
                                          for r in (meta.get("per_frame") or [])),
            "roi_missing": meta.get("roi_missing")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms-dir", required=True)
    ap.add_argument("--input", required=True)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()

    pen = a.out_dir
    os.makedirs(pen, exist_ok=True)
    dump = os.path.join(pen, "rigid_mask_dump_cd.json")
    align = os.path.join(pen, "roi_align_cd.json")
    base = os.path.join(pen, "baseline_delivery_v1.json")

    arms = {"C_W1": ("C_W1.blend", 1, 240),
            "C_W2": ("C_W2.blend", 1, 832),
            "D": ("D.blend", 1, 832)}

    ledger = {"spec": "m04_run_cd/1", "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "arms_dir": a.arms_dir.replace("\\", "/"), "input": a.input.replace("\\", "/"),
              "input_sha256": sha256(a.input), "arms": {}, "steps": [], "gates": {}}

    # 输入臂的 sha（跑前核，第七条）
    for key, (fname, _f0, _f1) in arms.items():
        p = os.path.join(a.arms_dir, fname)
        ledger["arms"][key] = {"path": p.replace("\\", "/"), "sha256_before": sha256(p),
                               "bytes": os.path.getsize(p)}

    cw1 = os.path.join(a.arms_dir, arms["C_W1"][0])

    # 1) 刚体→骨 dump（新骨架）
    ledger["steps"].append(run("1_dump", [
        BLENDER, "-b", "--python", os.path.join(HERE, "m04_rigid_mask_dump.py"),
        "--", "--blend", cw1, "--out", dump], os.path.join(pen, "cd_step1_dump.log"), dump))

    # 2) ROI 骨名
    with io.open(dump, encoding="utf-8") as fh:
        rows = json.load(fh)["rows"]
    bones = sorted({r["bone"] for r in rows
                    if (r.get("bone") or "").startswith("下擺_0_")})
    ledger["roi_bones"] = bones
    print("[roi] %d bones: %s" % (len(bones), ",".join(bones)), flush=True)
    if not bones:
        ledger["blocked"] = "dump 里取不到 下擺_0_* 骨名"
        with io.open(os.path.join(pen, "cd_run_ledger.json"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        return 3

    # 3) ROI 对齐
    ledger["steps"].append(run("3_align", [
        BLENDER, "-b", "--python", os.path.join(HERE, "m04_roi_align.py"),
        "--", cw1, align], os.path.join(pen, "cd_step3_align.log"), align))

    # 4) 静态基线：在**无动作**的输入重建件上取（三臂共用）
    ledger["steps"].append(run("4_baseline", [
        BLENDER, "-b", "--python", os.path.join(HERE, "m04_capsule_probe.py"),
        "--", "--blend", a.input, "--targets", align, "--bones", ",".join(bones),
        "--frames", "1:1", "--roi-label", "18_skirt_rigid",
        "--baseline-write", base,
        "--out", os.path.join(pen, "baseline_probe.jsonl"),
        "--meta", os.path.join(pen, "baseline_probe.meta.json")],
        os.path.join(pen, "cd_step4_baseline.log"), base))

    # 5-7) 三臂
    for idx, key in enumerate(("C_W1", "C_W2", "D"), start=5):
        fname, f0, f1 = arms[key]
        arm_path = os.path.join(a.arms_dir, fname)
        # 跑前核 sha（第七条）
        now = sha256(arm_path)
        if now != ledger["arms"][key]["sha256_before"]:
            ledger["arms"][key]["abort"] = "sha_changed_before_run"
            print("[%s] 跑前 sha 变了，该臂作废" % key, flush=True)
            continue
        jsonl = os.path.join(pen, "%s.jsonl" % key)
        meta = os.path.join(pen, "%s.meta.json" % key)
        ledger["steps"].append(run("%d_%s" % (idx, key), [
            BLENDER, "-b", "--python", os.path.join(HERE, "m04_capsule_probe.py"),
            "--", "--blend", arm_path, "--targets", align, "--bones", ",".join(bones),
            "--frames", "%d:%d" % (f0, f1), "--roi-label", "18_skirt_rigid",
            "--baseline", base, "--out", jsonl, "--meta", meta],
            os.path.join(pen, "cd_step%d_%s.log" % (idx, key)), meta))
        import json as _json
        if os.path.exists(meta):
            ledger["gates"][key] = check_frames(meta, f0, f1)
            with io.open(meta, encoding="utf-8") as fh:
                mm = _json.load(fh)
            ledger["arms"][key]["sha256_after"] = sha256(arm_path)
            ledger["arms"][key]["meta_sha256"] = sha256(meta)
            ledger["arms"][key]["meta_bytes"] = os.path.getsize(meta)
            ledger["arms"][key]["pose_source_is_baked"] = (mm.get("cache_state") or {}).get("is_baked")
            ledger["arms"][key]["eval_policy"] = mm.get("eval_policy")

    ledger["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with io.open(os.path.join(pen, "cd_run_ledger.json"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print("[ledger] written", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
