"""把 `reports/subai/M05/apply_action.md` 的头条数**只用仓里那份**重算一遍。

为什么要有它（`2号` 2026-11-16 20:15 立的同一把尺，`D-228` 第十三条）：报告的数字若只能靠
`out/` 里的中间件复算，干净 checkout 上就只剩结论。这里的输入**全部是 git 里的文件**：

- `reports/subai/M05/arms/20261116_324/summary.json`（物证摘要，含产物回读）
- `reports/subai/M05/arms_audit_324.json`（冻结账本的审计结果）

不许读 `out/`。发现要读 `out/` 才能算的数，就说明那份数不该出现在报告头条里。

    python reports/subai/M05/scripts/verify_report_numbers.py
    退出码：0 全中 / 1 有对不上（逐条打印哪一条）
"""
import io
import json
import os
import subprocess
import sys

REPORT = "reports/subai/M05/apply_action.md"
SUMMARY = "reports/subai/M05/arms/20261116_324/summary.json"
AUDIT = "reports/subai/M05/arms_audit_324.json"

# 报告头条里的数，写死在断言里：改了报告就得同步改这里，改不动就说明报告在说别的
EXPECT_RIGIDS = 324
EXPECT_NEEDED = 10111
EXPECT_ADDED = 8298
EXPECT_ALREADY = 1813
EXPECT_FRAME_END = {"C@W1.blend": 301, "C@W1-rerun.blend": 301, "C@W2.blend": 832,
                    "D.blend": 833, "D-_.blend": 447}
EXPECT_FPS = 24
EXPECT_ARMS = 5

# 报告引用、但按 `out/` 的既定性质不入仓的路径。**豁免不是「不查」，是「可核的转手」**：
# 每条必须写出「这个数由仓里哪一份承载」，而且那句话是 **schema 硬约束**（下面 assert 长度与非空），
# 不是表格里的一行备注 —— `4号` 20:21 的话：白名单会单调增长，加一行是「最小的绿」。
# 所以另加一条棘轮：豁免条数写死，要加一条就得动这个常量（留下 diff 与理由）。
EXPECT_EXEMPTIONS = 3
MIN_REASON_CHARS = 12
ALLOWED_NOT_IN_GIT = {
    "out/subai/M05/arms/20261116_324/manifest.json":
        "冻结账本本身；其 sha 结论由 reports/subai/M05/arms_audit_324.json 承载（本脚本断言 state/listed/drift）",
    "out/subai/M05/arms/20261116_324/readback_arms.json":
        "回读原件；五臂读数已并入 reports/subai/M05/arms/20261116_324/summary.json."
        "artifact_readback（本脚本逐臂断言 u324/掩码/窗口/权限）",
    "out/subai/M05/probe_fcurve_write_shape.json":
        "探针原件；其四条形状读数已写进报告 §十三 的表格，摘要口径由 summary.json 与"
        " evidence_m05_attempt11.json 承载",
}
for _k, _why in ALLOWED_NOT_IN_GIT.items():
    assert isinstance(_why, str) and len(_why) >= MIN_REASON_CHARS, \
        "豁免 %s 的「承载方」理由太短或为空（不许拿空话换一个不查）" % _k
assert len(ALLOWED_NOT_IN_GIT) == EXPECT_EXEMPTIONS, \
    "豁免条数变了（%d != %d）：要加豁免就得连 EXPECT_EXEMPTIONS 一起改，并写清承载方" % (
        len(ALLOWED_NOT_IN_GIT), EXPECT_EXEMPTIONS)


def find_repo_root(start):
    cur = os.path.abspath(start)
    while True:
        if (os.path.isdir(os.path.join(cur, "coordination"))
                and os.path.isdir(os.path.join(cur, "mmdpipe"))):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            raise SystemExit("从 %s 往上走到顶也没找到 coordination/ 与 mmdpipe/" % start)
        cur = parent


ROOT = find_repo_root(os.path.dirname(os.path.abspath(__file__)))
FAILS = []


def check(name, got, want):
    ok = got == want
    print("%-46s %s  got=%r want=%r" % (name, "ok" if ok else "MISMATCH", got, want))
    if not ok:
        FAILS.append(name)


def in_git(rel):
    # `text=True` 必须配 `encoding=`：两端契约，缺一端在 gbk 档会按平台默认码解出乱码/异常
    # （`2号` 今晚在同一处栽过一次；我这次是 `tests/test_subprocess_encoding.py` 的护栏抓到的，
    #  不是自查抓到的 —— 记在这里，别让下一个人以为这行可以省）。
    return subprocess.run(["git", "ls-files", "--error-unmatch", rel],
                          cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace").returncode == 0


def main():
    summary = json.load(io.open(os.path.join(ROOT, SUMMARY), encoding="utf-8"))
    audit = json.load(io.open(os.path.join(ROOT, AUDIT), encoding="utf-8"))

    arms = {a["arm"]: a for a in summary["arms"] if not a["arm"].startswith("CTRL_")}
    check("臂数量（不含 CTRL）", len(arms), EXPECT_ARMS)

    rb = {r["file"]: r for r in summary["artifact_readback"]["arms"]}
    check("回读臂数", len(rb), EXPECT_ARMS)
    check("回读状态", summary["artifact_readback"]["status"], "measured")

    # 两套命名：summary 的 `arm` 是 `C_W1` 这类，产物的 `basename` 是 `C@W1.blend`。
    # 用 basename 当桥，别在断言里硬编码两套名字。
    by_file = {a["artifact"]["basename"]: a for a in arms.values()
               if a["artifact"].get("basename")}

    for name, end in sorted(EXPECT_FRAME_END.items()):
        label = name.replace(".blend", "")
        rec = rb[name]
        check("%s u324（rigid_body 属性）" % label, rec["rigids_u324_rigid_body_attr"],
              EXPECT_RIGIDS)
        mw = rec["mask_wired"]
        check("%s mask_wired.needed" % label, mw["constraints_needed"], EXPECT_NEEDED)
        check("%s mask_wired.added" % label, mw["constraints_added"], EXPECT_ADDED)
        check("%s mask_wired.already" % label, mw["constraints_already_blocked"],
              EXPECT_ALREADY)
        check("%s mask_wired.capped" % label, mw["constraints_capped"], False)
        check("%s mask_wired.readback_mismatch" % label, mw["readback_mismatch"], 0)
        check("%s mask_wired.skipped" % label, mw["skipped_count"], 0)
        check("%s is_baked" % label, rec["is_baked"], False)
        check("%s frame_end" % label, rec["frame_end"], end)
        check("%s fps" % label, rec["fps"], EXPECT_FPS)
        check("%s 产物权限" % label, by_file[name]["artifact"]["frozen_mode"], "0o444")

    check("审计 state", audit["state"], "OK")
    check("审计 two_way_checked", audit["two_way_checked"], True)
    check("审计 listed", audit["listed"], 14)
    check("审计 drift", audit["drift"], [])
    check("审计 only_on_disk", audit["only_on_disk"], [])

    # 报告引用的每个路径都要在 git 里；唯一的豁免写在上面的常量里
    text = io.open(os.path.join(ROOT, REPORT), encoding="utf-8").read()
    import re
    refs = sorted({p for p in re.findall(r"[\w/.\-]+\.(?:py|json|md)", text) if "M05" in p})
    for rel in refs:
        if rel in ALLOWED_NOT_IN_GIT:
            print("%-46s skip  %s\n%54s理由：%s"
                  % ("git ls-files", rel, "", ALLOWED_NOT_IN_GIT[rel]))
            continue
        check("in-git %s" % rel, in_git(rel), True)

    print("\n报告头条数：%s（%d 条对不上）"
          % ("全部可由仓内文件重算" if not FAILS else "有对不上", len(FAILS)))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    raise SystemExit(main())
