"""S3 dispatcher worktree 资格预检回归。

覆盖手册 S3.3/6.3 的六类判据：合格 claim、非祖先 base、dirty、缺配置/路径不存在、
board 只读、不合格候选不提前占用 reserved_resources。
所有场景用临时 git 仓库 + 注入 worktrees 映射，不依赖真实 A1–A4 路径。
"""
import os
import shutil
import subprocess
import tempfile
import unittest

from coordination import board as board_mod
from coordination import dispatcher as dispatcher_mod


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def make_repo(root, name, dirty=False):
    path = os.path.join(root, name)
    os.makedirs(path, exist_ok=True)
    assert git(path, "init", "-q").returncode == 0
    with open(os.path.join(path, "f.txt"), "w", encoding="utf-8") as fh:
        # 内容必须随仓库名变化：同内容+同作者+同秒提交会得到相同 hash，
        # 会把“非祖先 base”夹具偶然造成同一个提交，形成环境相关的假绿/假红。
        fh.write(name + "\n")
    assert git(path, "add", ".").returncode == 0
    assert git(path, "-c", "user.email=a@b", "-c", "user.name=t",
               "commit", "-qm", "init").returncode == 0
    head = git(path, "rev-parse", "HEAD").stdout.strip()
    if dirty:
        with open(os.path.join(path, "f.txt"), "w", encoding="utf-8") as fh:
            fh.write("dirty\n")
    return path, head


def clone_repo(root, source, name):
    path = os.path.join(root, name)
    assert git(root, "clone", "-q", source, path).returncode == 0
    return path, git(path, "rev-parse", "HEAD").stdout.strip()


def lane_row(result, agent):
    return next(a for a in result["assignments"] if a["agent"] == agent and a["lane"] == agent)


class DispatcherWorktreeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mm_s3_disp_")
        self.board = board_mod.Board(os.path.join(self.tmp, "board.db"))
        self.board.init()
        self.addCleanup(self.board.close)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.wt1, self.head1 = make_repo(self.tmp, "A1")
        self.wt3, self.head3 = clone_repo(self.tmp, self.wt1, "A3")
        self.assertEqual(self.head1, self.head3)   # 同一 commit，base 对两条车道都可祖先

    def plan(self, registry):
        return dispatcher_mod.plan(self.board, repo=self.wt1, worktrees=registry)

    # 1. 合格 worktree 形成 claim，并输出实际 HEAD 供 --head 使用
    def test_qualified_worktree_forms_claim_with_head(self):
        self.board.add_task("M02", "M02", "A1", status="ready", resource="none")
        p = self.plan({"A1": self.wt1})
        row = lane_row(p, "A1")
        self.assertEqual(row["action"], "claim")
        self.assertEqual(row["worktree_head"], self.head1)
        self.assertEqual(row["worktree"], os.path.normpath(self.wt1))
        self.assertEqual(p["state"], "DISPATCH")

    # 2. 非祖先 base → needs_human / PROVENANCE_INVALID，且带齐 task/base/路径/原因
    def test_non_ancestor_base_becomes_needs_human(self):
        _, foreign_head = make_repo(self.tmp, "foreign")
        self.assertNotEqual(foreign_head, self.head1, "非祖先夹具必须生成不同提交")
        self.board.add_task("M02", "M02", "A1", status="ready",
                            resource="none", base_commit=foreign_head)
        p = self.plan({"A1": self.wt1})
        row = lane_row(p, "A1")
        self.assertEqual(row["action"], "needs_human")
        self.assertEqual(row["reason_code"], "PROVENANCE_INVALID")
        self.assertEqual(row["task_id"], "M02")
        self.assertEqual(row["base_commit"], foreign_head)
        self.assertEqual(row["worktree"], os.path.normpath(self.wt1))
        self.assertTrue(row["reason"])
        self.assertNotEqual(p["state"], "IDLE")

    # 3. dirty worktree → needs_human / OWNERSHIP_VIOLATION
    def test_dirty_worktree_becomes_needs_human(self):
        wtd, headd = make_repo(self.tmp, "A1dirty", dirty=True)
        self.board.add_task("M01", "M01", "A1", status="ready", resource="none")
        p = dispatcher_mod.plan(self.board, repo=wtd, worktrees={"A1": wtd})
        row = lane_row(p, "A1")
        self.assertEqual(row["action"], "needs_human")
        self.assertEqual(row["reason_code"], "OWNERSHIP_VIOLATION")
        self.assertEqual(row["base_commit"], headd)

    # 4a. 缺配置 → fail-closed，不是 idle
    def test_missing_config_is_fail_closed(self):
        self.board.add_task("M01", "M01", "A1", status="ready", resource="none")
        p = self.plan({})
        row = lane_row(p, "A1")
        self.assertEqual(row["action"], "needs_human")
        self.assertEqual(row["reason_code"], "PROVENANCE_INVALID")
        self.assertIn("reason_code", row)
        self.assertIsNone(row["worktree"])
        self.assertNotEqual(p["state"], "IDLE")
        self.assertEqual(p["needs_human_count"], 1)

    # 4b. 路径不存在 → fail-closed
    def test_missing_path_is_fail_closed(self):
        self.board.add_task("M01", "M01", "A1", status="ready", resource="none")
        missing = os.path.join(self.tmp, "does_not_exist")
        p = self.plan({"A1": missing})
        row = lane_row(p, "A1")
        self.assertEqual(row["action"], "needs_human")
        self.assertEqual(row["reason_code"], "PROVENANCE_INVALID")
        self.assertEqual(row["worktree"], missing)

    # 4c. 相对路径同样拒绝
    def test_relative_path_is_rejected(self):
        self.board.add_task("M01", "M01", "A1", status="ready", resource="none")
        p = self.plan({"A1": "relative/path"})
        self.assertEqual(lane_row(p, "A1")["reason_code"], "PROVENANCE_INVALID")

    # 5. 计划前后 board 的 tasks/events/resources 逻辑状态不变
    def test_plan_does_not_mutate_board(self):
        self.board.add_task("M02", "M02", "A1", status="ready", resource="blender")
        self.board.add_task("M05", "M05", "A3", status="ready", resource="blender")

        def snap():
            return tuple(
                [dict(r) for r in self.board.db.execute("SELECT * FROM %s ORDER BY 1" % t)]
                for t in ("tasks", "events", "resources"))

        before = snap()
        self.plan({"A1": self.wt1, "A3": self.wt3})
        self.assertEqual(before, snap())

    # 6. 不合格候选不得提前消耗 reserved_resources，挡住其他合法计划
    def test_unqualified_candidate_does_not_reserve_resource(self):
        self.board.add_task("M02", "M02", "A1", status="ready", resource="blender")
        self.board.add_task("M05", "M05", "A3", status="ready", resource="blender")
        p = self.plan({"A3": self.wt3})            # A1 缺配置
        self.assertEqual(lane_row(p, "A1")["action"], "needs_human")
        self.assertEqual(lane_row(p, "A3")["action"], "claim")

    # 7. 不提供任何绕过参数
    def test_no_bypass_flag(self):
        src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "coordination", "dispatcher.py")
        with open(src, encoding="utf-8") as fh:
            text = fh.read()
        for banned in ("no-worktree-check", "skip-worktree", "--allow-dirty"):
            self.assertNotIn(banned, text)


if __name__ == "__main__":
    unittest.main()
