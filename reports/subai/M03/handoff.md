# M03 · 交接（给 M04 / M07 / 总控）

## 1. 已证实

| # | 结论 | 数值证据 | 证据文件 |
|---:|---|---|---|
| 1 | **S5 卡芙卡袖子 = F3 硬约束冻结（confirmed）** | 16 根袖骨（`xk_*`/`zxk_*`）局部旋转增量 **0.0°**，父链（`ひじ.L/R`）**66.41°**；PMX 有 16 个绑定骨骼的焊接冻结根 | `evidence/blend/S5_sleeve_60f.json` |
| 2 | **S7 下摆直筒 = F1 没 build（confirmed）** | `mmd_root.is_built=False`、`COPY_ROTATION=0`、312 刚体、`is_baked=False` f1–240 | `evidence/blend/probe_v1.json` |
| 3 | **S8 掩码改动不生效 = F6（confirmed）** | A/B 3 帧 800×640，像素不同 **0/512000**；PNG 字节不同只是编码元数据 | `evidence/static/S8_f6.json`、`evidence/ab/*.json` |
| 4 | S3 胸口冻结的**结构**存在 | PMX joint 0/3：`右胸`/`左胸` 焊在 `上半身2`，6 自由度全锁；胸前 6 体 idx 24–29 全 mode2 | `evidence/static/S3.json` |
| 5 | S4 覆盖缺口可精确到骨 | `下擺` 行 11：11 根骨 **11/11 无刚体**；行 3 稀疏缺 6/18 | 同上 `coverage.gaps` |
| 6 | S2 零弹簧宽限位可结构定位 | 下摆单元 154 体 / 153 mode2 / `spring_max=0` / `limit_span=1.570796` | 同上 `wide_limit_units` |
| 7 | 判据可复现 | 同输入重跑指纹一致；37 条测试全绿 | `tests/test_diagnose.py` |

## 2. 未证实（不要当成已知）

- F4 的"大角度"阈值：`max_angle_deg` 只是"相对 f1 的世界旋转变化"代理指标，
  正常舞蹈实测到 **179.231°**，60° 阈值明显偏低 → 只能 suspected。
- F5 的 confirmed：没有穿透测量数据（`blender.penetration=null`）。
- S3 的动态证据：可用场景 `feixiao_v2_hsr` 里胸前 6 骨**没有 COPY_ROTATION**，不是现场；
  按 3 轮预算已停止寻找。
- R0：S1/S6 都没有逐帧穿透文件，R0 只有合成 fixture。
- F2 没有独立标签的真实样本（3 个场景实测到未烘焙，但都是别的故障现场）。

## 3. 剩余风险

1. **F4 误报风险高**：任何"有动"的舞蹈都会让裙摆 `max_angle_deg` 超过 60°，
   F4 会稳定输出 suspected。M04 若拿它做门禁，务必先标定，否则全是噪声。
2. **F3 漏报类**：两个回填体之间的焊接关节（布料硬支撑，常是故意的）不算冻结根，
   这类"僵"会漏。宁可漏，不误报。
3. **骨骼改名**：PMX 的冻结根目标骨在 `.blend` 里对不上时，F3 只能到 suspected。
   采集器会写 `missing_evidence: structure.frozen_root_target_bones`。
4. **多模型场景**：`_find_root` 按"骨骼最多"挑主模型；道具（刀/枪）也有 ROOT，
   早期按第一个 ROOT 取会拿到 `刀_arm`（1 根骨）—— 已修，并写进代码注释。
5. **四元数双覆盖**：`rotation_difference().angle` 会给出 357°；已在 `_angle_deg` 归一化，
   第三方若自己算角度要复现这个归一化，否则"几乎没动"会看起来像转了一圈。

## 4. 给 M04 的输入字段清单

M04 只需消费 `diagnosis.json`，不用读本模块推理过程：

```text
primary, secondary[], confidence, status, schema_version, taxonomy_version,
judgment_fingerprint, experiment_id, input_sha256,
diagnostics[]      # 每条 {id, matched, confidence, reason, score, evidence[], evidence_keys[], missing_evidence[]}
missing_evidence[] # 全局待补字段，可直接当采集清单
warnings[], config.thresholds{...}
frame_range{start,end,fps,evidence_mode}, cache{is_baked,frame_start,frame_end}
```

M04 要回填穿透测量时，写到 `evidence.blender.penetration`：

```json
[{"frame": 150, "families": ["下擺"], "bones": ["下擺_11_7"], "max_depth_m": -0.202}]
```

填完重跑判据即可让 F5 从 suspected → confirmed（机制：`_f5` 用 `families`/`bones` 与
`coverage.gaps` 求交），**schema 不用改**。

## 5. 给 M07 的 CLI 与退出码

```powershell
python -m mmdpipe.diagnose --pmx "模型.pmx" --out "diagnosis.json" [--ab A.json B.json]
& "E:\code\Blender\blender-5.2.2-windows-x64\blender.exe" -b -P "mmdpipe\diagnose_blender.py" -- `
    --blend "场景.blend" --out "diagnosis.json" --frames 60 [--pmx "模型.pmx"]
```

| 退出码 | 含义 | 插件里该怎么处理 |
|---:|---|---|
| 0 | JSON 已写盘 | 读 `primary`/`confidence` 渲染四区面板 |
| 1 | （仅 `--fail-on-confirmed`）已确认故障 | 面板标红，列出 `evidence_keys` |
| 2 | 参数错误 | 提示用户检查路径 |
| 3 | 输入不可读 / PMX 解析失败 | 不显示半成品结果 |
| 4 | （仅 Blender）`status=partial` | 面板显示"证据不完整"，列出 `missing_evidence` |

面板要展示的四件事：`primary`、`confidence`、`reason`、`missing_evidence`。
**不要把 `status=ok` 当"没问题"** —— 工具跑成功不等于归因成功。

## 6. 建议下一模块先读的接口

1. `mmdpipe/diagnose.py` 的 `build_report()` / `judge()`（判定入口，纯函数）；
2. `reports/subai/M03/schema.md` §2–§4（判据形状、口径、阈值来源）；
3. `reports/subai/M03/known_limits.md`（覆盖缺口，避免把 suspected 当结论）。
