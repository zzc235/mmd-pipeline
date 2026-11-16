# 判「某个 API 能不能用」的形状（M07 探测方法笔记）

2026-11-16 一天之内，同一个错在三个方向上各出现一次，三次都不是"算错"，而是**问错了对象**。
这份笔记只记形状与可复制的判法，不记结论性读数（读数在各次的 `result_attempt*.md` / 探针产物里）。

## 一、三种"按名字问"的失败方向

| 方向 | 写法 | 实测 | 错在哪 |
|---|---|---|---|
| **假阳性**（有） | `hasattr(bpy.ops.mmd_tools, "import_model")` | **True**（没注册时） | 命名空间是懒建的，`hasattr` 只证明"名字取得到" |
| **假阴性**（没有） | `hasattr(bpy.types.Action, "fcurve_ensure_for_datablock")` | **False** | 它是实例方法，类上不存在；`getattr(action, …)` 为 **True** |
| **假成功**（装上了） | `addon_utils.enable("不存在")` | 返回 `None`，**不抛** | "没抛异常"被当成"启用成功" |

前两条方向相反，根因相同：**`hasattr` 回答的是"这个名字在这台引擎的这条路径上取不取得到"，不是"这个能力可不可用"。**

## 二、为什么假阴性更难看出来

假阳性会立刻炸（调下去 `AttributeError` / `KeyError`），假阴性**不会炸**——它会让人得出"引擎没这个 API"，
于是绕开一条本来可用的路，并且**连"它有前置条件"这件事一起丢掉**：

`Action.fcurve_ensure_for_datablock(datablock, data_path, index=0, group_name="")` 的 `__doc__` 写着
*"This action must already be assigned to the data-block"*；对没挂到 ID 上的 `action.copy()` 真调，
得到的是 `RuntimeError` —— 这是**前置条件不成立**，不是**方法不存在**。按类问，这两件事会被压成一句话。

## 三、可复制的判法（三步，按顺序）

1. **存在性 —— 在将要调用的那个对象上问**，不在类/容器上问：
   `getattr(action, "fcurve_ensure_for_datablock", None)`（实例），而不是 `hasattr(bpy.types.Action, …)`（类）；
2. **可用性 —— 真调一次判据**：算子用 `get_rna_type()`（没注册 ⇒ `KeyError`）或 `poll()`（⇒ `AttributeError`），
   不用 `hasattr`；
3. **签名与前置条件 —— 读 `__doc__`，并至少造一个"前置条件不成立"的样本**看它是否按预期拒。
   只验成功路径的探针，等于没验前置条件。（3号 用 `action.copy()` 造这个样本，得到 `RuntimeError`。）

## 四、一句话

> `hasattr` 只能证明"名字能取到"；**能力要按宿主对象问、并且真调一次**。
> 问到"没有"时尤其要小心：那可能是"不在这条路径上"，不是"引擎没有"。

## 五、出处

- 假阳性 / 假成功的三条读数与三种环境的复现：`result_attempt3.md`（M07 attempt 3）；
- 假阴性（`bpy.types.Action` vs 实例）与"前置条件被一起判成不存在"：3号 2026-11-16 19:30 的只读探针
  `out/subai/M05/probe_fcurve_write_shape.py`，读侧写侧共用 `_channelbags_of()` 之后（`16eadcc`）。
- 本条属于 M07 车道（插件/扩展与 API 探测），**不是** M04 的 `known_limits.md`（那份归 2号，记的是测量口径的边界）。
