"""阶段 E：决策词表（`coordination/decision_taxonomy.json`）的**唯一执行点**。

三件事：
1. `validate(record)`：新裁决只能落在 `allowed_decision` / `allowed_reason_code` 里；
   不在表内的 reason_code **不接受为正常裁决**，转 `NEEDS_HUMAN` + `SCOPE_CHANGE`（§3-E.5）。
2. `check_history(path)`：历史必须逐条有交代——`legacy_map` 映射、或新记录本来就落在闭集里、
   或（2026-11-16 18:5x 补）被后续合规记录用 `supersedes` 显式点名更正。**不改原文**。
3. `append(path, record)`：唯一的追加入口（原子写：临时文件 + `os.replace`），
   保证「D0 无法再用自由文本 decision 改状态」。

注意：绕过 `append()` 手写 JSON 追加会跳过第 1 步的词表校验。这种事真发生过一次
（2026-11-16 18:44 我自己写 D-199…203，`decision="RULING"` 与 5 个自造 reason_code 都在表外），
是 `check_history` 抓到的——所以第 2 步必须先于「手写」这条路存在，且不静默放行。

退出码：0 OK / 3 词表违规 / 4 读不到。
"""
from __future__ import annotations

import argparse
import datetime
import io
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
TAXONOMY_PATH = os.path.join(HERE, "decision_taxonomy.json")
DECISIONS_PATH = os.path.join(HERE, "decisions.jsonl")


class TaxonomyError(ValueError):
    def __init__(self, message: str, reason_code: str = "SCOPE_CHANGE"):
        super().__init__(message)
        self.reason_code = reason_code


def load(path: str = TAXONOMY_PATH) -> dict:
    try:
        with io.open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise TaxonomyError("读不到词表 %s：%s" % (path, exc), "PROVENANCE_INVALID")


def allowed(doc: dict | None = None) -> tuple:
    doc = doc or load()
    return set(doc["allowed_decision"]), set(doc["allowed_reason_code"])


def validate(record: dict, doc: dict | None = None) -> dict:
    """校验一条新裁决。不合规时抛 `TaxonomyError`；合规时返回规范化后的记录。

    「不合规」的处置是**转 NEEDS_HUMAN**（人批准后才可把新词加进表），
    但本函数自己不做转换——转换发生在 `normalize_or_needs_human()`，
    因为「静默改写调用方的决定」也是一种状态说谎。
    """
    doc = doc or load()
    decisions, reasons = allowed(doc)
    decision = (record.get("decision") or "").strip()
    reason = (record.get("reason_code") or "").strip()
    if not decision:
        raise TaxonomyError("缺 decision", "SCOPE_CHANGE")
    if decision not in decisions:
        raise TaxonomyError("decision %r 不在词表里（允许 %d 类）" % (decision, len(decisions)),
                            "SCOPE_CHANGE")
    if reason and reason not in reasons:
        raise TaxonomyError("reason_code %r 不在词表里（允许 %d 个）" % (reason, len(reasons)),
                            "SCOPE_CHANGE")
    record = dict(record)
    record.setdefault("decision_id", new_decision_id())
    record.setdefault("logged_at", datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
    return record


def normalize_or_needs_human(record: dict, doc: dict | None = None) -> dict:
    """不合规 ⇒ 转成一条 `NEEDS_HUMAN` / `SCOPE_CHANGE`，原意塞进 `original`。"""
    doc = doc or load()
    try:
        return validate(record, doc)
    except TaxonomyError as exc:
        return {
            "decision_id": record.get("decision_id") or new_decision_id(),
            "task_id": record.get("task_id") or "SPEC",
            "decision": "NEEDS_HUMAN",
            "reason_code": "SCOPE_CHANGE",
            "original": {"decision": record.get("decision"), "reason_code": record.get("reason_code"),
                         "why": str(exc)},
            "human_approval_required": True,
            "message": "词表外的新概念被转成 NEEDS_HUMAN，待 Human 批准后才可加入词表",
            "logged_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        }


def new_decision_id(prefix: str = "D") -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d")
    return "%s-%s-NEW-%s" % (prefix, stamp, datetime.datetime.now().strftime("%H%M%S"))


def kind_ok(row: dict, decisions: set, reasons: set) -> bool:
    """这条记录的 kind 是否落在闭集里。"""
    return (row.get("decision") in decisions
            and (not row.get("reason_code") or row.get("reason_code") in reasons))


def supersede_map(rows: list, decisions: set, reasons: set) -> tuple:
    """收集「更正后的 kind」声明，返回 (`索引`, `问题列表`)。

    一条词表外的记录（典型：D0 手写 JSON 追加、绕过了 `append()`）只有被
    **后面一条合规记录显式点名更正**，才算有了交代；而不许被静默放行。

    七条 fail-closed（少一条这套机制就成了洗白通道；2号/3号/4号 在 2026-11-16 18:49
    各自独立把后四条撞了出来）：
    1. 声明行自身必须落在闭集里 —— 不许用一条词表外的行去更正另一条；
    2. 被更正的 id 必须在历史里真实存在 —— 否则凭空写个 id 就想「已被交代」；
    3. 更正后的 kind 也必须在闭集里 —— 否则等于换个位置写词表外的词；
    4. （H2）声明必须写在被更正记录**之后**（pos 更大）—— 否则「后面一条」只是文档里的字；
    5. （H4）不许自己更正自己 —— 自己给自己签收据不是交代；
    6. （H1）同一条被两处点名 ⇒ 记问题，并且**两份都留痕**（`disputed` + `also_by`）：
       只留胜者的话，调换两行顺序就能把「曾有两份矛盾更正」抹成干净的单条，账本被排序操纵；
    7. （H3）桶的口径：只有**目标确实越界**的才进 `corrected_out_of_vocabulary`，
       更正一条本来合规的记录另记 —— 否则桶名承诺「词表外」，装的却是「生效的声明条目」。

    声明形状：`"supersedes": {"D-…-199": {"decision": "REASSIGN", "reason_code": "RULING"}}`
    """
    pos = {}
    for i, row in enumerate(rows):
        pos.setdefault(row.get("decision_id"), i)
    index, problems = {}, []
    for row in rows:
        decl = row.get("supersedes")
        if not decl:
            continue
        by = row.get("decision_id")
        if not kind_ok(row, decisions, reasons):
            problems.append({"by": by, "why": "声明行自身不在词表闭集里，不足以更正别人"})
            continue
        if not isinstance(decl, dict):
            problems.append({"by": by, "why": "supersedes 必须是 {id: {decision, reason_code}}"})
            continue
        for target, intent in decl.items():
            if target not in pos:
                problems.append({"by": by, "decision_id": target, "why": "被更正的 id 不在历史里"})
                continue
            if target == by:
                problems.append({"by": by, "decision_id": target,
                                 "why": "自己更正自己（by == decision_id）不是交代"})
                continue
            if pos[by] <= pos[target]:
                problems.append({"by": by, "decision_id": target,
                                 "why": "声明写在被更正记录之前（要求声明者 pos 更大）"})
                continue
            if not isinstance(intent, dict):
                problems.append({"by": by, "decision_id": target, "why": "更正意图必须是对象"})
                continue
            decision = (intent.get("decision") or "").strip()
            reason = (intent.get("reason_code") or "").strip()
            if decision not in decisions or (reason and reason not in reasons):
                problems.append({"by": by, "decision_id": target,
                                 "why": "更正后的 kind 仍不在闭集里"})
                continue
            prior = index.get(target)
            if prior is not None:
                prior["disputed"] = True
                prior.setdefault("also_by", []).append(by)
                problems.append({"by": by, "decision_id": target,
                                 "why": "已被 %s 更正过，又被 %s 更正（同一目标两份声明）"
                                        % (prior["by"], by)})
                continue
            index[target] = {"by": by, "decision": decision, "reason_code": reason,
                             "disputed": False}
    return index, problems


def check_history(path: str = DECISIONS_PATH, doc: dict | None = None) -> dict:
    """历史必须逐条有交代；**只读**，不改原文。

    「有交代」有三条路（2026-11-16 16:1x 修 + 18:5x 补）：
    1. 老记录靠 `legacy_map` 映射；
    2. **新记录**（词表落地之后写的）本来就落在闭集里，不需要 legacy 映射——
       旧实现把两种都当历史，于是自己写的第一条新裁决就被判 `missing_mapping`，
       那是判据错，不是记录错；
    3. 词表外但已被后续合规记录**显式点名更正**（`supersedes`）的 —— 进
       `corrected_out_of_vocabulary` 让人看得见，不是静默放行。
    """
    doc = doc or load()
    legacy = doc["legacy_map"]
    decisions, reasons = allowed(doc)
    rows = []
    try:
        with io.open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
    except (OSError, ValueError) as exc:
        raise TaxonomyError("读不到裁决历史 %s：%s" % (path, exc), "PROVENANCE_INVALID")

    def accounted(row: dict) -> bool:
        if row.get("decision_id") in legacy:
            return True
        if kind_ok(row, decisions, reasons):
            return True
        return row.get("decision_id") in supersede_index

    supersede_index, supersede_problems = supersede_map(rows, decisions, reasons)
    by_id = {row.get("decision_id"): row for row in rows}
    missing = [row.get("decision_id") for row in rows if not accounted(row)]
    corrected, compliant = [], []
    for target, intent in supersede_index.items():
        item = {"decision_id": target,
                "was": {"decision": by_id[target].get("decision"),
                        "reason_code": by_id[target].get("reason_code")},
                **intent}
        # H3：桶名承诺「词表外」，就只装词表外的目标；更正一条本来合规的记录另记一桶，
        # 否则「越界事实还剩几条」这个数会被污染（4号 撞出来、2号/3号 复核同读数）
        (compliant if kind_ok(by_id[target], decisions, reasons) else corrected).append(item)
    unknown_decisions = sorted({row.get("decision") for row in rows
                                if row.get("decision") not in doc["state_decisions"]
                                and row.get("decision") not in doc["non_state_decisions"]
                                and row.get("decision") not in decisions})
    return {"records": len(rows), "missing_mapping": missing,
            "corrected_out_of_vocabulary": corrected,
            "corrected_compliant": compliant,
            "bad_supersedes": supersede_problems,
            "unknown_decision_kinds": unknown_decisions}


def append(path: str, record: dict, doc: dict | None = None) -> dict:
    """唯一追加口：先校验/转换，再原子追加一行（不改历史行）。"""
    doc = doc or load()
    final = normalize_or_needs_human(record, doc)
    line = json.dumps(final, ensure_ascii=False) + "\n"
    data = b""
    if os.path.exists(path):
        with io.open(path, "rb") as fh:
            data = fh.read()
    if data and not data.endswith(b"\n"):
        data += b"\n"
    tmp = path + ".tmp"
    with io.open(tmp, "wb") as fh:
        fh.write(data + line.encode("utf-8"))
    os.replace(tmp, path)
    return final


def main(argv=None) -> int:
    from .cli import ensure_utf8_stdio
    ensure_utf8_stdio()
    ap = argparse.ArgumentParser(prog="coordination.taxonomy",
                                 description="决策词表校验（只读历史，不改原文）")
    ap.add_argument("--check", action="store_true", help="校验历史全部有映射")
    ap.add_argument("--decisions", default=DECISIONS_PATH)
    ap.add_argument("--taxonomy", default=TAXONOMY_PATH)
    ap.add_argument("--demo-validate", default="", help="校验一个 decision 名（诊断用）")
    args = ap.parse_args(argv)
    try:
        doc = load(args.taxonomy)
    except TaxonomyError as exc:
        print(json.dumps({"state": "UNREADABLE", "why": str(exc)}, ensure_ascii=False))
        return 4
    if args.demo_validate:
        try:
            validate({"decision": args.demo_validate, "reason_code": "EVIDENCE_COMPLETE"}, doc)
            print(json.dumps({"state": "OK", "decision": args.demo_validate}, ensure_ascii=False))
            return 0
        except TaxonomyError as exc:
            print(json.dumps({"state": "REJECTED", "why": str(exc), "reason_code": exc.reason_code},
                             ensure_ascii=False))
            return 3
    result = check_history(args.decisions, doc)
    ok = (not result["missing_mapping"] and not result["unknown_decision_kinds"]
          and not result["bad_supersedes"])
    print(json.dumps({"state": "OK" if ok else "CONFLICT", **result,
                      "allowed_decision": doc["allowed_decision"],
                      "allowed_reason_code_count": len(doc["allowed_reason_code"])},
                     ensure_ascii=False, sort_keys=True))
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
