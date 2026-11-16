# -*- coding: utf-8 -*-
"""冻结账本审计（`coordination/artifact_audit.py`）的回归。

核心是两条**必红**的负控：

1. **冻结之后字节被改**（账本没错、盘上变了）⇒ `sha_drift`，exit 3；
2. **冻结目录里多出未登记的文件** ⇒ `only_on_disk`，exit 3。

第 2 条比第 1 条更值得测：少一个文件很明显，多一个文件没人解释得清。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from coordination import artifact_audit as A  # noqa: E402


def build_frozen_dir(tmp, files=None, readonly=True):
    """造一个 frozen/ 目录 + 一份 manifest（模拟 `1号` 的冻结形状）。"""
    files = files or {"a.json": b'{"x": 1}\n', "b.blend": b"BLENDDATA\n"}
    frozen = os.path.join(tmp, "frozen")
    os.makedirs(frozen, exist_ok=True)
    items = []
    for name, data in files.items():
        path = os.path.join(frozen, name)
        with open(path, "wb") as fh:
            fh.write(data)
        if readonly:
            os.chmod(path, 0o444)
        items.append({
            "role": name,
            "frozen_path": path,
            "bytes": len(data),
            "sha256": A.sha256_file(path),
            "sha256_lf_normalized": A.sha256_lf_file(path),
            "readonly": readonly,
        })
    manifest = {
        "manifest_name": "frozen_manifest.json",
        "freeze_order": "freeze 文件 → 枚举 frozen/ 写 manifest → freeze manifest",
        "assertions": {"bidirectional_ok": True, "listed_count": len(items),
                       "on_disk_count": len(items), "only_in_manifest": [], "only_on_disk": []},
        "items": items,
    }
    path = os.path.join(frozen, "frozen_manifest.json")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    return frozen, path


class AuditManifestTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="audit_")
        self.frozen, self.manifest = build_frozen_dir(self.tmp)

    def tearDown(self):
        for base, _d, names in os.walk(self.tmp):
            for n in names:
                try:
                    os.chmod(os.path.join(base, n), 0o644)
                except OSError:
                    pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_positive_clean_manifest(self):
        got = A.audit_manifest(self.manifest)
        self.assertTrue(got["ok"], got["drift"])
        self.assertEqual(got["listed"], 2)
        self.assertEqual(got["listed_ok"], 2)
        self.assertEqual(got["only_on_disk"], [])
        self.assertIn("manifest_sha256_lf_normalized", got)

    def test_sha_drift_after_freeze(self):
        """冻结之后字节被改 —— 账本没错，盘上变了。"""
        target = os.path.join(self.frozen, "a.json")
        os.chmod(target, 0o644)
        with open(target, "wb") as fh:
            fh.write(b'{"x": 2}\n')
        got = A.audit_manifest(self.manifest)
        self.assertFalse(got["ok"])
        self.assertTrue(any(d["why"] == "sha_drift" for d in got["drift"]))
        self.assertTrue(any(d["role"] == "a.json" for d in got["drift"]))

    def test_missing_file(self):
        os.chmod(os.path.join(self.frozen, "b.blend"), 0o644)
        os.unlink(os.path.join(self.frozen, "b.blend"))
        got = A.audit_manifest(self.manifest)
        self.assertFalse(got["ok"])
        self.assertTrue(any(d["why"] == "missing" for d in got["drift"]))

    def test_only_on_disk_is_drift(self):
        """冻结目录里多出一个没人登记的文件 —— 比少一个更可疑。"""
        with open(os.path.join(self.frozen, "extra.blend"), "wb") as fh:
            fh.write(b"LEFTOVER")
        got = A.audit_manifest(self.manifest)
        self.assertFalse(got["ok"])
        self.assertEqual(got["only_on_disk"], ["extra.blend"])
        self.assertTrue(any(d["why"] == "only_on_disk" for d in got["drift"]))

    def test_other_manifests_are_not_unlisted(self):
        """多层冻结各有 manifest，互不算未登记。"""
        with open(os.path.join(self.frozen, "sub_manifest.json"), "w", encoding="utf-8") as fh:
            fh.write("{}\n")
        got = A.audit_manifest(self.manifest)
        self.assertTrue(got["ok"], got["drift"])

    def test_bytes_drift_reported(self):
        target = os.path.join(self.frozen, "a.json")
        os.chmod(target, 0o644)
        with open(target, "wb") as fh:
            fh.write(b'{"x": 1}\n' + b" " * 0)   # 同内容
        got = A.audit_manifest(self.manifest)
        self.assertTrue(got["ok"], got["drift"])

    def test_readonly_change_is_warning_not_drift(self):
        """只读位变了记 warning：它不改字节，但改「物证」性质。"""
        target = os.path.join(self.frozen, "a.json")
        os.chmod(target, 0o644)
        got = A.audit_manifest(self.manifest)
        self.assertTrue(got["ok"], got["drift"])
        self.assertTrue(any(w["why"] == "readonly_changed" for w in got["warnings"]))

    def test_lf_normalization_recorded(self):
        with open(os.path.join(self.frozen, "crlf.txt"), "wb") as fh:
            fh.write(b"line1\r\nline2\r\n")
        lf = A.sha256_lf_file(os.path.join(self.frozen, "crlf.txt"))
        raw = A.sha256_file(os.path.join(self.frozen, "crlf.txt"))
        self.assertNotEqual(raw, lf)


class AuditRootTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="auditroot_")

    def tearDown(self):
        for base, _d, names in os.walk(self.tmp):
            for n in names:
                try:
                    os.chmod(os.path.join(base, n), 0o644)
                except OSError:
                    pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_finds_nested_manifests(self):
        build_frozen_dir(os.path.join(self.tmp, "run1"))
        build_frozen_dir(os.path.join(self.tmp, "run2", "recompute_frozen"))
        got = A.audit_root(self.tmp)
        self.assertEqual(got["manifests"], 2)
        self.assertTrue(got["ok"], [r["drift"] for r in got["reports"]])

    def test_one_bad_tree_fails_the_root(self):
        _frozen, manifest = build_frozen_dir(os.path.join(self.tmp, "run1"))
        with open(manifest, encoding="utf-8") as fh:
            manifest_obj = json.load(fh)
        bad_path = manifest_obj["items"][0]["frozen_path"]
        os.chmod(bad_path, 0o644)
        with open(bad_path, "wb") as fh:
            fh.write(b"tampered\n")
        got = A.audit_root(self.tmp)
        self.assertFalse(got["ok"])
        self.assertEqual(got["failures"], 1)


class CliTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="auditcli_")
        self.frozen, self.manifest = build_frozen_dir(self.tmp)

    def tearDown(self):
        for base, _d, names in os.walk(self.tmp):
            for n in names:
                try:
                    os.chmod(os.path.join(base, n), 0o644)
                except OSError:
                    pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *args):
        return subprocess.run([sys.executable, "-m", "coordination.artifact_audit"] + list(args),
                              cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    def test_exit_0_clean(self):
        proc = self._run("--manifest", self.manifest, "--quiet")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_exit_3_on_drift(self):
        with open(os.path.join(self.frozen, "extra.blend"), "wb") as fh:
            fh.write(b"x")
        proc = self._run("--manifest", self.manifest, "--quiet")
        self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)

    def test_exit_4_without_arguments(self):
        proc = self._run()
        self.assertEqual(proc.returncode, 4, proc.stdout + proc.stderr)

    def test_root_quiet_does_not_crash(self):
        """`--root --quiet` 走的是另一条汇总分支（`failures` 而不是 `drift`）。"""
        proc = self._run("--root", self.tmp, "--quiet")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("manifests=1", proc.stdout)


if __name__ == "__main__":
    unittest.main()
