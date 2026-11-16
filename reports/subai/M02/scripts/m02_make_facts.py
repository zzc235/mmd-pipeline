# -*- coding: utf-8 -*-
"""把「一次锁窗口里的多份读数」合成 `content_digest_v1` 需要的 facts（纯 Python，fail-closed）。

为什么要它：`content_digest_v1` 的 included 字段散在两处 —— 逐刚体/掩码/动作/场景来自回读
（`m02_m08_readback.py`），`chain_ratio` 来自重建报告（`rebuild_report.json` 的 `build.metrics`）。
合成本身就是一处**新的判据**：合错了、少合一项，强摘要就会「看起来合格」。

所以本脚本只做一件事，并且**缺任何一项就拒绝产出 facts**（不填默认值、不猜）：

    python m02_make_facts.py --readback <readback.json> --rebuild-report <rebuild_report.json> \
        --out <facts.json> [--action-name <name>]

拒绝码（exit 2）：`FACTS_MISSING`（列出缺哪些键）、`FACTS_BODIES_EMPTY`、
`FACTS_BODY_COUNT_MISMATCH`（`rigids != len(bodies)`）、`FACTS_ACTION_AMBIGUOUS`
（多份 action 且没给 `--action-name`）、`FACTS_ACTION_NOT_FOUND`。

自检（`--selftest`）：正控 1 + 负控 5，含「少一条 body 必须拒」与「chain_ratio 缺必须拒」。
"""

import argparse
import io
import json
import sys

# GBK 控制台下中文/符号会让脚本崩在打印上（总控 18:18）：入口统一 UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                        # noqa: BLE001
        pass

VERSION = "m02_make_facts_v1"
MASK_FIELDS = ("verdict", "constraints_capped", "skipped_count", "constraints_needed",
               "constraints_added", "constraints_already_blocked", "readback_mismatch")


class FactsError(Exception):
    def __init__(self, reason_code, message, missing=None):
        Exception.__init__(self, "[%s] %s" % (reason_code, message))
        self.reason_code = reason_code
        self.message = message
        self.missing = list(missing or [])


def _mask_of(readback):
    """掩码七项：优先进 `mask_wired_record`，退回 `mask_triple`/`mask_report`；缺哪项就报哪项。"""
    sources = [readback.get("mask_wired_record"), readback.get("mask_triple"),
               readback.get("mask_report")]
    out, missing = {}, []
    for field in MASK_FIELDS:
        value = None
        for src in sources:
            if isinstance(src, dict) and src.get(field) is not None:
                value = src[field]
                break
        if value is None:
            missing.append("mask.%s" % field)
        out[field] = value
    return out, missing


def _scene_of(readback):
    scene = readback.get("scene_now")
    if not isinstance(scene, dict):
        return None, ["scene"]
    missing = [k for k in ("frame_start", "frame_end", "fps") if scene.get(k) is None]
    if missing:
        return None, ["scene.%s" % k for k in missing]
    return {"frame_start": scene["frame_start"], "frame_end": scene["frame_end"],
            "fps": scene["fps"]}, []


def _action_of(readback, want_name):
    active = readback.get("active_action")
    if want_name:
        for act in readback.get("actions") or []:
            if act.get("name") == want_name:
                return {"name": act["name"], "frame_range": act.get("frame_range")}, []
        return None, ["action:%s" % want_name]
    if isinstance(active, dict) and active.get("name"):
        return {"name": active["name"], "frame_range": active.get("frame_range")}, []
    actions = [a for a in (readback.get("actions") or []) if a.get("name")]
    if len(actions) == 1:
        return {"name": actions[0]["name"], "frame_range": actions[0].get("frame_range")}, []
    if not actions:
        return None, ["action"]
    raise FactsError("FACTS_ACTION_AMBIGUOUS",
                     "场景里有 %d 份 action 且没有活跃动作：给 --action-name 指定用哪一份（%r）"
                     % (len(actions), [a["name"] for a in actions][:6]))


def build_facts(readback, rebuild_report=None, action_name=None):
    """合成 facts；缺料就抛 `FactsError`。返回 `(facts, notes)`。"""
    facts, missing, notes = {}, [], []
    rigids = readback.get("rigids_u324_rigid_body_attr")
    bodies = readback.get("bodies")
    if rigids is None:
        missing.append("rigids")
    if not isinstance(bodies, list) or not bodies:
        raise FactsError("FACTS_BODIES_EMPTY",
                         "回读里没有逐刚体属性（bodies 缺失或为空）：强摘要算不出来，不拿聚合量冒充")
    if isinstance(rigids, int) and rigids != len(bodies):
        raise FactsError("FACTS_BODY_COUNT_MISMATCH",
                         "rigids=%d 但 bodies 只有 %d 条：逐刚体回读不完整" % (rigids, len(bodies)))
    facts["rigids"] = rigids
    facts["bodies"] = bodies
    facts["constraints_by_type"] = readback.get("constraints_by_type")
    if not isinstance(facts["constraints_by_type"], dict):
        missing.append("constraints_by_type")

    mask, mask_missing = _mask_of(readback)
    missing.extend(mask_missing)
    facts["mask"] = mask

    scene, scene_missing = _scene_of(readback)
    missing.extend(scene_missing)
    facts["scene"] = scene

    action, action_missing = _action_of(readback, action_name)
    missing.extend(action_missing)
    facts["action"] = action

    cache = readback.get("cache")
    if isinstance(cache, dict):
        facts["cache"] = {"is_baked": cache.get("is_baked"),
                          "is_outdated": cache.get("is_outdated")}
        if facts["cache"]["is_baked"] is None:
            missing.append("cache.is_baked")
        if facts["cache"]["is_outdated"] is None:
            missing.append("cache.is_outdated")
    else:
        facts["cache"] = None
        missing.append("cache")

    metrics = ((rebuild_report or {}).get("build") or {}).get("metrics") or {}
    chain_ratio = metrics.get("chain_ratio")
    if chain_ratio is None:
        chain_ratio = (rebuild_report or {}).get("chain_ratio")
    if chain_ratio is None:
        missing.append("chain_ratio")
    facts["chain_ratio"] = chain_ratio

    if missing:
        raise FactsError("FACTS_MISSING",
                         "facts 缺这 %d 项：%r（不填默认值，回读那边补上再来）"
                         % (len(missing), missing), missing=missing)

    notes.append("rigids/bodies/scene/action/mask/cache 来自回读 %s" % readback.get("blend"))
    if rebuild_report:
        notes.append("chain_ratio 来自重建报告 build.metrics（同一次窗口、同一棵树）")
    if readback.get("body_read_errors"):
        notes.append("回读有 %d 条刚体读失败（已反映在 bodies 缺项上）"
                     % len(readback["body_read_errors"]))
    return facts, notes


def _mini_readback(n_bodies=3):
    bodies = [{"name": "000_a", "parent_bone": "下擺_11_7", "mass": 1.0, "kinematic": True,
               "collision_shape": "BOX", "collision_collections": [1] + [0] * 19,
               "friction": 0.5},
              {"name": "001_b", "parent_bone": "下擺_11_8", "mass": 1.0, "kinematic": True,
               "collision_shape": "BOX", "collision_collections": [1] + [0] * 19,
               "friction": 0.5},
              {"name": "002_ground", "parent_bone": None, "mass": 1.0, "kinematic": False,
               "collision_shape": "CONVEX_HULL", "collision_collections": [1] + [0] * 19,
               "friction": 0.5}][:n_bodies]
    return {"blend": r"E:\x\rebuild_built.blend", "rigids_u324_rigid_body_attr": 3,
            "bodies": bodies, "body_read_errors": [],
            "constraints_by_type": {"COPY_ROTATION": 10, "LIMIT_ROTATION": 2},
            "mask_triple": {"verdict": "WIRED", "constraints_capped": False, "skipped_count": 0,
                            "constraints_needed": 10111, "constraints_added": 8298,
                            "constraints_already_blocked": 1813, "readback_mismatch": 0},
            "mask_report": {"readback_mismatch": 0},
            "scene_now": {"fps": 24, "fps_base": 1.0, "frame_start": 1, "frame_end": 240},
            "cache": {"is_baked": False, "is_outdated": True},
            "actions": [{"name": "B_aligned", "frame_range": [1.0, 300.0]}],
            "active_action": {"name": "B_aligned", "frame_range": [1.0, 300.0]}}


def selftest():
    cases = []
    facts, notes = build_facts(_mini_readback(), {"build": {"metrics": {"chain_ratio": 0.946}}})
    cases.append(("正控：三份读数合成 facts", (facts["rigids"], len(facts["bodies"])), (3, 3)))
    cases.append(("正控：mask 七项齐", sorted(facts["mask"]), sorted(MASK_FIELDS)))

    def expect(mutator, rebuild=None, action_name=None):
        rb = _mini_readback()
        mutator(rb)
        try:
            build_facts(rb, rebuild if rebuild is not None else
                        {"build": {"metrics": {"chain_ratio": 0.946}}}, action_name)
        except FactsError as exc:
            return exc.reason_code
        return "NO_ERROR"

    cases.append(("负控：bodies 清空 ⇒ 拒",
                  expect(lambda r: r.__setitem__("bodies", [])), "FACTS_BODIES_EMPTY"))
    cases.append(("负控：少一条 body（rigids=3, bodies=2）⇒ 拒",
                  expect(lambda r: (r.__setitem__("bodies", r["bodies"][:2]))),
                  "FACTS_BODY_COUNT_MISMATCH"))
    cases.append(("负控：mask 少 readback_mismatch ⇒ 拒",
                  expect(lambda r: (r["mask_triple"].pop("readback_mismatch"),
                                    r["mask_report"].pop("readback_mismatch"))), "FACTS_MISSING"))
    cases.append(("负控：没有 chain_ratio ⇒ 拒",
                  expect(lambda r: None, rebuild={}), "FACTS_MISSING"))
    cases.append(("负控：多份 action 且无活跃 ⇒ 拒",
                  expect(lambda r: (r.__setitem__("active_action", None),
                                    r.__setitem__("actions", [{"name": "A", "frame_range": [1, 2]},
                                                              {"name": "B", "frame_range": [1, 3]}]))),
                  "FACTS_ACTION_AMBIGUOUS"))
    def multi_actions(r):
        r["active_action"] = None
        r["actions"] = [{"name": "A", "frame_range": [1, 2]},
                        {"name": "B_aligned", "frame_range": [1, 300]}]

    cases.append(("正控：多份 action + `--action-name` 指定 ⇒ 通过",
                  expect(multi_actions, action_name="B_aligned"), "NO_ERROR"))
    cases.append(("负控：指定的 action 不存在 ⇒ 拒",
                  expect(multi_actions, action_name="nope"), "FACTS_MISSING"))

    bad = 0
    for label, got, want in cases:
        ok = got == want
        print("  [%s] %-46s 期望 %r，实际 %r" % ("ok" if ok else "NO", label, want, got))
        bad += 0 if ok else 1
    print("facts 合成自检 %d 条，失败 %d 条" % (len(cases), bad))
    return 0 if bad == 0 else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=VERSION)
    ap.add_argument("--readback", help="m02_m08_readback.py 的产物")
    ap.add_argument("--rebuild-report", help="同一次重建的 rebuild_report.json")
    ap.add_argument("--action-name", help="场景里有多份 action 时必须指定")
    ap.add_argument("--out", help="facts 输出路径（喂给 m02_content_digest.py --facts）")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not (args.readback and args.out):
        ap.error("需要 --readback 与 --out（或 --selftest）")
    readback = json.load(io.open(args.readback, encoding="utf-8-sig"))
    rebuild = None
    if args.rebuild_report:
        rebuild = json.load(io.open(args.rebuild_report, encoding="utf-8-sig"))
    try:
        facts, notes = build_facts(readback, rebuild, action_name=args.action_name)
    except FactsError as exc:
        print("拒绝：%s" % exc)
        return 2
    with io.open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(facts, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("FACTS %s  rigids=%d bodies=%d" % (args.out, facts["rigids"], len(facts["bodies"])))
    for note in notes:
        print("  · %s" % note)
    print("  下一步：python reports/subai/M02/scripts/m02_content_digest.py --facts %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
