"""`coordination.status`（任务级状态派生视图）的对账与退出码。

只读视图，三条「应当被拒」的输入必须被拒（D0 的原话）：
  1. 状态表里有、裁决历史里没有的任务（且不是 NOT_STARTED）→ 退出码 3
  2. 裁决历史里有、状态表里没登记的任务 → 退出码 3
  3. 状态表不是合法 JSON → 退出码 4；status 不在枚举里 → 退出码 3
另外钉住两件事：`NOT_STARTED` 允许无裁决；视图**不写任何文件**。
"""
import json
import os
import tempfile
import unittest

from coordination import status as st


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path


def _status_doc(tasks):
    return {"tasks": tasks}


def _row(task, decision_id, **extra):
    base = {"decision_id": decision_id, "task_id": task, "decision": "RULING"}
    base.update(extra)
    return json.dumps(base, ensure_ascii=False)


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="m00_status_")
        self.status_path = os.path.join(self.tmp, "task_status.json")
        self.decisions_path = os.path.join(self.tmp, "decisions.jsonl")
        self.tasks = {
            "M00": {"status": "PARTIAL", "reason": "r", "next": "写 status.py"},
            "M01": {"status": "PASS", "reason": "r", "next": "无"},
            "M08": {"status": "NOT_STARTED", "reason": "r", "next": "等前置"},
        }
        _write(self.status_path, json.dumps(_status_doc(self.tasks), ensure_ascii=False))
        _write(self.decisions_path, "\n".join([
            _row("M00", "D-1"),
            _row("M01", "D-2"),
        ]) + "\n")

    def run_status(self):
        return st.main(["--status", self.status_path, "--decisions", self.decisions_path])

    def test_happy_path(self):
        self.assertEqual(self.run_status(), 0)

    def test_task_without_history_is_conflict(self):
        self.tasks["M01"]["status"] = "PARTIAL"          # 不再是 NOT_STARTED，必须有裁决
        _write(self.status_path, json.dumps(_status_doc(self.tasks), ensure_ascii=False))
        _write(self.decisions_path, _row("M00", "D-1") + "\n")
        self.assertEqual(self.run_status(), 3)

    def test_history_task_not_registered_is_conflict(self):
        _write(self.decisions_path, "\n".join([_row("M00", "D-1"), _row("M01", "D-2"),
                                               _row("M99", "D-3")]) + "\n")
        self.assertEqual(self.run_status(), 3)

    def test_not_started_may_have_no_history(self):
        self.assertEqual(self.run_status(), 0)            # M08 只有登记、没有裁决

    def test_invalid_json_is_unreadable(self):
        _write(self.status_path, "{not json")
        self.assertEqual(self.run_status(), 4)

    def test_missing_file_is_unreadable(self):
        os.remove(self.decisions_path)
        self.assertEqual(self.run_status(), 4)

    def test_bad_status_enum_is_conflict(self):
        self.tasks["M00"]["status"] = "DONE"              # 不在 PASS/PARTIAL/BLOCKED/NOT_STARTED
        _write(self.status_path, json.dumps(_status_doc(self.tasks), ensure_ascii=False))
        self.assertEqual(self.run_status(), 3)

    def test_empty_tasks_is_conflict(self):
        _write(self.status_path, json.dumps({"tasks": {}}, ensure_ascii=False))
        self.assertEqual(self.run_status(), 3)

    def test_non_task_ids_are_ignored(self):
        _write(self.decisions_path, "\n".join([
            _row("M00", "D-1"), _row("M01", "D-2"),
            _row("LANE", "D-lane"), _row("LEASE", "D-lease"),
        ]) + "\n")
        self.assertEqual(self.run_status(), 0)

    def test_pending_human_cleared_by_later_decision(self):
        _write(self.decisions_path, "\n".join([
            _row("M00", "D-1", human_approval_required=True),
            _row("M00", "D-2"),
            _row("M01", "D-3", human_approval_required=True),
        ]) + "\n")
        decisions = st.load_decisions(self.decisions_path)
        doc = st.load_status(self.status_path)
        rec = st.reconcile(doc, decisions)
        pending = st.pending_human(decisions, rec["history"])
        self.assertEqual([r["decision_id"] for r in pending], ["D-3"])

    def test_last_decision_is_the_latest_row(self):
        _write(self.decisions_path, "\n".join([
            _row("M00", "D-1"), _row("M00", "D-9"), _row("M01", "D-2"),
        ]) + "\n")
        doc = st.load_status(self.status_path)
        rec = st.reconcile(doc, st.load_decisions(self.decisions_path))
        self.assertEqual(rec["last"]["M00"]["decision_id"], "D-9")

    def test_render_contains_table_and_pending(self):
        doc = st.load_status(self.status_path)
        decisions = st.load_decisions(self.decisions_path)
        rec = st.reconcile(doc, decisions)
        lines = st.render(doc, rec, st.pending_human(decisions, rec["history"]))
        text = "\n".join(lines)
        self.assertIn("M08", text)
        self.assertIn("D-1", text)
        self.assertIn("待 Human 批项", text)

    def test_view_is_read_only(self):
        before = {name: os.stat(os.path.join(self.tmp, name)).st_mtime_ns
                  for name in os.listdir(self.tmp)}
        self.assertEqual(self.run_status(), 0)
        after = {name: os.stat(os.path.join(self.tmp, name)).st_mtime_ns
                 for name in os.listdir(self.tmp)}
        self.assertEqual(before, after, "派生视图不许写文件")


if __name__ == "__main__":
    unittest.main()
