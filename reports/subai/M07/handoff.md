# M07 · handoff（给 D0 / M08 / 后续接手的人）

## 1. 现在能用的（已入库到 `ai/a4`，未合 main）

| 能力 | 入口 | 证据 |
|---|---|---|
| 报告区读状态 | `addon/mmd_pipeline/status.py`：`summary(out)` / `report_lines(out)` / `failure_reason(state)` | `tests_bpy/test_status.py` 18 条 |
| 四区面板 | `panels.py`（资产/物理/渲染/报告）+ `params.ZONE_OF` | `tests_bpy/test_zones.py` 6 条 |
| 诊断按钮 | `mmd_pipeline.diagnose` → `run_tool.py diagnose` | 退出码 0/1 都当有效结果 |
| 门禁按钮 | `mmd_pipeline.gate` → `run_tool.py physics_gate` | 退出码 2 = 无 JSON，面板只报"配置或输入不可用" |
| 打包 | `build_addon.py` | `stage()` 实跑 42 文件；validate/build 待锁 |

## 2. 三条读法（面板与 M08 都别再踩）

1. **`UNKNOWN` 不是 `PASS`**：门禁三类全范围外或没测过都给 `UNKNOWN`，面板只显示探索性结论。
2. **`ERROR` 没有 JSON**：`physics_gate` 配置/输入错时退出码 2 且 `--out` 文件不出现；按 `status == "ERROR"` 写分支永远走不到。
3. **`false_positive_rate` 可能是 `null`**：那是"这一类没有有结论的样本"，不是 0%。

## 3. 还没验的（M08 要接着做，不要当已完成）

| 项 | 状态 | 需要的条件 |
|---|---|---|
| `extension validate` / `build` | 未执行 | Blender 锁（队列第 4 位） |
| 隔离安装 + `smoke.py` 8 项 | 未执行 | 同上 + 临时 `BLENDER_USER_SCRIPTS` |
| 12 帧 isolated E2E + ffprobe | 未执行 | 同上 + 一个已知能跑的 PMX/VMD/preset |
| 受控失败路径（缺 VMD → 可读错误、不产 final） | 未执行 | 同上（不渲染，不占长渲染预算） |
| GUI 面板排版/进度条/ESC | 未验证 | 只能人工看，自动覆盖不到 |
| 写用户全局配置的安装 | **未获批准** | 11 §9 要 D0 + Owner 双批准 |

## 4. 交接要点

- `status.py` 不 import bpy，可以脱离 Blender 单测；`panels.py` 只负责画，文本逻辑全在 `status.report_lines`。
- 参数新增时**必须**在 `params.ZONE_OF` 归区，否则 import 直接抛 `ValueError`（故意设计：宁可装不上，也不要旋钮静默消失）。
- `run_tool.py` 的工具白名单只有 `diagnose / physics_gate / gate_report`；要加工具先改白名单 + smoke 断言，别走任意命令。
- 打包只认 `mmd_pipeline-<version>.zip`；`dist/` 里的旧包不算本次产物。
