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

产品落盘按批次版本化（`D-189`/`D-203` 的教训）：`<out-dir>/<batch_id>/`，批次已存在且非空
⇒ **拒绝覆盖**（要重跑就换 `batch_id`，或显式 `--allow-overwrite`）；已冻结（只读）的批次
**连 `--allow-overwrite` 也不许覆盖** —— 那一份是某次读数的物证，不是中间产物。
收尾写 `manifest.json`（逐文件 `bytes` / `sha256` / 文本的 `sha256_lf_normalized` / 是否只读）。

用法：
    python reports/subai/M04/scripts/m04_run_cd.py --arms-dir <A3/out/subai/M05/arms> \
        --input <A1/out/subai/M08/rebuild_built.blend> --out-dir <out/subai/M04/penetration> \
        --batch-id round2_324 --freeze
"""
import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time

BLENDER = r"E:\code\Blender\blender-5.2.2-windows-x64\blender.exe"
HERE = os.path.dirname(os.path.abspath(__file__))

# 编码契约是两头的：抓 stdout 的父进程按 UTF-8 解，本进程就得按 UTF-8 写。
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):  # pragma: no cover - 老解释器/被重定向成非 TextIO
    pass


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- 批次版本化

BATCH_RE = re.compile(r"^[A-Za-z0-9._-]{3,64}$")


class BatchRefused(Exception):
    """批次目录不可写（已存在 / 已冻结）。"""


def sanitize_batch_id(raw):
    """批次名只允许 `[A-Za-z0-9._-]{3,64}`。

    宁愿拒也不净化：净化过的名字和用户以为的那个不是同一个，而产物路径要能当物证引用。
    """
    if not isinstance(raw, str) or not BATCH_RE.match(raw or ""):
        raise ValueError("batch_id 只允许 [A-Za-z0-9._-]{3,64}，收到 %r" % (raw,))
    if raw in (".", "..") or raw.strip(".") == "":
        raise ValueError("batch_id 不许是点目录：%r" % (raw,))
    return raw


def _is_frozen(path):
    """只读 = 没有写权限位。Windows 上 `chmod 0o444` 落成只读属性，这条对得上。"""
    try:
        return (os.stat(path).st_mode & 0o200) == 0
    except OSError:
        return False


def prepare_batch_dir(root, batch_id, allow_overwrite=False):
    """建 `<root>/<batch_id>`；已存在且非空时按冻结与否决定放不放行。

    返回 `(batch_dir, created)`。冻结的批次一律拒 —— 覆盖一次就等于把某次读数的物证换掉，
    今天已经发生过一次（`251146e9…` / `be6c0a1c…` 被同路径重跑覆盖）。
    """
    bdir = os.path.join(root, batch_id)
    if os.path.isdir(bdir):
        entries = sorted(e for e in os.listdir(bdir) if not e.startswith("."))
        if entries:
            frozen = [e for e in entries if _is_frozen(os.path.join(bdir, e))]
            if frozen:
                raise BatchRefused(
                    "批次 %s 已冻结（%d/%d 个文件只读），不许覆盖：%s"
                    % (batch_id, len(frozen), len(entries), bdir))
            if not allow_overwrite:
                raise BatchRefused(
                    "批次 %s 已有 %d 个文件，拒绝覆盖（换 batch_id，或显式 --allow-overwrite）：%s"
                    % (batch_id, len(entries), bdir))
        return bdir, False
    os.makedirs(bdir)
    return bdir, True


def file_facts(path, text_cap=8 << 20):
    """逐文件 `bytes` / `sha256`；文本再记 LF 归一后的 sha（本机 `core.autocrlf=true`）。"""
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
            n += len(chunk)
    facts = {"bytes": n, "sha256": h.hexdigest(), "readonly": _is_frozen(path)}
    if n <= text_cap:
        with open(path, "rb") as fh:
            raw = fh.read()
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            pass  # 二进制（.blend）没有「文本 sha」这回事，不记假值
        else:
            facts["sha256_lf_normalized"] = hashlib.sha256(
                raw.replace(b"\r\n", b"\n")).hexdigest()
    return facts


def write_manifest(batch_dir, extra=None):
    """把批次目录里每个文件的事实写进 `manifest.json`（本身不在清单里）。"""
    files = []
    for name in sorted(os.listdir(batch_dir)):
        p = os.path.join(batch_dir, name)
        if not os.path.isfile(p) or name == "manifest.json":
            continue
        row = {"name": name}
        row.update(file_facts(p))
        files.append(row)
    doc = {"spec": "m04_run_cd_manifest/1",
           "batch_id": os.path.basename(batch_dir),
           "written_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "count": len(files), "files": files}
    if extra:
        doc.update(extra)
    with io.open(os.path.join(batch_dir, "manifest.json"), "w",
                 encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return doc


def freeze_tree(batch_dir):
    """把批次里的文件设成只读（物证），返回被冻结的文件名。"""
    frozen = []
    for name in sorted(os.listdir(batch_dir)):
        p = os.path.join(batch_dir, name)
        if os.path.isfile(p):
            os.chmod(p, 0o444)
            frozen.append(name)
    return frozen


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


# 这个计数器数的是 `mmd_type == "RIGID_BODY"` ⇒ **u323 口径（323）**，不是 u324（324）。
# 两者差一个具名对象 `地面_物理`（有 `rigid_body`、无 `mmd_type`）。2026-11-16 18:55 在
# `C@W1.blend` 上实测 = 323，按 324 去判会把这批臂全挡在门外。
EXPECT_RIGIDS_DEFAULT = 323


def admission_checks(health, window_end, expect_rigids=EXPECT_RIGIDS_DEFAULT):
    """一条臂的准入判据（纯函数，离屏可测）。

    四条同时成立才放行，**缺记录一律不过**（「没记录」不等于「没问题」，`D-162`）：

    ① 刚体数 == 期望：动作那一步只许加动作、不许动刚体，324 就该还是 324；
    ② 场景上的 `mask_wired` 记录是 `WIRED`、`constraints_capped` 假、`skipped_count == 0`；
    ③ `cache.is_baked` 严格为 `False`（A1：跑前必须未烘）；
    ④ `scene.frame_end` ≥ 窗口末帧，且场景里真有动作。

    这四条读的是**臂件自己**，不采信任何人的转述或「结构性推断」——上一轮 `actions == []`
    就是在别人的体检结论里被当成「应该没问题」的。
    """
    fails, facts = [], {}
    h = health or {}

    rig = (h.get("rigids") or {}).get("count")
    facts["rigids"] = rig
    if rig is None:
        fails.append("rigids 读不到")
    elif rig != expect_rigids:
        fails.append("rigids=%s ≠ %d" % (rig, expect_rigids))

    mask = h.get("mask_wired") or {}
    facts["mask"] = {k: mask.get(k)
                     for k in ("verdict", "constraints_capped", "skipped_count")}
    if not mask:
        fails.append("场景上没有 mask_wired 记录（缺记录判 UNMEASURED）")
    else:
        if mask.get("verdict") != "WIRED":
            fails.append("mask verdict=%r" % (mask.get("verdict"),))
        if mask.get("constraints_capped"):
            fails.append("constraints_capped=true")
        if (mask.get("skipped_count") or 0) != 0:
            fails.append("skipped_count=%s" % (mask.get("skipped_count"),))

    cache = h.get("cache") or {}
    facts["is_baked"] = cache.get("is_baked")
    if cache.get("is_baked") is not False:
        fails.append("is_baked=%r（A1 要求 false）" % (cache.get("is_baked"),))

    scene = h.get("scene") or {}
    fe = scene.get("frame_end")
    facts["frame_end"] = fe
    if fe is None:
        fails.append("scene.frame_end 读不到")
    elif fe < window_end:
        fails.append("frame_end=%s < 窗口末帧 %d" % (fe, window_end))

    act = (h.get("armature_action") or {}).get("action")
    facts["action"] = act
    facts["actions_all"] = len(h.get("actions_all") or [])
    if not act and not facts["actions_all"]:
        fails.append("场景里没有动作（actions_all=0 且骨架无 action）")

    return {"ok": not fails, "failures": fails, "facts": facts}


def admission_round(a, arms, pen, ledger):
    """三臂各跑一次只读体检并判准入，返回 `(逐臂结果, 全部失败项)`。"""
    results, failures = {}, []
    for key in ("C_W1", "C_W2", "D"):
        fname, _f0, f1 = arms[key]
        out = os.path.join(pen, "health_%s.json" % key)
        led = run("0_health_%s" % key, [
            BLENDER, "-b", "--python", os.path.join(HERE, "m04_delivery_health.py"),
            "--", "--blend", os.path.join(a.arms_dir, fname), "--out", out],
            os.path.join(pen, "cd_step0_health_%s.log" % key), out)
        led["arm"] = key
        ledger["steps"].append(led)
        health = None
        if os.path.exists(out):
            with io.open(out, encoding="utf-8") as fh:
                health = json.load(fh)
        verdict = admission_checks(health, f1)
        verdict["health"] = out.replace("\\", "/")
        results[key] = verdict
        if not verdict["ok"]:
            failures.extend("%s: %s" % (key, f) for f in verdict["failures"])
            print("[admission %s] FAIL %s" % (key, verdict["failures"]), flush=True)
        else:
            print("[admission %s] ok rigids=%s frame_end=%s action=%r is_baked=%s"
                  % (key, verdict["facts"]["rigids"], verdict["facts"]["frame_end"],
                     verdict["facts"]["action"], verdict["facts"]["is_baked"]), flush=True)
    return results, failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms-dir", required=True)
    ap.add_argument("--input", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--batch-id", required=True, help="批次名 [A-Za-z0-9._-]{3,64}，产物落 <out-dir>/<batch-id>/")
    ap.add_argument("--allow-overwrite", action="store_true",
                    help="允许覆盖**未冻结**的非空批次（默认拒绝）")
    ap.add_argument("--freeze", action="store_true", help="收尾把这些产物设成只读")
    a = ap.parse_args()

    try:
        batch_id = sanitize_batch_id(a.batch_id)
    except ValueError as exc:
        print("[refused] %s" % exc, flush=True)
        return 2
    try:
        pen, created = prepare_batch_dir(a.out_dir, batch_id, a.allow_overwrite)
    except BatchRefused as exc:
        print("[refused] %s" % exc, flush=True)
        return 4
    print("[batch] %s (created=%s)" % (pen, created), flush=True)

    dump = os.path.join(pen, "rigid_mask_dump_cd.json")
    align = os.path.join(pen, "roi_align_cd.json")
    base = os.path.join(pen, "baseline_delivery_v1.json")

    arms = {"C_W1": ("C_W1.blend", 1, 240),
            "C_W2": ("C_W2.blend", 1, 832),
            "D": ("D.blend", 1, 832)}

    ledger = {"spec": "m04_run_cd/2", "batch_id": batch_id, "batch_created": created,
              "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "arms_dir": a.arms_dir.replace("\\", "/"), "input": a.input.replace("\\", "/"),
              "input_sha256": sha256(a.input), "arms": {}, "steps": [], "gates": {}}

    # 输入臂的 sha（跑前核，第七条）
    for key, (fname, _f0, _f1) in arms.items():
        p = os.path.join(a.arms_dir, fname)
        ledger["arms"][key] = {"path": p.replace("\\", "/"), "sha256_before": sha256(p),
                               "bytes": os.path.getsize(p)}

    cw1 = os.path.join(a.arms_dir, arms["C_W1"][0])

    def finish():
        """落台账 → （可选）冻结 → 写清单。两条出口共用，免得半路失败时批次里没有清单。"""
        ledger["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with io.open(os.path.join(pen, "cd_run_ledger.json"), "w",
                     encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        frozen = freeze_tree(pen) if a.freeze else []
        man = write_manifest(pen, extra={"frozen": bool(a.freeze),
                                         "frozen_files": frozen,
                                         "blocked": ledger.get("blocked")})
        print("[manifest] %d files, frozen=%s" % (man["count"], bool(a.freeze)), flush=True)

    # 0) 准入体检：**在要测的那些场景上**回读（D-162 / 七条前置的第 1、2 条）。
    #    别人的回读、别人的「结构性推断」都不算 —— 缺记录就判 UNMEASURED，不许当 OK。
    ledger["admission"], failures = admission_round(a, arms, pen, ledger)
    if failures:
        ledger["blocked"] = "准入未过：%s" % "; ".join(failures)
        print("[blocked] %s" % ledger["blocked"], flush=True)
        finish()
        return 5

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
        finish()
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

    finish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
