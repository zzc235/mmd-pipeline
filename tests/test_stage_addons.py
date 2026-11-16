# -*- coding: utf-8 -*-
"""`stage.ensure_addons()` 的**正控 / 反控**：证明「装上了」而不是「看起来通过」。

背景（`0321505`）：扩展装成 `bl_ext.user_default.mmd_tools` 时，`addon_utils.enable("mmd_tools")`
**不抛异常**、`bpy.ops.mmd_tools` 也看起来存在（命名空间懒建），但 `import_model` 根本没注册
⇒ `ensure_addons()` 报 True，`stage_import()` 静默产出一份「0 刚体」的场景。这条缺陷属于
「假成功」那一族（`D-086` / `D-125`）：判据打在没改的那份文件上，或者只断言返回值。

所以这里不拿返回值当证据：

* **正控**：扩展名对了 ⇒ 必须真的**调了 enable**（断言到被调对象与实参这一层），
  且**注册表里真的出现算子**，`require_importer()` 不抛；
* **反控①**：`enable()` 不抛、甚至返回 True，但算子没注册 ⇒ 必须判红（返回 False / 抛）；
* **反控②**：安装的是**扩展名写错的**那份（真实候选名的 `_typo` 变体）⇒ 必须判红；
  再把候选名改成真实安装名 ⇒ 立刻变绿（证明判红是"名字对不上"，不是仪器坏了）；
* **反控③**：`hasattr` 为 True 但 `get_rna_type()` 抛 ⇒ 不算注册（懒建命名空间的现场）；
* 没有 `addon_utils` 的纯 Python 环境 ⇒ 判红，不抛 ImportError（抛了会被外层吞成一句
  「导入失败」，又是一次看起来通过）。

不开 Blender：`bpy` / `addon_utils` 都是这里注入的替身，`mmdpipe.stage` 走
`tests/test_stage_wiring.py` 的同一个离屏加载器（假 `bpy` / 假 `mathutils`）。
"""
import os
import sys
import types
import unittest

# 复用 `test_stage_wiring.py` 的离屏加载器（假 `bpy` / 假 `mathutils`）。
# discover 走 `-t tests` 时 tests 目录已在 sys.path 上；直接 `python -m unittest tests.test_...`
# 时不在，所以自己补一下（两种跑法都要能绿）。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_stage_wiring import load_stage      # noqa: E402


# ---------------------------------------------------------------- 假注册表 / 假 addon_utils

class Registry:
    """磁盘上装了什么、enable 被谁调过、哪些 `(命名空间, 算子)` 真注册上了。"""

    def __init__(self, installed=(), registers=True, namespaces=None):
        self.installed = set(installed)   # 真装着的模块名（含 `bl_ext.<repo>.` 前缀）
        self.registers = registers        # False = 装上了、enable 也"成功"，但算子没注册
        self.enabled = set()              # enable 成功的模块名
        self.enable_calls = []            # [(module, default_set, persistent)]
        self.checks = []                  # addon_utils.check() 的实参
        self.ops = set()                  # {(namespace, operator)}
        # 模块名 → 算子命名空间；不给就取模块名最后一段（Blender 的常规行为）
        self.namespaces = dict(namespaces or {})

    def namespace_of(self, module):
        return self.namespaces.get(module, module.rsplit(".", 1)[-1])


class FakeAddonUtils(types.ModuleType):
    """够 `stage.ensure_addons()` 用的最小 `addon_utils`。

    `enable()` 对不存在的模块**返回 None、不抛**——这是 Blender 的真实行为，
    也正是那条假成功的入口。
    """

    def __init__(self, registry):
        super().__init__("addon_utils")
        self.registry = registry

    def enable(self, module, default_set=False, persistent=False):
        reg = self.registry
        reg.enable_calls.append((module, default_set, persistent))
        if module not in reg.installed:
            return None
        reg.enabled.add(module)
        if reg.registers:
            reg.ops.add((reg.namespace_of(module), "import_model"))
        return True

    def check(self, module):
        reg = self.registry
        reg.checks.append(module)
        on = module in reg.enabled
        return (on, on)


class FakeOpNode:
    def __init__(self, registry, namespace, op):
        self._registry = registry
        self._namespace = namespace
        self._op = op

    def get_rna_type(self):
        if (self._namespace, self._op) in self._registry.ops:
            return self
        # Blender 没注册时的真行为：属性取得到，一碰 RNA 就 KeyError
        raise KeyError("could not be found")


class FakeNamespace:
    """插件命名空间是**懒建**的：任何算子名都取得到，只有 `get_rna_type()` 才区分。"""

    def __init__(self, registry, name):
        self._registry = registry
        self._name = name

    def __getattr__(self, op):
        if op.startswith("_"):
            raise AttributeError(op)
        return FakeOpNode(self._registry, self._name, op)


class FakeOps:
    def __init__(self, registry):
        self._registry = registry

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return FakeNamespace(self._registry, name)


class FakeBpyAddons(types.ModuleType):
    def __init__(self, registry):
        super().__init__("bpy")
        self._registry = registry
        self.ops = FakeOps(registry)


# ---------------------------------------------------------------- 用例

class TestEnsureAddons(unittest.TestCase):
    def setUp(self):
        self.stage, _ = load_stage()
        self._orig_bpy = self.stage.bpy
        self._orig_candidates = dict(self.stage.ADDON_CANDIDATES)
        self._orig_addon_utils = sys.modules.pop("addon_utils", None)
        self.addCleanup(self._restore)

    def _restore(self):
        self.stage.bpy = self._orig_bpy
        self.stage.ADDON_CANDIDATES = self._orig_candidates
        sys.modules.pop("addon_utils", None)
        if self._orig_addon_utils is not None:
            sys.modules["addon_utils"] = self._orig_addon_utils

    def install(self, installed=(), registers=True, namespaces=None):
        registry = Registry(installed, registers, namespaces)
        sys.modules["addon_utils"] = FakeAddonUtils(registry)
        self.stage.bpy = FakeBpyAddons(registry)
        return registry

    # ------------------------------------------------------------ 正控

    def test_positive_control_extension_name_really_registers(self):
        """正控：该装上时必须真装上——不是"返回 True"，而是**真的调了 enable + 算子真注册**。"""
        registry = self.install(installed={"bl_ext.user_default.mmd_tools"})
        status = self.stage.ensure_addons(names=("mmd_tools",))
        self.assertEqual(
            status, {"mmd_tools": True},
            "该装上却没报装上；实际 enable 调用 %r" % (registry.enable_calls,))
        self.assertIn(
            ("bl_ext.user_default.mmd_tools", False, False), registry.enable_calls,
            "返回了 True 但根本没调 enable（真名）——这就是「自检打在了没改的那份文件上」；"
            "实际调用 %r" % (registry.enable_calls,))
        self.assertTrue(
            self.stage.operator_registered(self.stage.bpy.ops.mmd_tools, "import_model"),
            "enable 调了、注册表里却没有 import_model：实际注册 %r" % (registry.ops,))
        self.stage.require_importer()          # 不抛 = 导入前那道闸放行

    # ------------------------------------------------------------ 反控①

    def test_negative_control_enable_succeeds_but_operator_missing(self):
        """反控①：`enable()` 不抛、还返回 True，但算子没注册 ⇒ 必须判红。"""
        registry = self.install(installed={"bl_ext.user_default.mmd_tools"},
                                registers=False)
        status = self.stage.ensure_addons(names=("mmd_tools",))
        self.assertEqual(
            status, {"mmd_tools": False},
            "enable() 没抛异常、还返回 True，但算子没注册；这里报 True 就是那条假成功。"
            "实际调用 %r，注册表 %r" % (registry.enable_calls, registry.ops))
        with self.assertRaises(RuntimeError):
            self.stage.require_importer()

    # ------------------------------------------------------------ 反控②

    def test_negative_control_wrong_extension_name_turns_red(self):
        """反控②：装着的是候选名的 `_typo` 变体 ⇒ 判红，且**查表逻辑真的跑过两遍**。"""
        registry = self.install(installed={"bl_ext.user_default.mmd_tools_typo"})
        status = self.stage.ensure_addons(names=("mmd_tools",))
        self.assertEqual(
            status, {"mmd_tools": False},
            "扩展名对不上却报装上了；实际 enable 调用 %r" % (registry.enable_calls,))
        self.assertEqual(
            [call[0] for call in registry.enable_calls],
            list(self.stage.ADDON_CANDIDATES["mmd_tools"]),
            "候选名列表没被逐个试（连「查表逻辑存在」都证明不了）；实际 %r"
            % (registry.enable_calls,))

    def test_negative_control_name_sensitivity_fix_turns_green(self):
        """反控②的灵敏度：把候选名换成真实安装名 ⇒ 同一场景立刻变绿。

        没有这一步，「判红」可能只是仪器坏了（永远红）；有了它，红/绿都归因到名字。
        替身里这份扩展的模块名/`extension id` 是错的（`..._typo`），但它注册的算子命名
        空间仍是 `mmd_tools` —— 所以名字一对上就真的能用；这不是"松判据"，是模拟
        「目录/扩展名被改名、插件本体没变」的现场。
        """
        registry = self.install(
            installed={"bl_ext.user_default.mmd_tools_typo"},
            namespaces={"bl_ext.user_default.mmd_tools_typo": "mmd_tools"})
        self.stage.ADDON_CANDIDATES["mmd_tools"] = ("bl_ext.user_default.mmd_tools_typo",)
        status = self.stage.ensure_addons(names=("mmd_tools",))
        self.assertEqual(status, {"mmd_tools": True},
                         "改成真实安装名还是红 ⇒ 判红不是名字问题；实际调用 %r"
                         % (registry.enable_calls,))
        self.assertTrue(self.stage.operator_registered(self.stage.bpy.ops.mmd_tools,
                                                       "import_model"),
                        "变绿了但注册表里没有 import_model：%r" % (registry.ops,))

    # ------------------------------------------------------------ 反控③

    def test_hasattr_is_not_a_probe(self):
        """反控③：命名空间懒建 ⇒ `hasattr` 为 True，但算子没注册。"""
        self.install(installed=())            # 什么都没装
        namespace = self.stage.bpy.ops.mmd_tools
        self.assertTrue(hasattr(namespace, "import_model"),
                        "替身没模拟出「懒建命名空间」（真 Blender 里 hasattr 是 True）")
        self.assertFalse(self.stage.operator_registered(namespace, "import_model"),
                         "算子没注册却判注册了 —— 判据退回了 hasattr")

    def test_missing_addon_utils_is_red_not_an_exception(self):
        """反控③：没有 `addon_utils`（纯 Python）⇒ 判红，不许抛异常被外层吞掉。"""
        sys.modules.pop("addon_utils", None)
        self.stage.bpy = FakeBpyAddons(Registry())
        status = self.stage.ensure_addons(names=("mmd_tools",))
        self.assertEqual(status, {"mmd_tools": False})

    # ------------------------------------------------------------ 无算子断言的插件

    def test_plugin_without_operator_assertion_uses_module_state(self):
        """`jinfengling_hsr_addon` 没有算子级断言 ⇒ 退回「模块真启用了吗」。

        这条同样要证明**真的调了 enable**，而不是只看返回值。
        """
        registry = self.install(
            installed={"bl_ext.user_default.jinfengling_hsr_addon"})
        status = self.stage.ensure_addons(names=("jinfengling_hsr_addon",))
        self.assertEqual(status, {"jinfengling_hsr_addon": True})
        self.assertIn(
            ("bl_ext.user_default.jinfengling_hsr_addon", False, False),
            registry.enable_calls,
            "报 True 却没调 enable；实际 %r" % (registry.enable_calls,))


if __name__ == "__main__":
    unittest.main()
