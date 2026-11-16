# M07 · 产物路径表（isolated vs legacy）

> 2026-11-16 · 来源：`mmdpipe/layout.py`（规则）、`mmdpipe/runner.py` L164–175（实际写盘点）、
> `addon/mmd_pipeline/status.py`（面板侧解析）。全部逐行核过，不是照抄 README。

## 1. 两种布局的落点矩阵

`--out` 记作 `<out>`，`<run>` = `run_id`（由 `started_at` 生成，如 `20261116_120000`）。

| 产物 | isolated（**默认**） | legacy（旧行为） |
|---|---|---|
| `pipeline_state.json` | `<out>/pipeline_state.json`（**不跟 run 走**，永远是"最近一次"） | 同左 |
| 帧序列 `s_XXXX.png` | `<out>/work/<run>/frames/` | `<out>/frames/` |
| `result.mp4` | `<out>/work/<run>/result.mp4` → 通过后复制到 `<out>/final/<run>/result.mp4` | `<out>/result.mp4`（无 final 概念） |
| `contact_sheet.png` / `camera.json` / `scene.blend` | `<out>/work/<run>/` → 通过后复制进 `final/<run>/` | `<out>/` |
| 中间 PMX/VMD 副本、拼接 `chain.vmd` | `<out>/work/<run>/` | `<out>/` |
| `run.log`（operator 写） | `<out>/run.log` | 同左 |

规则出处：`layout.py::plan()`（work/final 计算）与 `DELIVERABLES`（进 final 的 5 个文件名）；
`runner.py` L169–174 决定 `png_dir`/`mp4`/`state_path` 三者落点；`runner.py` L172–174 注释写明
"state 留在 `--out` 根目录，不跟着 run id 走"。

## 2. 谁读哪里

| 读者 | 读什么 | 本轮之前 | 本轮之后 |
|---|---|---|---|
| operator 进度条 | 帧数 | `<out>/frames` → isolated 下**恒 0** | `status.resolve()`：state 的 `paths.work` + `frames/`，legacy 回落 `<out>/frames` |
| operator 完成判定 | `pipeline_state.json` 的 `ok` + 进程退出码 | `<out>/pipeline_state.json`（**本来正确**） | 不变，改由 `status.summary()` 读 |
| operator 失败原因 | `blocked_by` + 阶段 issue | 只给阶段名 | `S3_chain: E-15 拼接帧数不守恒：…` |
| 面板报告区（待 C） | state 摘要 | 无 | `status.summary()`：state/log/final/frames 路径齐全 |
| E2E 验收（M08） | final 落盘 | — | 用同一套路径，不另写 |

## 3. 旧 state 的兼容

`statefile.migrate()` 把 schema 2 的记录升到 3，此时 `paths` 补成 `{root: None, work: None, final: ""}`。
`status._work_dir()` 对这种"有 paths 但 work 为 None"的记录退回 `<out>` 根目录——
**不会拼出 `None/frames`**，有专门一条测试（`test_schema2_migrated_paths_are_none`）。

## 4. 状态与进度判定口径

- 进度：`count_frames(frames_dir) / 请求帧数`，上限 99。**100% 只由进程退出码 + `state.ok` 判定**，不由帧数猜。
- 完成：`rc == 0 and state.ok` → FINISHED，并报出实际帧数与落点（final 优先）。
- 失败：`rc != 0` 或 `state.ok` 假 → 报"退出码 + 阶段 + 第一个 block 的 code+hint + 日志路径"。
- state 缺失/半写完/不是 dict：一律不抛异常，按"读不到"处理（面板里 Traceback 比"读不到"更坏）。

## 5. 尚未覆盖

- GUI 里进度条是否真的从 0 爬到 99、ESC 是否清掉 timer 与日志：**只能在 GUI 人工看**，无头覆盖不到。
- `final` 目录在失败运行中必须不存在：逻辑上由 `layout.promote()` 只在 ok 后调用保证，M08 验收时要实测一次。
