# -*- coding: utf-8 -*-
"""快照 manifest 的审计范围：三态核验 + 两条负控。

触发：`总控` 19:50 的 `artifact_audit` 第一版在我这份快照上报了 **46 条假 drift** ——
条目只写文件名、产物在 `out/` 批次目录，而审计方按 manifest 所在目录做双向枚举。
文件一个字节没动，缺的是「范围」写在盘上。

所以这里钉三件事：
1. 真件按 `base` 能逐条解析（35/35）；
2. 名字不存在 ⇒ `MISMATCH`（负控，证明检查在工作）；
3. **`base` 不在本机 ⇒ `UNMEASURED`，不是 `MISMATCH`**（今晚被判过四次的形状）。
"""
import importlib.util
import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SNAP = os.path.join(ROOT, "reports", "subai", "M04", "cd_round2")
# 条数棘轮：加一条承载方就得改这个常量（`3号` 20:23 的形状），别让表静默增长。
EXPECT_CARRIERS = 7
MODULE = os.path.join(ROOT, "reports", "subai", "M04", "scripts", "m04_snapshot_scope.py")


def load_module():
    spec = importlib.util.spec_from_file_location("m04_snapshot_scope_uut", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SCOPE = load_module()


class RealSnapshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope = SCOPE.load_json(os.path.join(SNAP, "manifest_scope.json"))
        cls.manifest = SCOPE.load_json(os.path.join(SNAP, "manifest.json"))

    def test_scope_declares_base_and_path_field(self):
        self.assertEqual(self.scope["path_field"], "name")
        self.assertTrue(self.scope["base"])
        self.assertEqual(self.scope["entries_declared"], len(self.manifest["files"]))

    def test_every_entry_resolves_under_base(self):
        out = SCOPE.resolve_scope(self.scope, self.manifest)
        if out["state"] == SCOPE.STATE_UNMEASURED:
            # 这台机器上没有那批产物（新克隆）：量不了，不算失败，但要断言原因是「base 不在」
            self.assertIn("base 不在本机", out["reason"])
            return
        self.assertEqual(out["state"], SCOPE.STATE_OK, out)
        self.assertEqual(out["checked"], 35)
        self.assertEqual(out["missing"], [])

    def test_every_declared_copy_is_accounted_for_in_git(self):
        """`in_git=true` 的必须在 git 里；`in_git=false` 的必须写明原因。

        这里**不**用 `os.path.exists`：那只说明本机有没有。`compare.log` 本机有、git 里没有
        （`.gitignore:39` 的 `*.log`），而 main 19:55 就是被这个「靠本机状态的绿灯」弄红的。
        """
        rel_snap = os.path.relpath(SNAP, ROOT).replace("\\", "/")
        out = SCOPE.check_copies(self.scope, SNAP, rel_snap=rel_snap)
        self.assertEqual(out["state"], SCOPE.STATE_OK, out)
        self.assertEqual(out["checked"], len(self.scope["snapshot_copies"]))

    def test_two_way_checked_is_false_with_reason(self):
        self.assertFalse(self.scope["two_way_checked"])
        self.assertIn("out/", self.scope["why"])

    def test_renamed_logs_are_declared_in_git(self):
        copies = {c["name"]: c for c in self.scope["snapshot_copies"]}
        for new, old in (("compare.log.txt", "compare.log"),
                         ("compare_selftest.log.txt", "compare_selftest.log")):
            self.assertTrue(copies[new]["in_git"], new)
            self.assertEqual(copies[new]["source_name_in_base"], old)
            self.assertIn(".gitignore", copies[new]["why_renamed"])
        self.assertNotIn("compare.log", copies)  # 原名不能留在「入 git」清单里


class NegativeControlTest(unittest.TestCase):
    """负控：应当被拒的两类输入。"""

    def test_missing_name_is_mismatch_not_unmeasured(self):
        scope = {"base": SNAP, "path_field": "name"}
        manifest = {"files": [{"name": "_snapshot_index.json"},
                              {"name": "no_such_file_here.json"}], "count": 2}
        out = SCOPE.resolve_scope(scope, manifest)
        self.assertEqual(out["state"], SCOPE.STATE_MISMATCH)
        self.assertEqual(len(out["missing"]), 1)
        self.assertEqual(out["checked"], 2)

    def test_absent_base_is_unmeasured_not_mismatch(self):
        """`base` 不在这台机器上 ⇒ UNMEASURED。这是「量不了 ≠ 不一致」的那条。"""
        scope = {"base": r"Z:\no\such\batch", "path_field": "name"}
        manifest = {"files": [{"name": "a.json"}], "count": 1}
        out = SCOPE.resolve_scope(scope, manifest)
        self.assertEqual(out["state"], SCOPE.STATE_UNMEASURED)
        self.assertIn("base 不在本机", out["reason"])

    def test_scope_without_base_is_unmeasured(self):
        out = SCOPE.resolve_scope({"path_field": "name"},
                                  {"files": [{"name": "a.json"}]})
        self.assertEqual(out["state"], SCOPE.STATE_UNMEASURED)

    def test_entry_without_path_field_is_reported(self):
        out = SCOPE.resolve_scope({"base": SNAP, "path_field": "name"},
                                  {"files": [{"path": "x.json"}]})
        self.assertEqual(out["state"], SCOPE.STATE_MISMATCH)
        self.assertEqual(out["missing"][0]["why"], "条目没有 'name' 字段")


class CopiesTest(unittest.TestCase):
    """负控：声明与 git 对不上必须 `MISMATCH`；git 不可用必须 `UNMEASURED`。"""

    def test_declared_tracked_but_missing_is_mismatch(self):
        scope = {"snapshot_copies": [{"name": "compare.log", "in_git": True}]}
        out = SCOPE.check_copies(scope, SNAP, tracked=lambda rel: False, rel_snap="reports/x")
        self.assertEqual(out["state"], SCOPE.STATE_MISMATCH)
        self.assertEqual(len(out["bad"]), 1)

    def test_ignored_copy_without_reason_is_mismatch(self):
        scope = {"snapshot_copies": [{"name": "a.log", "in_git": False}]}
        out = SCOPE.check_copies(scope, SNAP, tracked=lambda rel: None)
        self.assertEqual(out["state"], SCOPE.STATE_MISMATCH)
        self.assertIn("why_not", out["bad"][0]["why"])

    def test_git_unavailable_is_unmeasured(self):
        scope = {"snapshot_copies": [{"name": "cmp_round2.json", "in_git": True}]}
        out = SCOPE.check_copies(scope, SNAP, tracked=lambda rel: None)
        self.assertEqual(out["state"], SCOPE.STATE_UNMEASURED)

    def test_copy_without_in_git_field_is_mismatch(self):
        """一个只有名字的副本条目 = 「本机有」冒充「账上有」，必须拒。"""
        scope = {"snapshot_copies": [{"name": "cmp_round2.json"}]}
        out = SCOPE.check_copies(scope, SNAP, tracked=lambda rel: True)
        self.assertEqual(out["state"], SCOPE.STATE_MISMATCH)
        self.assertIn("in_git", out["bad"][0]["why"])


class CarriersTest(unittest.TestCase):
    """`3号` 20:17：**豁免 ≠ 可核的转手**；`4号` 20:23：只做子串匹配会退化成新散文。

    所以每条承载方带三档 `kind`，每档机器判真假：
    - `git`：`paths` 逐条必须 `git ls-files` 到；
    - `out`：只在产物树 ⇒ 必须给 `carrier_of_out` 指回仓内一份（拿豁免冒充可核是不许的）；
    - `input`：输入件不在仓 ⇒ 必须给 `sha256` 声明身份。
    """

    @classmethod
    def setUpClass(cls):
        cls.scope = SCOPE.load_json(os.path.join(SNAP, "manifest_scope.json"))

    def _resolve(self, rel):
        """按三处候选把 `rel` 解析到盘上的绝对路径（快照目录 → 仓库根 → M04 scripts）。"""
        cands = [os.path.join(SNAP, rel),
                 os.path.join(ROOT, rel),
                 os.path.join(ROOT, "reports", "subai", "M04", "scripts", rel)]
        for cand in cands:
            if os.path.exists(cand):
                return cand
        return None

    def test_carriers_shape_is_hard(self):
        carriers = self.scope.get("carriers") or []
        self.assertTrue(carriers, "manifest_scope 里没有 carriers 表")
        for ent in carriers:
            self.assertIn(ent.get("kind"), ("git", "out", "input"), ent)
            self.assertTrue(ent.get("key"), ent)
            if ent["kind"] == "git":
                self.assertTrue(ent.get("paths"), ent)
            if ent["kind"] == "out":
                # 「只在产物树」必须指回仓内一份承载方
                self.assertTrue(ent.get("carrier_of_out"), ent)
            if ent["kind"] == "input":
                self.assertTrue(ent.get("sha256"), ent)

    def test_git_carriers_are_tracked(self):
        missing, checked = [], 0
        for ent in self.scope["carriers"]:
            for rel in ent.get("paths") or []:
                full = self._resolve(rel)
                if full is None:
                    missing.append((ent["key"], rel, "盘上三处候选都没有"))
                    continue
                rel_repo = os.path.relpath(full, ROOT).replace("\\", "/")
                checked += 1
                if SCOPE.git_tracked(rel_repo, cwd=ROOT) is not True:
                    missing.append((ent["key"], rel, "git 里没有"))
        self.assertEqual(missing, [], "承载方不可核：%s" % missing)
        self.assertGreaterEqual(checked, 5, "可核路径太少，护栏可能在空转")

    def test_out_carriers_point_back_into_git(self):
        for ent in self.scope["carriers"]:
            if ent.get("kind") != "out":
                continue
            back = self._resolve(ent["carrier_of_out"])
            self.assertIsNotNone(back, ent)
            rel_repo = os.path.relpath(back, ROOT).replace("\\", "/")
            self.assertIs(SCOPE.git_tracked(rel_repo, cwd=ROOT), True,
                          "out 档的承载方必须指回仓内一份：%s" % ent)

    def test_carrier_count_is_a_ratchet(self):
        """条数棘轮（`3号` 20:23）：加一条承载方就得动这个常量、留下 diff。"""
        self.assertEqual(len(self.scope["carriers"]), EXPECT_CARRIERS,
                         "承载方条数变了：改了这张表就把 EXPECT_CARRIERS 一起改")

    def test_carriers_note_states_the_rule(self):
        note = self.scope["carriers_note"]
        self.assertIn("承载", note)
        self.assertIn("豁免", note)


class CliTest(unittest.TestCase):
    def test_cli_returns_zero_or_three_never_two_on_this_machine(self):
        code = SCOPE.main(["--dir", SNAP])
        self.assertIn(code, (0, 3))  # 0 = 全部解析到；3 = base 不在本机（量不了）


if __name__ == "__main__":
    unittest.main()
