# M02 · 「交付场景能不能由今天的代码重建」——不能，缺口有确切数字

问题（D0 派）：`out/subai/M02/blend/B_from_blend1.blend`（Nov-7 交付物，324 刚体）能不能用今天的
`mmdpipe/stage.py` + `presets/feiying.json` 从 PMX 重新建出来。

**答案：不能。**今天跑一遍得到 **312** 刚体、**0** 个 `$name_j` 占位体、**0** 个第 11 行刚体；
交付物是 **324** = 313 + 11。

## 一、实测（锁 13:23:0x→13:23:23，14 s，`m02_rebuild_scene_v3.py`）

源：`E:\blender模型\没有外套本家模型\星穹铁道—飞霄（无外套）.pmx`（sha `2db720a2…49a267`，3 316 950 B）
预设：`presets/feiying.json`（走 `preset.load()`，`preset_has_import=true`）

| 项 | import 后 | build 后 | 交付物 `B_from_blend1` |
|---|---:|---:|---:|
| 刚体总数 | **312** | **312** | 324 |
| `$name_j` 占位体 | **0** | **0** | 11 |
| `下擺_0_*` 有刚体 | **18** | 18 | 18 |
| `下擺_11_*` 有刚体 | **0** | **0** | 11 |
| 骨 / 顶点 / 新增对象 | 482 / 25506 / 706 | 482 / — / — | — |
| `skirt_bodies` | — | 147 | 147 |

`build` 侧无问题：`issues: []`、`is_built: true`、`chain_ratio 0.946`、约束
`COPY_ROTATION 264 / COPY_TRANSFORMS 31 / TRANSFORM 32 / DAMPED_TRACK 4 / IK 4 / LIMIT_ROTATION 2`、
`solver_iterations 20`、`substeps 10`。

对账：

```
312（今天重建，import 阶段）
  = 313（baseline.blend = 312 + 地面_物理）− 1（地面不在导入阶段）+ 0
324（B_from_blend1）
  = 313（baseline）+ 11（$name_j 占位体）
```

PMX 侧独立核对：312 rigids / 288 骨带刚体 / `下擺*` 刚体 147（族 0–10）/
`下擺_11_*` 骨存在 11 根但**刚体 0**。⇒ 今天没有任何代码路径会造出那 11 个占位体。

## 二、缓存状态（两份产物都干净）

`m02_cache_gate.py` → `cache_gate_rebuild.json`：

| 产物 | 刚体 | is_baked | is_outdated | verdict | exit |
|---|---:|---|---|---|---:|
| `rebuild_import.blend`（4 851 025 B） | 312 | false | true | `OK_UNBAKED` | **0** |
| `rebuild_built.blend`（5 271 126 B） | 312 | false | true | `OK_UNBAKED` | **0** |

⇒ 这两份可以直接当「干净输入」（无过期缓存），不触发 cache 缺陷。

## 三、副产品：`stage.py` 两条会安静失败的缺陷（只报不改，块 4 归 4号）

1. **插件「假启用」：`ensure_addons()` 报 `True` 而算子没注册。**
   它用 `addon_utils.enable("mmd_tools", …)`，返回 `{'mmd_tools': True}`，但
   `bpy.ops.mmd_tools.import_model` 不存在（扩展真名是 `bl_ext.user_default.mmd_tools`，
   `opencc` 轮子只在 enable 时解包）⇒ `stage_import` 失败，**产物是「0 刚体」的安静失败**
   （v2 那次 `rigids=0`、`issues` 为空）。

   **怎么判才对（我自己复现过，`addon_gate_normal.json` / `addon_gate_isolated.json`）**：
   把 `BLENDER_USER_EXTENSIONS` 指到空目录（安全，不碰全局），得到

   | 判据 | 正常仓库 | 空仓库（算子不在） |
   |---|---|---|
   | `addon_utils.enable(...)` 是否抛异常 | 不抛 | **也不抛**（返回 `None`）⇒ 不能用来判 |
   | `hasattr(bpy.ops.mmd_tools, "import_model")` | True | **True** ⇒ **不能用来判** |
   | `bpy.ops.mmd_tools.import_model.get_rna_type()` | `MMD_TOOLS_OT_import_model` | **`KeyError: … not found`** ⇒ 可判 |
   | `bpy.ops.mmd_tools.import_model.poll()` | True | **`AttributeError: … could not be found`** ⇒ 可判 |

   **更正我 13:23 那条**：我当时建议「断言 `hasattr`」，那是错的——我那次 `hasattr` 为 True
   只是因为算子确实在，它并不具区分力。4号 的实测与我的复现一致，正确写法是
   `addon_utils.enable("bl_ext.user_default.mmd_tools", default_set=False, persistent=False)`
   + **`get_rna_type()` 不抛**（或 `poll()` 为真），否则报 BLOCK。
2. **`presets/*.json` 是差分文件。** 里面没有 `import` 段，`stage_import` 直接取 `preset["import"]`
   会 `KeyError`；必须走 `preset.load(path)`（把 `DEFAULT_PRESET` 合进来）。走 `runner.py` 的产线
   不受影响，但 M07 面板若单独调 `stage_import` 会踩。

**静默失败的尸检证据**：v3 覆盖保存同路径时，Blender 把 v2 的产物轮转成
`out/subai/M02/rebuild/rebuild_import.blend1`（93 719 B，13:22:31）。两种探法：

| 探法 | 结果 |
|---|---|
| `m02_cache_gate.py` | **`OK_NO_PHYSICS`**（连 `rigidbody_world` 都没有）— `cache_gate_rebuild_v2.json` |
| `m02_probe_blend.py` | **`objects: 0`**、`rigids: 0`、`armatures: {}`、`frame_end: 250`（Blender 默认值）— `rebuild/rebuild_import_blend1_content.json` |

也就是说：**v2 存下来的是一个空场景**——`reset_scene()` 跑过了，导入在报错前什么都没加，脚本照样存盘。
这就是「安静失败」的样子：不崩、不抛给调用方、`issues` 为空、只是世界里没有东西。
（归属依据是时间戳与保存顺序，文件本身没有自述字段。）



## 四、对 M08 的意义（D0 的硬前提成立）

- `B_from_blend1.blend` **不在当前代码的产出空间里** ⇒ 不能当 M08 的验收对象；
- 验收对象要用今天重建的产物（312 刚体、无占位体、`OK_UNBAKED`）；
- 2号 的胶囊基线若要跨工程复用，必须在新产物上重取——那 11 个静态占位体只存在于这一份交付物里。

## 五、脚本与产物

- `scripts/m02_rebuild_scene_v3.py`（本次用的版本：扩展真名 + 算子断言 + `preset.load`）
- `scripts/m02_rebuild_scene_v2.py`（`preset.load` 但用短名启用 → 0 刚体失败版，保留作对照）
- `scripts/m02_rebuild_scene.py`（v1，从未运行，只作历史）
- 产物：`out/subai/M02/rebuild/rebuild_import.blend`、`rebuild_built.blend`、`rebuild_report.json`
- 缓存判据：`reports/subai/M02/cache_gate_rebuild.json`
