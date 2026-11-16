"""M05 批次驱动：一条命令跑完七臂（四臂 + 对照 + 两条反控），落版本化路径并冻结。

为什么要脚本：`D-188`（跑 Blender 前第一句 assert-owner）与 `D-189`（版本化落盘 + 不覆盖 +
冻结只读）都是「靠人记得就会漏」的规矩。写进这里，漏了就是进程起不来。

用法（**先在别的终端 `python -m coordination.lock acquire --owner '模块负责3|A3'`**）：

    python reports/subai/M05/scripts/run_arms.py \
        --batch-id 20261116_1900 \
        --in-blend <交付场景.blend> \
        --blender "E:\\code\\Blender\\blender-5.2.2-windows-x64\\blender.exe"

`--dry-run` 只打印将要执行的命令与目标路径（不起 Blender、不需要锁）。
本脚本**不 acquire、不 release**：锁的取得与放回是显式的，留给调用者。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))))          # scripts → M05 → subai → reports → A3
sys.path.insert(0, ROOT)

from mmdpipe.apply_action import versioned_out_path  # noqa: E402
from coordination import lock as lock_mod            # noqa: E402

OWNER = "模块负责3|A3"
ARMS_DIR = os.path.join(ROOT, "out", "subai", "M05", "arms")
PRESET = "presets/feiying.json"

# 臂表：动作源、窗口操作、标签、附注。四臂输入同一份场景，臂间只差源与窗口。
ARMS = [
    {"name": "C_W1", "role": "C@W1", "vmd": r"E:\dsh pr\woker2\out\B_aligned.vmd", "extra": []},
    {"name": "C_W2", "role": "C@W2", "vmd": r"E:\dsh pr\woker2\out\B_aligned.vmd",
     "extra": ["--hold-until", "832"]},
    {"name": "D", "role": "D", "vmd": r"E:\dsh pr\woker2\kafuka_all\vmd\原神摇_merged.vmd",
     "extra": ["--note", "预注册 D 臂：原神摇 832 帧全长（b872fda7…）；源第 832 帧落在 action 833，"
                        "测量窗口 1..832 外，尾帧未测"]},
    {"name": "D_ctrl_447", "role": "D-对照", "vmd": r"E:\dsh pr\woker2\out\原神摇_merged.vmd",
     "extra": ["--note", "447 帧原片版，非预注册素材，不进 D 的判词"]},
    {"name": "C_W1_rerun", "role": "C@W1-rerun", "src_from": "C_W1",
     "vmd": r"E:\dsh pr\woker2\out\B_aligned.vmd",
     "extra": ["--note", "幂等复跑：输入是 C_W1 自己的产物，同一动作再应用一次"]},
    {"name": "CTRL_no_addon", "role": "反控-无插件闸门",
     "vmd": r"E:\dsh pr\woker2\out\B_aligned.vmd",
     "extra": ["--skip-ensure", "--note", "场景级反控：关掉插件闸门，应当判红且不写交付件"]},
    {"name": "CTRL_fps_changed", "role": "反控-fps被改",
     "vmd": r"E:\dsh pr\woker2\out\B_aligned.vmd",
     "extra": ["--allow-scene-settings", "--note", "场景级反控：允许导入改 fps，A6 应当判红且不写交付件"]},
]


def build_commands(batch_id, in_blend, blender, allow_overwrite=False):
    """把臂表展开成具体命令 + 目标路径。纯计算，不起进程。"""
    cmds, targets = [], {}
    for arm in ARMS:
        out = versioned_out_path(ARMS_DIR, batch_id, arm["role"])
        targets[arm["name"]] = out
        if os.path.exists(out) and not allow_overwrite:
            raise SystemExit("拒绝：目标已存在（%s）—— 臂件是物证，换 --batch-id 或显式 --allow-overwrite"
                             % out)
        src = (targets.get(arm["src_from"]) if arm.get("src_from") else None) or in_blend
        # 复跑臂的输入是**本批次**刚产出的 C_W1
        if arm.get("src_from"):
            src = versioned_out_path(ARMS_DIR, batch_id, "C@W1")
        rec = os.path.join(ARMS_DIR, batch_id, arm["name"] + ".json")
        cmd = [blender, "-b", src, "--python-exit-code", "3",
               "-P", os.path.join(ROOT, "mmdpipe", "apply_action.py"), "--",
               "--owner", OWNER,
               "--vmd", arm["vmd"], "--preset", PRESET,
               "--out-dir", ARMS_DIR, "--batch-id", batch_id,
               "--arm-role", arm["role"], "--freeze",
               "--json", rec] + list(arm["extra"])
        cmds.append({"arm": arm["name"], "cmd": cmd, "expect_rc": 3 if arm["name"].startswith("CTRL_") else 0,
                     "record": rec, "out_blend": out})
    return cmds


def read_health(path):
    """读交付件体检 JSON，判断这份场景**能不能当本步骤的输入**。

    一条我自己的教训（2026-11-16 18:51，写进代码前差点酿成误伤）：本步骤的输入**通常
    `actions == []`** —— 那正是我要干的事（把动作装上去）。所以**不能拿「有没有动作」
    当输入闸门**，那会把「我该修的件」判成「不许跑」。输入的闸门只有两条：

    1. **有刚体世界**（物理先建好，见 `2号` 的准入 ②）；
    2. 输入若已带动作 ⇒ **只警告不拦**：本步骤是「先清再装」，幂等性已在 `C_W1_rerun` 上验过。

    真正该断言「有动作」的是**产物**，那由臂记录里的 `A1/A3/A6` 判据负责（见 `check_arm_record`）。
    """
    # `utf-8-sig`：别人家的工具在 Windows 上落 JSON 很可能带 BOM（PowerShell 的
    # `Set-Content -Encoding utf8` 就带），裸 `utf-8` 会直接 `Unexpected UTF-8 BOM` 崩掉。
    with open(path, encoding="utf-8-sig") as fh:
        doc = json.load(fh)
    actions = None
    for k in ("actions", "action_names", "actions_all"):
        if isinstance(doc.get(k), list):
            actions = doc[k]
            break
    has_physics = doc.get("has_physics", doc.get("rigidbody_world"))
    warnings = []
    if actions:
        warnings.append("输入已带 %d 条动作：本步会先清再装（幂等），不是问题" % len(actions))
    if has_physics is False:
        return {"ok": False, "why": "输入没有刚体世界：物理还没建，本步骤不该在这份上跑",
                "actions": actions, "warnings": warnings}
    return {"ok": True,
            "why": "有刚体世界" if has_physics else "体检未报 has_physics（不拦，但要核）",
            "actions": actions, "warnings": warnings}


def check_arm_record(path, expect_verdict):
    """产物侧判据：**这里**才要求有动作。没有记录 / 判词不符 / 红项 ⇒ 记一笔。"""
    if not os.path.exists(path):
        return {"ok": False, "why": "没有臂记录（进程可能没跑完）"}
    with open(path, encoding="utf-8-sig") as fh:
        rec = json.load(fh)
    reds = [c["id"] for c in (rec.get("checks") or []) if not c["ok"]]
    verdict = rec.get("verdict")
    ok = verdict == expect_verdict and (not reds if expect_verdict == "READY" else True)
    return {"ok": ok, "verdict": verdict, "expect": expect_verdict, "red_checks": reds}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="run_arms", description="M05 批次驱动（版本化 + 冻结 + 锁闸门）")
    ap.add_argument("--batch-id", required=True)
    ap.add_argument("--in-blend", required=True, help="输入交付场景（四臂同一份）")
    ap.add_argument("--blender", default=r"E:\code\Blender\blender-5.2.2-windows-x64\blender.exe")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-overwrite", action="store_true")
    ap.add_argument("--health-json", default=None,
                    help="交付件体检输出（2号 m04_delivery_health.py 的 JSON）；给了就先看有没有动作")
    args = ap.parse_args(argv)

    health = None
    if args.health_json:
        health = read_health(args.health_json)
        print("体检：%s —— %s" % ("通过" if health["ok"] else "不通过", health["why"]))
        if not health["ok"] and not args.dry_run:
            raise SystemExit("拒绝起臂：输入场景没通过体检（上面那句）。先在输入上把动作装好再说。")

    cmds = build_commands(args.batch_id, args.in_blend, args.blender, args.allow_overwrite)
    if args.dry_run:
        for c in cmds:
            print("[dry] %-16s expect_rc=%d\n      %s" % (c["arm"], c["expect_rc"],
                                                          " ".join('"%s"' % p if " " in p else p
                                                                   for p in c["cmd"])))
        print("\n共 %d 臂；目标目录 %s" % (len(cmds), os.path.join(ARMS_DIR, args.batch_id)))
        return 0

    # 不起 Blender 就先确认锁是我的（D-188：不是自己持锁就一个进程都不许起）
    lock_mod.assert_owner(OWNER)
    results = []
    for c in cmds:
        t0 = time.time()
        proc = subprocess.run(c["cmd"], capture_output=True)
        out = (proc.stdout or b"").decode("utf-8", "replace")
        err = (proc.stderr or b"").decode("utf-8", "replace")
        rec = {"arm": c["arm"], "rc": proc.returncode, "expect_rc": c["expect_rc"],
               "ok": proc.returncode == c["expect_rc"],
               "seconds": round(time.time() - t0, 1),
               "record": c["record"],
               "artefact_check": check_arm_record(
                   c["record"], "BLOCKED" if c["arm"].startswith("CTRL_") else "READY"),
               "stdout_tail": out.strip().splitlines()[-2:],
               "stderr_tail": err.strip().splitlines()[-2:]}
        results.append(rec)
        print("%-16s rc=%d（期望 %d）%s" % (c["arm"], proc.returncode, c["expect_rc"],
                                           "" if rec["ok"] else "   <<< 不符"))

    report = {"schema": "m05.batch/1", "batch_id": args.batch_id, "in_blend": args.in_blend,
              "owner": OWNER, "health": health, "arms": results}
    os.makedirs(os.path.join(ARMS_DIR, args.batch_id), exist_ok=True)
    path = os.path.join(ARMS_DIR, args.batch_id, "batch_report.json")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    bad = [r["arm"] for r in results if not r["ok"] or not r["artefact_check"]["ok"]]
    print("\n批次报告：%s" % path)
    print("不符期望的臂：%s" % (bad or "无"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
