# M04 → M07 接口说明（门禁 / 装配 / 批量报告）

> 写这份的目的是让 M07 能**直接接线**，不用读 M04 的实验历史。
> 字段类型、单位、空值语义全部写死；标 `UNVERIFIED` 的地方**不得当已验证物理使用**。

## 0. 四个模块一句话

| 模块 | 入口 | 输入 | 输出 | 退出码 |
|---|---|---|---|---|
| 求值器 | `python -m mmdpipe.physics_gate` | measurement + profile | 门禁 JSON | `PASS=0 / FAIL=1 / ERROR=2 / UNKNOWN=3` |
| 装配器 | `python -m mmdpipe.measure` | 逐帧 JSONL ×2 | measurement JSON | `0` 成功 / `2` 输入不可用 |
| 批量报告 | `python -m mmdpipe.gate_report` | 样本清单 JSON + profile | 混淆矩阵 JSON | `0` 成功 / `2` 输入或划分不足 |
| 库调用 | `from mmdpipe import physics_gate, measure, gate_report` | 同 CLI | 同 CLI | — |

**M07 只应消费前三个 CLI 的 JSON**，不要 import 内部函数做判定——内部口径会随实验变，JSON 契约才是冻结的。

## 1. 门禁 JSON（`physics_gate.evaluate` 输出）

```json
{
  "gate_version": "physics_gate/1",
  "profile_id": "exploratory_v0",
  "profile_status": "exploratory",
  "threshold_version": "pg/0.1-exploratory",
  "sample_id": "synthetic-bad",
  "evidence_mode": "synthetic",
  "status": "FAIL",
  "failed_gates": ["frozen", "overshoot", "penetration"],
  "unknown_gates": [],
  "out_of_scope_gates": [],
  "gate_results": {
    "overshoot": {"gate": "overshoot", "status": "FAIL", "reason": "...", "evidence": {}, "missing": []},
    "frozen":    {"gate": "frozen", "status": "FAIL", "reason": "...", "evidence": {}, "missing": []},
    "penetration": {"gate": "penetration", "status": "FAIL", "reason": "...", "evidence": {}, "missing": []}
  },
  "evidence_paths": ["..."],
  "warnings": ["profile_status=exploratory：阈值未经生产标定，结论只能当探索性证据"],
  "diagnosis_ref": {"schema_version": "diagnose/1", "primary": "F3", "confidence": "suspected",
                    "judgment_fingerprint": "..."}
}
```

字段级说明：

| 字段 | 类型 | 取值 | 空值语义 |
|---|---|---|---|
| `status` | str | `PASS` / `FAIL` / `UNKNOWN` | 聚合顺序 **FAIL > UNKNOWN > PASS**；`OUT_OF_SCOPE` 不参与聚合 |
| `profile_status` | str | `exploratory` / `production` | 非 `production` 时面板必须显式标注「探索性」 |
| `failed_gates` / `unknown_gates` / `out_of_scope_gates` | list[str] | 门禁名 | 空数组 = 该类没有 |
| `gate_results.*.reason` | str | 人读一句话（含实测值） | 不会为空 |
| `gate_results.*.evidence` | obj | 该门禁的关键数值（带单位后缀的键名） | 缺数据时为空对象 |
| `gate_results.*.missing` | list[str] | 缺失字段的点路径 | 空 = 证据齐全 |
| `diagnosis_ref` | obj \| null | M03 `diagnose/1` 的摘要 | `null` = 未传诊断，**门禁判定不依赖它** |

**面板可直接显示**：`status` / `profile_status` / 三类 `*_gates` / 每个 `reason`。
**不要显示**：`gate_results.*.evidence` 里的裸浮点按原样，需自己加单位与取整（`median_deg` 已是度）。

## 2. measurement JSON（`measure` 输出，也是 `physics_gate` 的输入）

```json
{
  "sample_id": "S2_s2_x07",
  "evidence_mode": "baked",
  "frames": {"start": 1, "end": 240},
  "dynamics": {"median": 37.2, "p95": 72.8, "max": 93.3, "spike_count": 0,
               "bones": 420, "spike_threshold_deg": 155.4,
               "aggregation": "frame_max_then_percentile"},
  "frozen": {"parent_delta_deg": 66.41, "target_delta_deg": 0.0,
             "consecutive_frames": 60, "bone": "下擺_0_1", "candidates": 18},
  "penetration": {"roi": "row11", "max_depth_m": -0.202, "frames": 31,
                  "bones": 11, "epsilon_m": 0.02}
}
```

单位约定（**全部写在这，别自己猜**）：

| 字段 | 单位 | 方向/符号 |
|---|---|---|
| `dynamics.median/p95/max` | 度 | 每帧「骨最大角」的统计量，非负 |
| `dynamics.spike_count` | 帧 | 整数 |
| `frozen.parent_delta_deg` | 度 | 父链增量，非负 |
| `frozen.target_delta_deg` | 度 | 目标相对父骨的最大角，非负 |
| `frozen.consecutive_frames` | 帧 | 角度 ≤ `frozen_eps_deg` 的最长连续段 |
| `penetration.max_depth_m` | 米 | **负值 = 穿入**（与 S4 历史 −0.202 m 一致） |
| `penetration.frames` / `bones` | 帧 / 骨 | 超过 `epsilon_m` 的计数 |

`penetration` 段**可以不存在**（没测），门禁返回 `UNKNOWN` —— 这不是错误，是诚实。

`measurement.out_of_scope`（可选，字符串数组）：声明「本样本的某类不在 M04 口径内」，
例如 `["penetration"]`。被声明的门禁输出 `OUT_OF_SCOPE`，不参与聚合。

## 3. 混淆矩阵 JSON（`gate_report` 输出）

```json
{
  "report_version": "gate_report/1",
  "profile_id": "exploratory_v0",
  "profile_status": "exploratory",
  "threshold_version": "pg/0.1-exploratory",
  "calibration": {"tp": 1, "fp": 0, "tn": 1, "fn": 0, "unknown": 0, "conclusive": 2,
                  "false_positive_rate": 0.0, "false_negative_rate": 0.0, "detail": []},
  "holdout": {"tp": 1, "fp": 0, "tn": 2, "fn": 0, "unknown": 0, "conclusive": 3,
              "false_positive_rate": 0.0, "false_negative_rate": 0.0, "detail": []},
  "exploratory": true,
  "conclusion": "探索性结论：阈值未标定，holdout 只作一次检查，不得宣称生产级误判率"
}
```

三条 M07 必须遵守的读法：

1. `false_positive_rate` / `false_negative_rate` 可能是 `null` —— 意思是「这一类没有有结论的样本」，
   **不是 0**，不许在面板上画成 0%。
2. `unknown` 单列，**不参与** 误报率/漏报率分母，也不计入对错。
3. 缺少 `calibration` / `holdout` 划分时，`gate_report` 直接退出码 2，**不产出报告**（防虚假 100%）。

## 4. 配置

| 文件 | 作用 | 可改 |
|---|---|---|
| `presets/physics_gate/exploratory_v0.json` | 三类门禁阈值（含 `unit` / `source`） | 改值必须升 `threshold_version` |
| `presets/physics_gate/assembly_v1.json` | 逐帧→聚合的口径（尖峰 k/下限、冻结 eps、穿透 epsilon） | 同上；改了口径要重跑装配 |

## 4.1 状态与错误：两条可断言的表述（M07 照这个写解析）

**（一）聚合只在三级之间发生**

> `status ∈ {PASS, FAIL, UNKNOWN}`，优先级 `FAIL > UNKNOWN > PASS`；
> `OUT_OF_SCOPE` 在聚合前被排除，若三类门禁全被排除则 `status = UNKNOWN`。

**（二）`ERROR` 不产出 JSON**

> `ERROR` **不是** `status` 的取值。它是配置/输入异常：CLI 返回**退出码 2**，
> **不写任何 gate JSON**（`--out` 指定的文件不会出现）。消费方只能看退出码；
> 若按「`status == "ERROR"`」写解析分支，那条分支**永不可达**。

```powershell
# 自检：配置错误 → 退出码 2 且 --out 文件不存在
python -m mmdpipe.physics_gate --measurement m.json --profile 坏配置.json --out gate.json
$LASTEXITCODE   # 期望 2
Test-Path gate.json   # 期望 False
```

这条由 `tests/test_physics_gate.py::TestCli::test_config_error_exits_2_and_writes_no_json` 钉住。



本轮全部真数字都是**合成证据**。以下三条在此状态下**都没有真实样本支撑**：

- **UNVERIFIED**：过冲门禁的 `p95_max_deg=120` / `max_abs_floor_deg=200` / `spike_count_max=3` 只是量级参照，尚未用真实 measurement 标定；
- **UNVERIFIED**：冻结门禁的 `parent_delta_min_deg=15` / `target_delta_deg=1.0` 取自 S3 单一实测（父链 66.41°、目标 0.00°），没有第二组独立样本；
- **UNVERIFIED**：穿透门禁从未在真实样本上取数，`penetration` 段至今只有合成演示。

真标定挂在 `M04-calib`（拿 M02 阶段 C 的逐帧产物算），产物是 `confusion_matrix.json` 的**有数字版本**。
在那之前，面板上的门禁结论只能标「探索性」。
