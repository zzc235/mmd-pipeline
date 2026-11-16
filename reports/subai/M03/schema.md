# M03 · DiagnosisReport schema（v1，已冻结）

> `schema_version = diagnose/1` · `taxonomy_version = F1-F6+R0/1` · `tool_version = 0.1.0`
> 冻结日期：2026-11-15。M04/M07 直接消费本文件，不需要读 M03 的推理过程。
> 两份最小示例：`schema_example_confirmed.json`（F3 confirmed）、`schema_example_insufficient.json`（证据不足）。

## 1. 顶层字段

| 字段 | 类型 | 来源 | 说明 |
|---|---|---|---|
| `schema_version` | str | 常量 | `diagnose/1`；字段有增删必须升版本 |
| `taxonomy_version` | str | 常量 | `F1-F6+R0/1`：八类 + R0 的标签版本 |
| `tool` / `tool_version` | str | 常量 | `mmdpipe.diagnose` / `0.1.0` |
| `generated_at` | str | 时间 | 本地时区 ISO8601；**不参与判定指纹** |
| `experiment_id` | str | 派生 | `diag-<sha1(input_sha+版本)[:12]>`，同一输入稳定 |
| `input_path` | str | 输入 | 绝对路径（含中文/空格原样保留） |
| `input_sha256` | str | 输入 | 采集前算一次；Blender 侧另有 `evidence.source.sha256_before/after` |
| `source_type` | str | 输入 | `pmx` \| `blend` |
| `status` | str | 工具 | `ok` \| `partial`：工具是否跑完整，**不代表故障归因成功** |
| `model` | obj | PMX/Blender | `name/version/encoding/bones/rigids/joints`，取不到的写 `null` |
| `frame_range` | obj | Blender | `start/end/fps/evidence_mode`（`baked`/\`stepped\`） |
| `cache` | obj | Blender | `is_baked/frame_start/frame_end`（`point_cache`） |
| `primary` | enum | 判据 | `F1..F6` \| `OUT_OF_TAXONOMY` \| `UNKNOWN` \| `INSUFFICIENT_EVIDENCE` |
| `secondary` | array | 判据 | 其余命中，`[{id, confidence, reason}]`，按证据完整度降序 |
| `confidence` | enum | 判据 | `confirmed` \| `suspected` \| `insufficient` |
| `diagnostics` | array | 判据 | 7 条判据（F1–F6 + OUT_OF_TAXONOMY）的完整结果，见 §2 |
| `evidence` | obj | 采集 | 原始证据（`source/model/structure/coverage/blender/ab/r0`） |
| `missing_evidence` | array | 判据 | 要补的字段清单（点号路径），给下一轮采集直接用 |
| `warnings` | array | 工具 | 阈值未标定、纯静态输入、质量字段缺失等 |
| `config` | obj | 配置 | 生效的阈值及来源（见 §4） |
| `judgment_fingerprint` | str | 派生 | 判定指纹：同输入重复运行必须相同（测试锁定） |

`status` 与 `primary` 分开是硬要求：工具跑成功 ≠ 归因成功。**任何缺证据的情况
都只能出现 `INSUFFICIENT_EVIDENCE` 或 `confidence=insufficient`，不能当 PASS。**

## 2. 每条判据的形状

```json
{
  "id": "F3",
  "title": "硬约束冻结",
  "matched": true,
  "confidence": "confirmed",
  "reason": "1 根骨在父链明显运动（≥5.0°）时相对增量≈0（≤0.50°），且 PMX 有焊接冻结根：硬约束冻结",
  "score": 3.5,
  "evidence": [
    {"key": "blender.frozen_pairs.frozen",
     "value": [{"bone": "右胸", "rot_delta_deg": 0.0, "parent_rot_delta_deg": 32.0}],
     "unit": "deg", "compare": "目标≤0.50° 而父链≥5.0°",
     "frames": "f1–f60", "source": "blend"}
  ],
  "evidence_keys": ["structure.frozen_roots", "blender.frozen_pairs.frozen"],
  "missing_evidence": []
}
```

每条证据固定 6 个键：`key`（字段名）、`value`（实测值）、`unit`（单位）、
`compare`（与什么比较）、`frames`（帧号/帧范围）、`source`（`pmx`/`blend`/`ab`/`probe`）。
少一个就不是合格证据。

## 3. 六类判据的口径（实现即契约）

| id | 关键证据（dotted key） | confirmed 条件 | 缺什么会降级 |
|---|---|---|---|
| F1 | `blender.mmd_root.is_built`、`blender.constraints`、`structure.feedback_rigids` | `is_built=False`；或 `COPY_ROTATION+COPY_TRANSFORMS==0` 且存在回填刚体 | 无 Blender 证据 → insufficient |
| F2 | `blender.point_cache.is_baked`、`.frame_start`、`.frame_end` | `is_baked=False` 且缓存帧范围已记录 | 缺帧范围 → suspected |
| F3 | `structure.frozen_roots`、`blender.frozen_pairs` | 有绑定骨骼的焊接冻结根 + 候选骨「父链≥5° 而自身≤0.5°」 | 缺动态 / 父链本身不动 → suspected |
| F4 | `structure.wide_limit_units`、`blender.unit_angles` | 零弹簧 + 限位≥1.2 rad + 实测摆角≥60° **且阈值已标定** | 阈值未标定一律 suspected |
| F5 | `coverage.gaps`、`blender.penetration` | 整行/整组无刚体 + 同族穿入实测对应 | 无穿透测量 → suspected |
| F6 | `ab.variable_changed`、`.fields_compared`、`.differing_fields`、`.result_identical` | 唯一变量明确 + 字段逐位相同 + 结果一致 | 无 A/B → 固定 `INSUFFICIENT_EVIDENCE` |
| R0 | `r0.detected` / `blender.penetration.frame==1` | 首帧即穿入 | **永远不进 F1–F6**，输出 `OUT_OF_TAXONOMY` |

选择规则：`confirmed` 优先于 `suspected`，同级比 `score`，再同级按 F1→F6 顺序。
多故障共存时其余进 `secondary`，不用 if 顺序掩盖。

## 4. 阈值与来源（`config.thresholds`）

| 键 | 值 | 单位 | 来源 | 已标定 |
|---|---:|---|---|---|
| `spring_zero_eps` | 1e-9 | rad | 与 `pmx.py Joint.springs_zero` 同口径 | 是 |
| `f3_frozen_deg` | 0.5 | deg | 项目书 S3 证据① 烘焙增量 0.00000° | 是 |
| `f3_parent_motion_deg` | 5.0 | deg | 保守下限，**未标定** | 否 |
| `f4_wide_limit_rad` | 1.2 | rad | 项目书 S2 根部限位 ±1.5708 rad | 是 |
| `f4_angle_deg` | 60.0 | deg | **未标定**（「接近水平」的保守下限） | 否 |
| `f5_gap_ratio` | 0.5 | 行比例 | 项目书 S4 第 11 行 11/11 根骨无刚体 | 是 |
| `f6_numeric_eps` | 1e-9 | raw | 项目书 S8 A/B 逐位相同 | 是 |

`f4_calibrated=false` 时，F4 即使结构+角度都对，最高也只给 `suspected` —— 这是刻意的。

## 5. CLI 契约（给 M07）

```powershell
# 1) 静态结构检查（纯 Python，3 秒内）
python -m mmdpipe.diagnose --pmx "模型.pmx" --out "diagnosis.json"

# 2) 可选：带 A/B 测量文件判 F6
python -m mmdpipe.diagnose --pmx "模型.pmx" --ab "A.json" "B.json" --out "diagnosis.json"

# 3) Blender 运行期检查（需串行取 blender.lock）
& "E:\code\Blender\blender-5.2.2-windows-x64\blender.exe" -b -P "mmdpipe\diagnose_blender.py" -- `
    --blend "场景.blend" --out "diagnosis.json" --frames 60 [--pmx "模型.pmx"]
```

| 退出码 | 含义 |
|---:|---|
| 0 | JSON 已写盘（`status=ok/partial` 都算成功），判定看 `primary`/`confidence` |
| 1 | 仅 `--fail-on-confirmed` 时：`primary` 的 `confidence=confirmed` |
| 2 | 命令行参数错误 |
| 3 | 输入不可读 / PMX 解析失败（**不写半成品 JSON**） |
| 4 | （仅 Blender 入口）JSON 已写盘但 `status=partial` |

Blender 入口另加（可选，不是必需参数）：`--pmx` 合并静态证据、`--watch-bones`、
`--config`、`--experiment-id`。给了 `--pmx`，F3 才可能 `confirmed`（冻结结构在 PMX 层）。

Blender 入口在 `json.dump + fsync` 之后走 `os._exit()`：312 刚体的析构段错误是既有问题，
不掩盖真正的运行错误（错误仍走退出码 3 并写 stderr）。

## 6. 稳定性

* 同一输入重复运行 → `judgment_fingerprint` 必须相同（`tests/test_diagnose.py` 锁定）。
  指纹只含判定本身，不含 `generated_at` 与路径。
* `missing_evidence` 是「下一轮该采什么」的待办列表，M04 可直接当采集清单。
