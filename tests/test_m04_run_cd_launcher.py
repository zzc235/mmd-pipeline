# -*- coding: utf-8 -*-
"""启动器的两层拼装（离屏，不开 Blender、不碰锁）。

这一层只负责两件事，两件都不该由 `coordination.lock guard` 操心：
owner 的两段写（命令行里不出现竖线）与 guard 命令的正确拼装。锁的行为本身归 `guard`（`D-213`）。
"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LAUNCHER = os.path.join(os.path.dirname(HERE), "reports", "subai", "M04", "scripts",
                        "m04_run_cd_locked.py")


def load_launcher():
    spec = importlib.util.spec_from_file_location("m04_run_cd_locked_uut", LAUNCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


L = load_launcher()


class ResolveOwnerTest(unittest.TestCase):
    def test_single_string_with_pipe(self):
        self.assertEqual(L.resolve_owner("模块负责2|A2", "", ""), "模块负责2|A2")

    def test_two_parts_are_joined_in_python(self):
        got = L.resolve_owner("", "模块负责2", "A2")
        self.assertEqual(got, "模块负责2" + "|" + "A2")

    def test_single_string_without_pipe_is_refused(self):
        # 反控：竖线被 shell 吞掉的那种形状（owner 变成「模块负责2A2」）必须被拒，别让它走到锁那里
        self.assertEqual(L.resolve_owner("模块负责2A2", "", ""), "")

    def test_nothing_given(self):
        self.assertEqual(L.resolve_owner("", "", ""), "")
        self.assertEqual(L.resolve_owner("", "模块负责2", ""), "")


class BuildGuardCmdTest(unittest.TestCase):
    def test_guard_wraps_the_driver_after_dashdash(self):
        cmd = L.build_guard_cmd("A|B", "note", r"C:\root", r"C:\drv.py", ["--x", "1"],
                                wait_s=1800, heartbeat_every=240)
        self.assertIn("guard", cmd)
        self.assertIn("--owner", cmd)
        self.assertEqual(cmd[cmd.index("--owner") + 1], "A|B")
        self.assertEqual(cmd[cmd.index("--wait") + 1], "1800")
        self.assertEqual(cmd[cmd.index("--heartbeat-every") + 1], "240")
        cut = cmd.index("--")
        self.assertEqual(cmd[cut + 1:], [cmd[cut + 1], r"C:\drv.py", "--x", "1"])

    def test_owner_is_one_argv_token(self):
        cmd = L.build_guard_cmd("模块负责2|A2", "n", ".", "d.py", [], wait_s=0)
        self.assertEqual(sum(1 for c in cmd if c == "模块负责2|A2"), 1)
        self.assertNotIn("模块负责2|A2".replace("|", ""), cmd)

    def test_two_part_form_is_forwarded_not_composed(self):
        # guard 自己已支持两段写（且与 --owner 互斥），这里必须原样透传、不再自己拼竖线
        cmd = L.build_guard_cmd("", "n", ".", "d.py", ["--y"],
                               owner_module="模块负责2", owner_tree="A2")
        self.assertIn("--owner-module", cmd)
        self.assertEqual(cmd[cmd.index("--owner-module") + 1], "模块负责2")
        self.assertEqual(cmd[cmd.index("--owner-tree") + 1], "A2")
        self.assertNotIn("--owner", cmd)
        self.assertFalse(any("|" in c for c in cmd), cmd)


if __name__ == "__main__":
    unittest.main()
