# M07 · result（attempt 3）：`stage.py` 两处静默失败 —— 修好并用「应当被拒」的输入验过

> 席位 A4 · 分支 `ai/a4` · 本笔 HEAD `0321505`（父 `d059a7f` = 已并入 main 的 attempt 2）· 2026-11-16 13:30
>
> 状态：**PASS**（两条缺陷都带可复现的拒绝例）。这两条由 **1号** 在「用今天的代码重建交付场景」时实测撞出、只报不改，修法归我（块 4）。

## 1. 缺陷一：`ensure_addons()` 报 `True` 而算子根本没注册

| 项 | 旧代码 | 现在 |
|---|---|---|
| 启用名 | 只用短名 `mmd_tools` | 先试 `bl_ext.user_default.mmd_tools`，再退回短名（`ADDON_CANDIDATES`） |
| 判定 | `addon_utils.enable()` 没抛异常 ⇒ `{name: True}` | 逐个候选启用后**再验算子**：`getattr(bpy.ops.mmd_tools, "import_model").get_rna_type()` |
| 失败表现 | `stage_import` 静默产出一份 **0 刚体**的场景 | `require_importer()` 抛 `RuntimeError` → `stage_import` 返回 **E-16 的 BLOCK** |

**为什么不能继续用 `hasattr`**（本轮实测，三种环境各一遍）：

```
算子没注册时 hasattr(bpy.ops.mmd_tools, "import_model")  →  True   ← 假阳性
算子没注册时 bpy.ops.mmd_tools.import_model.get_rna_type() →  KeyError: get_rna_type("MMD_TOOLS_OT_import_model") not found
算子没注册时 bpy.ops.mmd_tools.import_model.poll()         →  AttributeError: … could not be found
```

命名空间是懒建的，`hasattr` 只能证明"名字能取到"，不能证明"算子注册了"。所以判据落在 `get_rna_type()`。

## 2. 缺陷二：预设是差分文件，`preset["import"]` 直接 `KeyError`

`presets/kafuka_hsr_look.json` 磁盘上只有 `camera` / `look` 两段（**没有 `import`**）。
走 `runner.py` → `preset.load()` 的产线没事，但**直接调 `stage_import(preset_dict)`** 的调用者会当场 `KeyError`，
而那一行在 `try` 之外 ⇒ 导入阶段直接抛栈，不是可读失败。

修法：`mmdpipe/preset.section(preset, name)` —— 用 `DEFAULT_PRESET` 补齐缺的整段/部分段；`stage_import`、
`stage_motion`、`stage_render` 三处取 `import` 段的地方都改走它。`tests/test_preset.py` 9 条钉住
（缺段补默认、部分段保留其余默认、显式值优先、未知段 `KeyError`、非 dict 拒绝、不改入参、**磁盘上确实没有 import 段**）。

## 3. 验证（本笔 HEAD `0321505`，全部在锁内跑）

| 步骤 | exit | 关键输出 | 耗时 |
|---|---:|---|---:|
| `python build_addon.py` | 0 | `Success parsing TOML` / 42 文件 / `SHA256 7b77382ee2bac46066418b29513c28ab0befe5ac675a4f1e233fd11cc06e9eed` | 2.23 s |
| 隔离安装（`BLENDER_USER_EXTENSIONS=<temp>` + `--no-prefs`） | 0 | `STATUS Installed "mmd_pipeline"` | 1.2 s |
| `tests_bpy/smoke.py` | 0 | **9/9 PASS**（新增「插件启用闸门」一项） | 1.1 s |
| `tests_bpy/stage_addon_gate.py --expect ok` | **0** | `ensure_mmd_tools=True` / `blocked=False` / **rigids=145** / `arm='卡芙卡3.0_arm'` / `objects=332`（**只给差分段 `{"look":{…}}`**） | 2.94 s |
| `tests_bpy/stage_addon_gate.py --expect blocked` | **0** | 空扩展仓库 ⇒ `ensure_mmd_tools=False` / `blocked=True` / **rigids=0** / E-16「算子没注册…先跑 ensure_addons()」 | 0.91 s |
| `python -m unittest discover -s tests -t tests -p "test_*.py"` | 0 | **251 passed / 0 failed / 15 skipped** | 15.6 s |

锁：13:26:35→13:26:43（8.6 s，一次窗口内跑完 build/install/smoke/正例/反例）。

**两条都是"喂应当被拒的输入"验的，不是"改完看着对"**：

- 反例（应当被拒）：把扩展仓库指到**空目录** ⇒ `mmd_tools` 彻底不可见 ⇒ 必须 `ensure=False` + `BLOCK` + `0 刚体`。
  旧代码在这一格里会 `ensure=True`、`blocked=False`、**静默产出 0 刚体场景**。
- 正例（修完之后仍要能用）：**只给差分段**的预设也必须导入成功 —— 这直接复现 1号 踩到的 `KeyError` 场景。

## 4. 顺带发现的一条（对所有人有用）

`hasattr(bpy.ops.<ns>, "<op>")` 不能当"算子可用"的判据。同类错误今天在这个项目里出过一次
（我用 `bpy.types` 判自己插件的 operator 注册，也是假阴性）。**判据一律落到"调用能不能取到 RNA / 能不能 poll"上。**

## 5. 已知限制

1. `jinfengling_hsr_addon` 没有算子级断言（`ADDON_OPERATORS` 里只登记了 `mmd_tools` 的 `import_model`），
   它的"可用"仍然只看 `addon_utils.check()` 的启用位；
2. 本机 `mmd_tools` 仍是**装了没启用**的状态：`stage_addon_gate --expect ok` 之所以能过，是因为
   `ensure_addons()` 在会话内启用了它（`default_set=False, persistent=False`，**不写偏好**）；
3. 面板还没接这两条闸门（面板的"运行"按钮走 `run_pipeline.py` → `runner.py`，那条路本来就走 `preset.load()`；
   若将来面板单独提供"只跑导入"的按钮，必须走 `ensure_addons()` + `require_importer()`）。
