# -*- coding: utf-8 -*-
"""M08 验收判据（`coordination/acceptance.py`）的测试。

重点同样是**「通过」与「测不出来」不许同形**：

* 缺事实 ⇒ `CANNOT`（exit 4），不许当 PASS；
* 交付期望打在一份**旧场景形状**的事实上，必须在**具名行**上 FAIL（这是负控：
  证明这支脚本看得见差异，而不是"什么都说好"）；
* 三次 sha 不一致 ⇒ FAIL（验收期间有人在写文件）。
"""
import json
import os
import tempfile
import unittest

from coordination import acceptance


def good_facts():
    return {
        "blend": "delivery_v1.blend",
        "sha256_reads": ["a" * 64, "a" * 64, "a" * 64],
        "rigids_u323": 312,
        "rigids_u324": 312,
        "placeholders": 0,
        "bones": 482,
        "vertices": 25506,
        "skirt_bones_0": 18,
        "skirt_bones_11": 0,
        "cache_verdict": "OK_UNBAKED",
        "mask": {
            "verdict": "WIRED",
            "constraints_capped": False,
            "skipped_count": 0,
            "blocked_and_should_collide": 0,
            "nocollide_pairs_still_colliding": 0,
            "unexpressible_pairs": 0,
        },
        "errors": [],
    }


def j_baked_facts():
    """11-07 那份交付文件的形状：324 刚体（U323 323）、11 个 `$name_j` 占位体、通道没接。"""
    facts = good_facts()
    facts.update({
        "blend": "J_baked.blend",
        "rigids_u323": 323,
        "rigids_u324": 324,
        "placeholders": 11,
        "bones": 488,
        "vertices": 25432,
        "cache_verdict": "DEFECT_BAKED_OUTDATED",
        "mask": {
            "verdict": "PARTIAL",
            "constraints_capped": None,
            "skipped_count": None,
            "blocked_and_should_collide": 0,
            "nocollide_pairs_still_colliding": 38605,
            "unexpressible_pairs": 0,
        },
    })
    return facts


def failing_ids(report):
    return {row["id"] for row in report["rows"] if row["status"] != acceptance.PASS}


class TestJudge(unittest.TestCase):
    def test_good_facts_pass_with_exit_zero(self):
        report = acceptance.judge(good_facts())
        self.assertEqual(report["verdict"], acceptance.PASS)
        self.assertEqual(report["exit_code"], 0)
        self.assertEqual(failing_ids(report), set())

    def test_old_scene_fails_on_named_rows(self):
        """负控：交付期望打旧场景的事实上，必须**点名**红在哪几行。"""
        report = acceptance.judge(j_baked_facts())
        self.assertEqual(report["verdict"], acceptance.FAIL)
        self.assertEqual(report["exit_code"], 3)
        bad = failing_ids(report)
        self.assertIn("rigids_u323", bad)
        self.assertIn("rigids_u324_equals_u323", bad)
        self.assertIn("placeholders", bad)
        self.assertIn("cache_verdict", bad)
        self.assertIn("nocollide_pairs_still_colliding", bad)

    def test_missing_facts_are_cannot_not_pass(self):
        facts = good_facts()
        for key in ("bones", "vertices", "mask"):
            facts.pop(key, None)
        report = acceptance.judge(facts)
        self.assertEqual(report["verdict"], acceptance.CANNOT)
        self.assertEqual(report["exit_code"], 4)
        self.assertIn("bones", failing_ids(report))

    def test_sha_mismatch_fails(self):
        facts = good_facts()
        facts["sha256_reads"] = ["a" * 64, "b" * 64, "a" * 64]
        report = acceptance.judge(facts)
        self.assertEqual(report["verdict"], acceptance.FAIL)
        self.assertIn("blend_sha256_three_reads", failing_ids(report))

    def test_capped_channel_fails(self):
        facts = good_facts()
        facts["mask"]["constraints_capped"] = True
        report = acceptance.judge(facts)
        self.assertEqual(report["verdict"], acceptance.FAIL)
        self.assertIn("constraints_capped", failing_ids(report))

    def test_collector_errors_fail(self):
        facts = good_facts()
        facts["errors"] = ["stage_mask 抛异常"]
        report = acceptance.judge(facts)
        self.assertIn("collector_errors", failing_ids(report))

    def test_expectations_are_data(self):
        """换验收对象只换期望值，不改判断分支。"""
        facts = good_facts()
        facts["rigids_u323"] = 300
        facts["rigids_u324"] = 300
        report = acceptance.judge(facts, {"rigids_u323": 300})
        self.assertNotIn("rigids_u323", failing_ids(report))


class TestCli(unittest.TestCase):
    def _write(self, payload):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                             encoding="utf-8")
        handle.write(payload)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_cli_accepts_blender_log_and_writes_artifacts(self):
        facts_path = self._write("noise before\nFACTS_JSON "
                                 + json.dumps(good_facts()) + "\n")
        out_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: [os.unlink(os.path.join(out_dir, name))
                                 for name in os.listdir(out_dir)])
        code = acceptance.main(["--facts", facts_path, "--out-dir", out_dir])
        self.assertEqual(code, 0)
        written = sorted(os.listdir(out_dir))
        self.assertEqual(written, ["accept_aaaaaaaa.json", "accept_aaaaaaaa.txt"])
        with open(os.path.join(out_dir, "accept_aaaaaaaa.json"), encoding="utf-8") as fh:
            payload = json.load(fh)
        self.assertEqual(payload["verdict"], acceptance.PASS)
        self.assertEqual(payload["blend_sha256"], "a" * 64)

    def test_cli_returns_4_for_unreadable_facts(self):
        self.assertEqual(acceptance.main(["--facts", "does_not_exist.json"]), 4)

    def test_cli_returns_3_for_failing_facts(self):
        facts_path = self._write(json.dumps(j_baked_facts()))
        out_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: [os.unlink(os.path.join(out_dir, name))
                                 for name in os.listdir(out_dir)])
        self.assertEqual(acceptance.main(["--facts", facts_path,
                                          "--out-dir", out_dir]), 3)


if __name__ == "__main__":
    unittest.main()
