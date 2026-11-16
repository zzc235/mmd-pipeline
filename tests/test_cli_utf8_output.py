"""CLI 输出编码契约的护栏：**子进程在 GBK 环境下，父进程按 UTF-8 解码必须成功。**

为什么这条要单独一个文件（2026-11-16，一天撞两次）：

* `coordination/lock.py` 打印中文走本地编码，测试按 UTF-8 解码 → `UnicodeDecodeError`
  → `stdout=None` → `assertIn("空闲", None)` → `TypeError`；
* 只修测试侧（钉 `encoding="utf-8"`）会把红**搬到默认环境**——也就是所有人默认会踩的那种。

所以判据是**行为**，不是"有没有写 `reconfigure`"：把子进程的 `PYTHONIOENCODING` 钉成最坏情况
`gbk`，父进程仍按 UTF-8 严格解码，还要断言 stdout 非空（`None` 与空串是同一类坑）。

护栏自己也喂了应当被拒的输入：临时造一个**不钉编码**的 CLI，必须在同一判据下失败。
新增 CLI 时把它加进 `CLI_REGISTRY`——注册即被这条护栏盯着。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORST_ENV = {"PYTHONIOENCODING": "gbk"}


def _run(argv, env_extra):
    env = dict(os.environ)
    env.pop("PYTHONIOENCODING", None)
    env.update(env_extra)
    return subprocess.run(argv, cwd=ROOT, capture_output=True, env=env, timeout=120)


def decode_utf8_strict(proc):
    """把子进程输出按 UTF-8 严格解码；失败就返回 (None, 原因)。"""
    try:
        out = proc.stdout.decode("utf-8")
        err = proc.stderr.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, "子进程输出不是合法 UTF-8：%s" % exc
    return (out, err), None


class TestCliUtf8UnderGbk(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="m00_cliutf8_")
        self.lock = os.path.join(self.tmp, "blender.lock")
        self.ev = os.path.join(self.tmp, "ev.json")
        from coordination import evidence as ev_mod
        doc = {"spec": "evidence/1", "task_id": "M00", "attempt": 1, "status": "PASS",
               "files": [], "tests": [], "artifacts": [], "known_risks": [],
               "interface": "x"}
        with open(self.ev, "wb") as fh:
            fh.write(ev_mod.canonical_bytes(ev_mod.normalize(doc)))
        self.status = os.path.join(self.tmp, "task_status.json")
        self.decisions = os.path.join(self.tmp, "decisions.jsonl")
        with open(self.status, "w", encoding="utf-8") as fh:
            json.dump({"tasks": {"M00": {"status": "PASS", "reason": "r", "next": "看点"}}},
                      fh, ensure_ascii=False)
        with open(self.decisions, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"decision_id": "D-1", "task_id": "M00"}, ensure_ascii=False) + "\n")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _registry(self):
        """每个能打印中文的 CLI：注册即被盯。"""
        return [
            ("coordination.lock", [sys.executable, "-m", "coordination.lock",
                                   "status", "--lock", self.lock]),
            ("coordination.evidence", [sys.executable, "-m", "coordination.evidence",
                                       "check", self.ev]),
            ("coordination.status", [sys.executable, "-m", "coordination.status",
                                     "--status", self.status, "--decisions", self.decisions]),
        ]

    def test_each_cli_survives_gbk_child(self):
        for name, argv in self._registry():
            with self.subTest(cli=name):
                proc = _run(argv, WORST_ENV)
                decoded, why = decode_utf8_strict(proc)
                self.assertIsNone(why, "%s：%s" % (name, why))
                out, err = decoded
                self.assertEqual(proc.returncode, 0, "%s 退出码 %d：%s" % (name, proc.returncode, err))
                self.assertTrue(out.strip(), "%s 没有任何输出（None 与空串同一类坑）" % name)

    def test_cli_reports_chinese_text(self):
        """不只看"有没有输出"：要有中文，否则把输出改成 ASCII 也能混过这条护栏。"""
        proc = _run([sys.executable, "-m", "coordination.lock", "status", "--lock", self.lock],
                    WORST_ENV)
        decoded, why = decode_utf8_strict(proc)
        self.assertIsNone(why, why)
        self.assertRegex(decoded[0], "空闲|持有")

    def test_guard_rejects_a_cli_without_utf8_stdio(self):
        """**应当被拒的输入**：临时造一个不钉编码的 CLI，必须过不了同一条判据。"""
        bad = os.path.join(self.tmp, "naive_cli.py")
        with open(bad, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("import sys\nprint('空闲：这把锁没人持')\n")
        proc = _run([sys.executable, bad], WORST_ENV)
        decoded, why = decode_utf8_strict(proc)
        self.assertIsNotNone(why, "护栏没有抓住不钉 UTF-8 输出的 CLI：%r" % (decoded,))
        self.assertIn("UTF-8", why)

    def test_control_same_script_with_utf8_stdio_passes(self):
        """正控：同一个脚本钉了编码就能过——否则「失败」可能只是脚本本身的别的问题。"""
        good = os.path.join(self.tmp, "good_cli.py")
        with open(good, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("import sys\n"
                     "for s in (sys.stdout, sys.stderr):\n"
                     "    s.reconfigure(encoding='utf-8')\n"
                     "print('空闲：这把锁没人持')\n")
        proc = _run([sys.executable, good], WORST_ENV)
        decoded, why = decode_utf8_strict(proc)
        self.assertIsNone(why, why)
        self.assertIn("空闲", decoded[0])


if __name__ == "__main__":
    unittest.main()
