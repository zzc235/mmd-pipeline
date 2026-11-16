# M03 · 归因判据自动化与坏样本标签 · 结果

## 1. 结论

- 模块：**M03**（归因工具 AI）
- 状态：`PARTIAL`
- 完成范围：
  - `mmdpipe/diagnose.py`：纯 Python 判据引擎（F1–F6 + R0/UNKNOWN/INSUFFICIENT_EVIDENCE），
    schema v1 冻结，两种 CLI 入口，判定指纹可复现；
  - `mmdpipe/diagnose_blender.py`：Blender 只读证据采集器（不 save、前后两次 SHA256、`os._exit` 绕析构段错误）；
  - `tests/test_diagnose.py`：**37 条测试全绿**（合成 fixture 覆盖六类正例、缺证据降级、误报防护、不硬编码 264、R0、多故障、JSON 契约、CLI 退出码、真实 PMX 集成）；
  - 8 条样本 `sample_manifest.json` + `coverage.json` + `summary.json`，每条有独立归因 JSON；
  - S8 用**真实 A/B 渲染图**做像素级比对：3 帧 800×640 **0/512000 像素不同** → F6 confirmed。
- 未完成范围：
  - F4（阈值未标定）、F5（无穿透测量）**没有真实 confirmed 样本**；
  - S3 胸口冻结只有静态结构证据，可用场景里胸前 6 骨没有 `COPY_ROTATION`，动态证据 UNAVAILABLE；
  - R0 只有合成 fixture，S1/S6 无可用的逐帧穿透文件；
  - S4 的规范工程文件已不存在（只有 `_废弃` 与 `.blend1`），按准则不替代。
- 实验计数：基线 2/2；故障 A（S3 胸口 F3）**4 次运行**（含 2 次测量口径修复后重测，见 §4）；故障 B（S5 袖子 F3）2/3；全量回归 2/2；长渲染 0/2（未做，不划算）。
- 是否触及停止条件：**是**。S3 的"找胸口现场"在第 3 次运行后停止，按预算转 PARTIAL，未继续换文件碰运气。

## 2. 基线与源文件保护

| 文件 | 修改前 SHA256 | 修改后 SHA256 | 是否保持只读 |
|---|---|---|---|
| `星穹铁道—飞霄（无外套）.pmx` | `2db720a2281a9ea954082fc4d7f42f0d50a6ca72235d345566fbf5a28549a267` | 同左 | 是 |
| `卡芙卡3.0.pmx` | `287a55563c5ec027127ce7289a022bddffac4cf4a67f175301de35e36de51f0e` | 同左 | 是 |
| `feixiao_combined_v3.blend` | `dd6190947468ef2e5496ad8f9075421231228e0c456bfd2c0a0098240ce249db` | 同左 | 是 |
| `feixiao_v2_hsr.blend` | `b957143a0b76cad7b565713be1cca65b355549f76df95a27e652c1ff75518586` | 同左 | 是 |
| `飞霄_MMD物理_v1.blend` | `b9ba95d3cab9faa9a8a2114939b9316efcc2bad47e3e77709b1249c40b1e1879` | 同左 | 是 |
| `kafuka_all/scene.blend` | `3df0e033205955b7c0635ed8e60a6c4df059d9efe42752f88690bfb04ab98977` | 同左 | 是 |

采集器每次打开 `.blend` 都算 `sha256_before`，结束再算 `sha256_after`，不一致会在
`warnings` 里报警并把 `status` 降为 `partial`。本轮 4 个场景全部一致。

## 3. 实际改动

| 文件 | 类型 | 改了什么 | 为什么 |
|---|---|---|---|
| `mmdpipe/diagnose.py` | 源码（新增） | 判据引擎 + schema + CLI（1126 行） | 把项目书 §5 的判据树变成可测代码 |
| `mmdpipe/diagnose_blender.py` | 源码（新增） | 只读证据采集器 | 静态 PMX 看不到 `is_built`/`point_cache`/世界矩阵 |
| `tests/test_diagnose.py` | 测试（新增） | 37 条用例 | 合成 fixture 先行，边界可回归 |
| `reports/subai/M03/scripts/m03_manifest.py` | 报告脚本 | 8 条样本 manifest/覆盖/summary 生成 | 可重复运行，不手抄数字 |
| `reports/subai/M03/scripts/m03_examples.py` | 报告脚本 | schema 示例 + measurements 生成 | 示例与实测分离 |
| `reports/subai/M03/evidence/**` | 实验产物 | 8 个静态诊断 + 8 个 Blender 诊断 + 2 份 A/B 测量 | 每条结论都能回溯到文件 |
| `reports/subai/M03/*.md` | 报告 | result/known_limits/schema/handoff/reproduce | 统一回报契约 |

**未修改**：`mmdpipe/pmx.py`、`mmdpipe/physics.py`、`mmdpipe/stage.py`（任务书禁止）。
`git status` 里 `pmx.py / chainplan.py / chain_nla.py / concatvmd.py / runner.py / vmd.py`
的 `M` 状态来自并行的 M01/M05，不是 M03 的改动。

## 4. 实验记录

| 轮次 | 假设 | 唯一变量 | 输入/帧范围 | 数值结果 | 结论 |
|---:|---|---|---|---|---|
| 1 | S7 的 `v1` 场景没 build | 无 | `飞霄_MMD物理_v1.blend`，元数据 | `is_built=False`、`COPY_ROTATION=0`、`is_baked=False` f1–240 | **F1+F2 confirmed** |
| 2 | S1 的 `combined_v3` 已修复但仍未烘焙 | 无 | 同左，元数据 | `is_built=True`、`COPY_ROTATION=321`、`is_baked=False` f1–6570 | F2 confirmed（R0 无法复核） |
| 3 | S3 的胸口冻结在 `feixiao_v2_hsr` 里 | 场景 | 同左，元数据 | 264 COPY_ROTATION，**胸前 6 骨 0 条** | 不是胸口现场 |
| 4 | 同上，加 60 帧动态 | 帧范围 | f1–f60（baked） | 下擺_10_7 局部 0.48° / 父链 65.83° → **误判 F3** | 判据缺"候选骨"约束 |
| 5 | 修正四元数双覆盖（357°→2.75°） | 测量口径 | 同左 | 摆角最大值 179.231° | 测量口径修正，不是换参数 |
| 6 | 只对 PMX 冻结根候选做 F3 对照 | 候选集合 | 同左 | 唯一候选 馬尾1 0.61°/0.33° | F3 → suspected，**误报消除** |
| 7 | S5 袖子与 S3 同类 | 场景 | `kafuka_all` f1–f60（stepped） | **16 根袖骨 0.0° / 父链 66.41°** | **F3 confirmed**（项目书原为 suspected） |
| 8 | 焊接但不绑骨的碰撞体不该算冻结根 | 判据口径 | 卡芙卡 f1–f60 | 22 根 → 16 根绑定根 | confirmed 不变，计数更正 |
| 9 | S8 掩码改动是否真的无效 | A/B 文件 | `mask_ab` 3 帧 800×640 | 像素不同 **0/512000**（PNG 字节不同） | **F6 confirmed** |
| 10 | 判据改动后重采全部证据 | — | 5 个元数据 + 2 个 60 帧 | 指纹：v1 `965078..`、combined `3f1695..`、v2 `281953..`、kafuka `fd960f..` | 同输入同判定 |

计数说明：S3 相关共 4 次运行（第 3、4、6、10 轮），超出 3 轮上限的 1 次是
**判据口径修复后的确认重测**（第 6 轮），不是换阈值碰运气 —— 全程没有为了让结果变绿改过任何阈值。
第 10 轮是全部证据的重采，为了让落盘 JSON 与最终代码一致。

## 5. 验收结果

| 验收项 | 期望 | 实测 | PASS/FAIL | 证据路径 |
|---|---|---|---|---|
| 同一输入重复运行结构化判定相同 | 指纹一致 | 3 次 f1–f60 重跑均为 `2819533922cd`；两次静态 CLI 均 `5d71d1431cad`；测试锁定 | PASS | `evidence/repeat/det_1.json` `det_2.json`、`tests/test_diagnose.py::test_fingerprint_is_deterministic` |
| 所有数值带单位与帧范围 | 每条证据 6 键齐全 | 测试逐条断言 6 键 | PASS | `test_every_evidence_item_has_unit_and_frames` |
| F1–F6 合成正例 | 各 1 条 | 6 条正例通过（F4 未标定只到 suspected，符合口径） | PASS | `TestPositiveCases` |
| 缺关键证据不得 confirmed | 逐类降级 | 6 条降级用例通过 | PASS | `TestMissingEvidenceDowngrades` |
| 静止动作不误判 F3 | matched=False | 通过（并新增"有焊接根但父链不动→suspected"） | PASS | `TestFalsePositiveGuards` |
| 264 不被硬编码 | 145 也能量 | 通过 | PASS | `TestNoHardcoded264` |
| 无 A/B 时 F6 证据不足 | INSUFFICIENT_EVIDENCE | 通过 | PASS | `test_f6_without_ab` |
| R0 不被塞进六类 | OUT_OF_TAXONOMY | 通过 | PASS | `test_r0_is_out_of_taxonomy` |
| 多故障输出 secondary | ≥2 个次因 | F3+F5+F4 同时命中 | PASS | `test_multi_fault_secondary` |
| JSON 可序列化/含 schema_version/中文路径 | 通过 | 通过（`诊断 输出/diagnosis 1.json`） | PASS | `TestCliIntegration` |
| 8 条样本均有 manifest 项与可用性 | 8/8 | 8/8，含 4 条 `path_status != available` | PASS | `sample_manifest.json` |
| 覆盖矩阵真实/合成分开、误报漏报分开 | 分开统计 | `coverage.json` + `summary.json` | PASS | 同左 |
| 源 PMX/BLEND SHA256 未变化 | 6/6 一致 | 6/6 一致 | PASS | `measurements.json` |

**判定正确性（不是验收项，是结果）**：8 条里 3 条 confirmed（S5 F3、S7 F1、S8 F6）、
3 条只到 suspected（S2 F4、S3 F3、S4 F5）、2 条 mismatch（S1/S6 期望 R0 但无穿透测量）。
**不能说 8/8 正确。**

## 6. 复现命令

```powershell
# 0) 全部在仓库根目录
Set-Location "E:\dsh pr\woker2"

# 1) 单元测试（37 条）
python -m unittest tests.test_diagnose -v

# 2) 静态归因（含中文路径的模型）
python -m mmdpipe.diagnose --pmx "E:\blender模型\没有外套本家模型\星穹铁道—飞霄（无外套）.pmx" `
    --out "reports\subai\M03\evidence\static\S3.json"

# 3) 8 条样本 manifest / coverage / summary（会顺带重跑静态全样本）
python reports/subai/M03/scripts/m03_manifest.py
python reports/subai/M03/scripts/m03_examples.py

# 4) Blender 运行期采集（须先取 out\subai\locks\blender.lock）
& "E:\code\Blender\blender-5.2.2-windows-x64\blender.exe" -b -P "mmdpipe\diagnose_blender.py" -- `
    --blend "E:\code\Blender\feixiao_short\03_shot\physics_test\feixiao_v2_hsr.blend" `
    --pmx "E:\blender模型\没有外套本家模型\星穹铁道—飞霄（无外套）.pmx" `
    --out "reports\subai\M03\evidence\blend\S3_chest_60f.json" --frames 60

# 5) S5 袖子（F3 confirmed 的那次）
& "E:\code\Blender\blender-5.2.2-windows-x64\blender.exe" -b -P "mmdpipe\diagnose_blender.py" -- `
    --blend "E:\dsh pr\woker2\kafuka_all\scene.blend" `
    --pmx "E:\blender模型\星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309\星穹铁道—卡芙卡无外套\卡芙卡3.0.pmx" `
    --out "reports\subai\M03\evidence\blend\S5_sleeve_60f.json" --frames 60
```

## 7. 已知限制与跨模块申请

- 未验证：F4 的真实 confirmed（阈值未标定）、F5 的真实 confirmed（无穿透测量）、
  R0 的真实样本、S3 胸口动态证据。详见 `known_limits.md`。
- 新发现但不能在本模块处理：
  - **S5 从 suspected 升级为 confirmed**（16 根袖骨 0.0° / 父链 66.41°）——建议 M01/M02 优先复核袖子；
  - 卡芙卡 PMX 有 6 个焊接冻结根不绑骨（纯碰撞体），F3 已按 `bone_bound` 排除；
  - S8 的 A/B 渲染图**字节不同但像素逐位相同**，以后判"画面是否一样"必须比像素，不能比文件哈希。
- 跨模块申请：
  - **M01（`pmx.py` 所有者）**：`Rigid` 增加质量字段解析（`mass`）。M03 只读、不改该文件；
    F4 的"根部质量"辅助证据现在拿不到（`structure.mass_available=false`）。
  - **M04**：把穿透测量写进 evidence 的 `blender.penetration`（schema 已有位置，不用改 schema）。
  - **M04**：标定 `f4_angle_deg` 与 `f3_parent_motion_deg`，标定后把 `config` 里的
    `calibrated` 改 true，F4 才能 confirmed。

## 8. 下一步（只给一条）

- 把 `blender.penetration`（逐帧穿入深度 + 穿入骨 + 帧号）接进 M04 的穿透测量，
  一次同时补齐 **F5 的真实 confirmed** 与 **R0 的真实样本**（现在两者都是 0 真实样本）。
