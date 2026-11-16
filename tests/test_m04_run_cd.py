# -*- coding: utf-8 -*-
"""`m04_run_cd.py` 的批次版本化规则（离屏，不开 Blender）。

为什么这些规则值得一组回归：今天真实发生过一次「同路径重跑把物证换掉」——
`C@W1` / `D` 的 `.blend` 被后续重跑覆盖，读数钉的两个 sha 在盘上不存在了。
所以「拒绝覆盖」「冻结优先级高于 --allow-overwrite」这两条必须是代码里的，
不能靠记性；而 `manifest.json` 里的 `bytes` / `sha256` 是以后核这些产物的唯一入口。
"""
import importlib.util
import io
import json
import os
import shutil
import stat
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(os.path.dirname(HERE), "reports", "subai", "M04", "scripts",
                      "m04_run_cd.py")


def load_driver():
    spec = importlib.util.spec_from_file_location("m04_run_cd", DRIVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DRV = load_driver()


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="m04runcd-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def write(self, rel, data=b"x"):
        p = os.path.join(self.root, rel)
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        mode = "wb" if isinstance(data, bytes) else "w"
        kw = {} if isinstance(data, bytes) else {"encoding": "utf-8", "newline": "\n"}
        with open(p, mode, **kw) as fh:
            fh.write(data)
        return p

    def unfreeze(self, path):
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        except OSError:
            pass


class BatchIdTest(unittest.TestCase):
    def test_accepts_plain_names(self):
        for name in ("round2", "round2_324", "r2.a-b", "A" * 64):
            self.assertEqual(DRV.sanitize_batch_id(name), name)

    def test_rejects_names_that_would_escape_or_mislead(self):
        # 反控：这些必须拒，而不是被「净化」成别的名字
        for bad in ("", "a", "..", ".", "x" * 65, "a/b", "a b", "回合一", None, 3):
            with self.assertRaises(ValueError, msg=repr(bad)):
                DRV.sanitize_batch_id(bad)

    def test_refuses_dot_only_name(self):
        for bad in (".", "..", "..."):
            with self.assertRaises(ValueError, msg=repr(bad)):
                DRV.sanitize_batch_id(bad)


class PrepareBatchDirTest(TempDirCase):
    def test_creates_new_batch(self):
        bdir, created = DRV.prepare_batch_dir(self.root, "round2")
        self.assertTrue(created)
        self.assertTrue(os.path.isdir(bdir))
        self.assertEqual(os.path.basename(bdir), "round2")

    def test_reuses_empty_batch(self):
        os.makedirs(os.path.join(self.root, "round2"))
        bdir, created = DRV.prepare_batch_dir(self.root, "round2")
        self.assertFalse(created)
        self.assertTrue(os.path.isdir(bdir))

    def test_refuses_nonempty_batch_by_default(self):
        self.write("round2/D.jsonl")
        with self.assertRaises(DRV.BatchRefused) as ctx:
            DRV.prepare_batch_dir(self.root, "round2")
        self.assertIn("拒绝覆盖", str(ctx.exception))

    def test_allow_overwrite_opens_unfrozen_batch(self):
        self.write("round2/D.jsonl")
        bdir, created = DRV.prepare_batch_dir(self.root, "round2", allow_overwrite=True)
        self.assertFalse(created)
        self.assertTrue(os.path.isdir(bdir))

    def test_frozen_batch_refuses_even_with_allow_overwrite(self):
        p = self.write("round2/D.jsonl")
        os.chmod(p, stat.S_IREAD)
        self.addCleanup(self.unfreeze, p)
        self.assertTrue(DRV._is_frozen(p))
        with self.assertRaises(DRV.BatchRefused) as ctx:
            DRV.prepare_batch_dir(self.root, "round2", allow_overwrite=True)
        self.assertIn("已冻结", str(ctx.exception))

    def test_other_batch_unaffected(self):
        p = self.write("round1/D.jsonl")
        os.chmod(p, stat.S_IREAD)
        self.addCleanup(self.unfreeze, p)
        bdir, created = DRV.prepare_batch_dir(self.root, "round2")
        self.assertTrue(created)
        self.assertTrue(os.path.isfile(p))


class FileFactsTest(TempDirCase):
    def test_text_gets_lf_normalized_sha(self):
        p = self.write("a.json", b'{"k": 1}\r\n')
        facts = DRV.file_facts(p)
        self.assertEqual(facts["bytes"], 10)
        self.assertEqual(len(facts["sha256"]), 64)
        q = self.write("b.json", b'{"k": 1}\n')
        # CRLF 与 LF 的 raw sha 不同，LF 归一的 sha 必须相同（本机 core.autocrlf=true）
        self.assertNotEqual(facts["sha256"], DRV.file_facts(q)["sha256"])
        self.assertEqual(facts["sha256_lf_normalized"],
                         DRV.file_facts(q)["sha256_lf_normalized"])

    def test_binary_gets_no_text_sha(self):
        p = self.write("x.blend", b"\xff\xfe\x00binary")
        facts = DRV.file_facts(p)
        self.assertNotIn("sha256_lf_normalized", facts)  # 不记假值
        self.assertEqual(facts["bytes"], 9)

    def test_readonly_flag_reflects_mode(self):
        p = self.write("a.json", b"{}\n")
        self.assertFalse(DRV.file_facts(p)["readonly"])
        os.chmod(p, stat.S_IREAD)
        self.addCleanup(self.unfreeze, p)
        self.assertTrue(DRV.file_facts(p)["readonly"])


class ManifestTest(TempDirCase):
    def test_manifest_lists_files_except_itself(self):
        self.write("round2/C_W1.jsonl", b"a\n")
        self.write("round2/D.meta.json", b"b\n")
        bdir = os.path.join(self.root, "round2")
        doc = DRV.write_manifest(bdir)
        self.assertEqual(doc["count"], 2)
        self.assertEqual([r["name"] for r in doc["files"]],
                         ["C_W1.jsonl", "D.meta.json"])
        self.assertEqual(doc["batch_id"], "round2")
        again = DRV.write_manifest(bdir)  # 幂等：manifest 不把自己算进去
        self.assertEqual(again["count"], 2)
        with io.open(os.path.join(bdir, "manifest.json"), encoding="utf-8") as fh:
            disk = json.load(fh)
        self.assertEqual(disk["count"], 2)
        for row in disk["files"]:
            self.assertEqual(len(row["sha256"]), 64)
            self.assertIn("bytes", row)

    def test_empty_batch_manifest_is_zero_not_crash(self):
        bdir = os.path.join(self.root, "round2")
        os.makedirs(bdir)
        doc = DRV.write_manifest(bdir)
        self.assertEqual(doc["count"], 0)
        self.assertEqual(doc["files"], [])

    def test_extra_fields_land(self):
        bdir = os.path.join(self.root, "round2")
        os.makedirs(bdir)
        doc = DRV.write_manifest(bdir, extra={"frozen": False, "blocked": None})
        self.assertFalse(doc["frozen"])
        self.assertIsNone(doc["blocked"])


class FreezeTest(TempDirCase):
    def test_freeze_makes_files_readonly_and_write_then_raises(self):
        p = self.write("round2/C_W1.jsonl", b"a\n")
        bdir = os.path.join(self.root, "round2")
        frozen = DRV.freeze_tree(bdir)
        self.addCleanup(self.unfreeze, p)
        self.assertEqual(frozen, ["C_W1.jsonl"])
        self.assertTrue(DRV._is_frozen(p))
        with self.assertRaises((PermissionError, OSError)):
            with open(p, "wb") as fh:
                fh.write(b"b\n")

    def test_manifest_records_frozen_after_freeze(self):
        p = self.write("round2/C_W1.jsonl", b"a\n")
        bdir = os.path.join(self.root, "round2")
        self.addCleanup(self.unfreeze, p)
        DRV.freeze_tree(bdir)
        doc = DRV.write_manifest(bdir, extra={"frozen": True})
        self.assertTrue(doc["files"][0]["readonly"])
        self.assertTrue(doc["frozen"])

    def test_frozen_batch_cannot_be_reprepared_for_same_batch(self):
        p = self.write("round2/C_W1.jsonl", b"a\n")
        bdir = os.path.join(self.root, "round2")
        self.addCleanup(self.unfreeze, p)
        DRV.freeze_tree(bdir)
        with self.assertRaises(DRV.BatchRefused):
            DRV.prepare_batch_dir(self.root, "round2", allow_overwrite=True)
        # 换批次名照常可用
        b2, created = DRV.prepare_batch_dir(self.root, "round3")
        self.assertTrue(created)


if __name__ == "__main__":
    unittest.main()
