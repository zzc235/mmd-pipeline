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

    def test_snapshot_copies_are_listed_and_present(self):
        copies = self.scope["snapshot_copies"]
        self.assertTrue(copies)
        for name in copies:
            self.assertTrue(os.path.exists(os.path.join(SNAP, name)), name)

    def test_two_way_checked_is_false_with_reason(self):
        self.assertFalse(self.scope["two_way_checked"])
        self.assertIn("out/", self.scope["why"])


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


class CliTest(unittest.TestCase):
    def test_cli_returns_zero_or_three_never_two_on_this_machine(self):
        code = SCOPE.main(["--dir", SNAP])
        self.assertIn(code, (0, 3))  # 0 = 全部解析到；3 = base 不在本机（量不了）


if __name__ == "__main__":
    unittest.main()
