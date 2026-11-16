"""M05 attempt 11：324 批次版本化+冻结端到端读数 + Blender 5.2 `Action.fcurves` 形状修复。

口径：
  - 文本按 `lf_normalized_v1` 算 sha（先 CRLF→LF），二进制按原字节；
  - artifact 带 snapshot（`coordination/evidence_store.py` 自证：同写 path/sha/snapshot）；
  - 闸门包交给 `gates.check_bundle` 判，不自验。
"""
import hashlib
import json
import os
import sys

def find_repo_root(start):
    """往上走到有 `coordination/` 与 `mmdpipe/` 的那一层；走不到就把起点打出来再死。

    不写死 `dirname` 次数：同一份脚本既可能在 `out/subai/M05/`（产物树）也可能在
    `reports/subai/M05/scripts/`（仓库），深度不同，写死必然有一边算错，而算错的样子是
    `ImportError`（看起来像「这个模块不存在」）。
    """
    cur = os.path.abspath(start)
    while True:
        if (os.path.isdir(os.path.join(cur, "coordination"))
                and os.path.isdir(os.path.join(cur, "mmdpipe"))):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            raise SystemExit("从 %s 往上走到顶也没找到 coordination/ 与 mmdpipe/"
                             % os.path.abspath(start))
        cur = parent


ROOT = find_repo_root(os.path.dirname(os.path.abspath(__file__)))

A3 = ROOT
sys.path.insert(0, A3)

from coordination import evidence as ev            # noqa: E402
from coordination import evidence_store as store    # noqa: E402
from coordination import gates                      # noqa: E402

TEXT_EXT = {".py", ".md", ".json", ".jsonl", ".txt"}
OUT = os.path.join(A3, "reports", "subai", "M05", "evidence_m05_attempt11.json")


def _has_flag(name):
    return name in sys.argv


def _arg_value(name):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None

FILES = [
    "mmdpipe/apply_action.py",
    "tests/test_apply_action.py",
    "reports/subai/M05/apply_action.md",
    "reports/subai/M05/arms/20261116_324/summary.json",
]

ARTIFACTS = [
    "reports/subai/M05/apply_action.md",
    "reports/subai/M05/arms/20261116_324/summary.json",
]


def sha(path, text_basis):
    raw = open(path, "rb").read()
    if text_basis:
        raw = raw.replace(b"\r\n", b"\n")
    return hashlib.sha256(raw).hexdigest()


def main():
    files = []
    for rel in sorted(FILES):
        p = os.path.join(A3, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            raise SystemExit("缺文件：" + p)
        files.append({"path": rel, "tracked": True,
                      "sha256": sha(p, os.path.splitext(rel)[1].lower() in TEXT_EXT)})

    arts, snaps = [], []
    for rel in sorted(ARTIFACTS):
        row = store.snapshot_artifact(os.path.join(A3, rel.replace("/", os.sep)))
        arts.append({"path": rel, "sha256": row["sha256"], "version": "m05-apply-action-324",
                     "snapshot": row["snapshot"]})
        snaps.append({"path": rel, "snapshot": row["snapshot"]})

    summary = json.load(open(os.path.join(A3, "reports", "subai", "M05", "arms",
                                          "20261116_324", "summary.json"), encoding="utf-8"))
    arms = {a["arm"]: a for a in summary["arms"]}
    rb = summary["artifact_readback"]

    arm_lines = ["%-16s %s   sha256=%s  bytes=%s  mode=%s  frame_end=%s  action=%s  fcurves=%s  is_baked=%s"
                 % (k, v["artifact"]["basename"], v["artifact"]["sha256"],
                    v["artifact"]["bytes"], v["artifact"]["frozen_mode"],
                    (v["window"] or {}).get("frame_end"),
                    (v["action"] or {}).get("frame_range"),
                    (v["action"] or {}).get("fcurves"),
                    (v["cache"] or {}).get("is_baked"))
                 for k, v in sorted(arms.items()) if not k.startswith("CTRL_")]
    interface_text = "\n".join([
        "给 2号（未烘臂件，测 C/D 组）：目录 "
        r"E:\code\mmdpipe-ai\A3\out\subai\M05\arms\20261116_324",
    ] + arm_lines + [
        "五份全 0o444、全 is_baked=false；烘过的那份这份证据里没有（要 4号 的 stage_bake 真跑并存新路径）。",
        "给 4号（bake 首测）：建议 C@W1.blend，frame_end=301，--frame 1..24 落在窗口内；"
        "0o444 ⇒ 就地 save 会失败，要留副本请起新路径。",
        "给 1号（构建链接入）：from mmdpipe.apply_action import apply_action, fcurves_of；"
        "CLI 形如 blender -b <blend> -P mmdpipe/apply_action.py -- --owner '模块|树' --vmd A.vmd "
        "--preset P.json --out-dir <根> --batch-id <批次> --freeze --json R.json；判红 exit 3 且不写件。",
    ])

    payload = {
        "spec": "evidence/1",
        "task_id": "M05",
        "attempt": 11,
        "status": "PARTIAL",
        "hash_basis": "lf_normalized_v1",
        "truth_tier": "T2",
        "scope": "两件：(1) D-189 / D-203 那条「版本化只算代码就绪、端到端未验」结账——"
                 "324 件上七臂真跑，五份产物版本化落盘 + --freeze + 拒绝覆盖，并做只读产物回读；"
                 "(2) 回读撞出 Blender 5.2 的分层动作形状（Action.fcurves 在对存盘件读回时不存在），"
                 "修 mmdpipe/apply_action.py 三处调用点并补离屏 5 条 + 一条反向控制。"
                 "不含：烘过的件、拿存盘臂件再跑一次 apply_action、content_digest_v1。",
        "files": files,
        "tests": [
            {"cmd": "python -m unittest tests.test_apply_action", "exit": 0,
             "passed": 41, "failed": 0, "skipped": 0},
            {"cmd": "python -m unittest discover -s tests", "exit": 0,
             "passed": 632, "failed": 0, "skipped": 1},
            {"cmd": "PYTHONUTF8=1 python -m unittest discover -s tests", "exit": 0,
             "passed": 632, "failed": 0, "skipped": 1},
            {"cmd": "PYTHONIOENCODING=gbk python -m unittest discover -s tests", "exit": 0,
             "passed": 632, "failed": 0, "skipped": 1},
            {"cmd": "python out/subai/M05/ctrl_fcurves_shape.py  (反向控制：退回旧写法红 3 条，还原全绿)",
             "exit": 0, "passed": 1, "failed": 0, "skipped": 0},
        ],
        "artifacts": arts,
        "known_risks": [
            "烘过的件没给：apply_action 只到「未烘」为止，烘焙是 4号 的 stage_bake()；"
            "本批不涉及，也不拿「另存一次」冒充烘焙（2号 的 M08 T3 仍缺这一份）",
            "拿一件已经存过盘的臂件再跑一次 apply_action **没跑过**：fcurves_of 的修法只在离屏"
            "哑对象上验过形状；真机上这一条要窗口，324 批次之后窗口一直在 2号 / 1号 手里",
            "content_digest_v1 没做，臂记录里连这个字段都没有（bodies[] 要 1号 的重建回读，"
            "D-186 明令不造第二份读刚体的实现）——是「已知未做」，不是「留了 null」",
            "D 臂尾帧未测：源第 832 帧落在 action 833，在预注册测量窗口 1..832 之外；不裁源（D-186）",
            "C@W2 的 302..832 是末帧定格（回读末键帧 301），不是动作本身；D vs C 只在该窗口同段比较",
            "fps 被按住不改：update_scene_settings=False，五臂 24→24；A6 是红判据"
            "（刚体步长 dt=1/fps），反控 CTRL_fps_changed 只红 A6 一条",
            ".blend 字节复现性不稳定（第二次实测：同一输入两遍 sha 不同、六个回读字段逐项相同）⇒ "
            "「字节变了=有人改过」永远不成立，幂等只能判在回读内容上",
            "回读只覆盖场景态与刚体计数（u324=324、mask_wired 四条、is_baked/is_outdated、"
            "point_cache_range），**不解算、不测量**：本份只交场景态回读，不宣称任何解算类结论，"
            "所以 fresh_solve_confirmed 不填（填了就等于替解算结论背书）",
            "324 件输入用的是 run 目录那份副本（1号 后来又冻结了一份同 sha 的 frozen/ 件）；"
            "字节相同，但严格说输入路径不是冻结路径，凡按路径判身份的用法要改用 sha",
        ],
        "interface": interface_text,
        "measurements": {
            "input_blend": summary["input"],
            "driver": summary["driver"],
            "arms": {k: {"verdict": v["verdict"],
                         "checks": v["checks"],
                         "frozen_mode": v["artifact"]["frozen_mode"],
                         "out_blend_sha256": v["artifact"]["sha256"],
                         "out_blend_bytes": v["artifact"]["bytes"],
                         "action": v["action"],
                         "window": v["window"],
                         "cache_is_baked": (v["cache"] or {}).get("is_baked"),
                         "cache_is_outdated": (v["cache"] or {}).get("is_outdated"),
                         "point_cache_range": (v["cache"] or {}).get("point_cache_range"),
                         "fps_before": (v["scene"] or {}).get("fps_before"),
                         "fps_after": (v["scene"] or {}).get("fps_after"),
                         "source_sha256": (v["source"] or {}).get("sha256"),
                         "source_frame_range": (v["source"] or {}).get("frame_range")}
                     for k, v in arms.items()},
            "artifact_readback": {
                "status": rb["status"],
                "read_only": rb.get("read_only"),
                "per_arm": {a["file"]: {"rigids_u324": a["rigids_u324_rigid_body_attr"],
                                        "mask_verdict": (a["mask_wired"] or {}).get("verdict"),
                                        "mask_needed": (a["mask_wired"] or {}).get("constraints_needed"),
                                        "mask_added": (a["mask_wired"] or {}).get("constraints_added"),
                                        "mask_already": (a["mask_wired"] or {}).get("constraints_already_blocked"),
                                        "mask_capped": (a["mask_wired"] or {}).get("constraints_capped"),
                                        "mask_readback_mismatch": (a["mask_wired"] or {}).get("readback_mismatch"),
                                        "is_baked": a["is_baked"],
                                        "is_outdated": a["is_outdated"],
                                        "fps": a["fps"],
                                        "frame_end": a["frame_end"],
                                        "actions": [{"name": x["name"], "fcurves": x["fcurves"],
                                                     "via": x["fcurves_via"],
                                                     "frame_range": x["frame_range"]}
                                                    for x in a["actions"]]}
                            for a in rb["arms"]},
            },
            "byte_reproducibility": summary["byte_reproducibility"],
            "offline_reverse_controls": {
                "legacy_fcurves_only": "新测试绿（旧形状照读）",
                "layered_fcurves_only": "新测试绿（channelbags 求和 700+25=725）",
                "break_fcurves_of_back": "反向控制：新测试红 3 条（还原后 41 条全绿）",
                "zero_fcurves": "只红 A1_action_applied",
            },
        },
    }

    canonical = ev.canonical_bytes(ev.normalize(payload))
    # 默认输出是**已提交的证据**：重跑一次就会静默改写交付件，所以默认拒绝覆盖，
    # 要覆盖必须显式 `--force`；`--out` 只用于验证（写到临时路径，产物树不留东西）。
    out_path = _arg_value("--out") or OUT
    if os.path.exists(out_path) and not _has_flag("--force"):
        raise SystemExit("拒绝覆盖已有证据：%s（确需重写加 --force）" % out_path)
    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(canonical)
    print("写出:", out_path, len(canonical), "bytes")
    print("digest:", ev.digest(payload))
    print("文件 sha256:", hashlib.sha256(open(out_path, "rb").read()).hexdigest())

    bundle = {
        "evidence_check_exit": 0,
        "coverage_check": "PASS",
        # 验收权在 D0，我不自验 ⇒ NOT_APPLICABLE（PASS / FAIL / NOT_APPLICABLE 三选一）
        "acceptance_result": "NOT_APPLICABLE",
        "truth_tier": "T2",
        "pose_source": "n/a",
        "fresh_solve_confirmed": None,
        "module_provenance": {"m05_step": os.path.join(A3, "mmdpipe", "apply_action.py")},
        "snapshot_paths": snaps,
        "resource_lease_valid": None,
    }
    result = gates.check_bundle(bundle, payload, worktree=A3)
    print("\n== 闸门包 ==")
    print("  ok:", result["ok"], "reason_code:", result["reason_code"])
    for c in result["checks"]:
        print("   [%s] %-12s %s" % ("ok" if c["ok"] else "NO", c["code"], c["detail"]))
    # 闸门包必须跟着 `--out` 走。第一版只重定向了证据、闸门仍写默认路径，
    # 于是「只验证一次」就把已提交的 `gate_m05_attempt11.json` 改了一个 snapshot 路径
    # （实测被 git status 抓到、已还原）。验证性运行要能**完全落在临时目录里**。
    gate_out = os.path.join(os.path.dirname(os.path.abspath(out_path)), "gate_m05_attempt11.json")
    with open(gate_out, "w",
              encoding="utf-8") as fh:
        json.dump(bundle, fh, ensure_ascii=False, indent=2)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
