# M05 交接（≤100 行）

状态：`PARTIAL`。三段丢帧 **PASS**；NLA **帧映射层 PASS（数据层）**；「悬空坐姿」视觉 **BLOCKED**（无坏样本）。
Blender 资源锁已释放（21:31 取、21:38 放，owner.txt 核对过），期间无其他 Blender 进程。

## 已证实

1. **244 的根因**：`vmd.concat` 自动 offsets 不累加偏移。三段 91/91/151 gap=2 → offsets `[0,93,93]`，
   第 3 段压在第 2 段上，337 → 244（`91+2+151`）。记录 18196 一条没少，只有帧账本能发现。
   修复后 `[0,93,186]`、337 帧、无重叠、两次输出 sha256 相同。
2. **NLA 坏姿态的层是「交叉淡化的帧映射」**（`chain_nla` 的 `extend_upper_strip`）：
   旧代码把 B 条带 `[448,847]` 映射到 action `[448,827]`，B 被压缩 5.5%、整体提前约 20 帧，
   尾部 20 帧不被采样。实测 f846 与未淡化差 **1.00696 m**。
3. 修法：四个帧值显式写成恒等映射（`frame_start/end` 与 `action_frame_start/end` 都延伸 shift），
   修后除首帧 f1=0.0130 m 外全部 ≤0.00007 m；**导出 VMD 与 splice 在 380/827 个共有帧上差 0.0000**。
4. **多段拼接的收尾崩溃**：`runner.py` 把 layout 的 `paths`(dict) 复用作动作列表，跑完在
   `paths["final"]` 处 TypeError——渲了 12 帧却不落 final。改名 `seg_paths` 后 `state.final` 正常。
   这个坑所有 `--motions` 用户都会踩，M07/M08 的 E2E 必须覆盖。
5. NLA `N>2` 现在写文件前 BLOCK（`chainplan.nla_segments_check`）。

## 未证实 / 已知限制

- **「悬空坐姿」没有原始坏样本**：本轮证明并修掉了帧映射缺陷，但没做同机位视觉复现，
  不能写「悬空坐姿已修」。
- 导出再导入 Blender 的世界姿态未测（只比到「导出文件 vs splice 文件」）。
- f1 处 bake 与 bake 前差 12.96 mm（只首帧），未查。
- `blend > gap`（淡化比空档长）未测：此时 B 会提前覆盖 A 尾部，可能反而不对。
- 12 帧探针预算 2/2 已用尽（1 次环境失败 + 1 次成功但收尾崩溃）；后续验证用 2 帧跑做回归。

## 剩余风险

- `runner` 的守恒断言已在三次 Blender 跑里验证过字段，但**没有自动化 bpy 测试**，回归靠人跑。
- `vmd.concat` 的 `total_frames` 用 spans 末帧 +1；若手工补键没同步 `bone_last_frame`，值会偏。
- `chainplan.plan` 的 `pose_diff` 仍指第一个交接对，N 交接要看 `junctions`。

## 给 M07 的接口说明

- `chainplan.plan()`：新增 `junctions`（每相邻对一条，含 pair/timeline/over_threshold/max_angle_deg/pose_diff）；
  旧 `pose_diff` 保持首个交接对语义，两段时等价。`segments[i]` 新增 `expected_count`、`gap_after`。
- `concat_vmd(..., frames=N)`：输出 `explicit_truncated_frames` / `unexplained_gap_frames`。
- `nla_segments_check(n)`：N>2 必 BLOCK；`concat_via_nla` 仍是两段接口，面板不要允许「3 段 + NLA」静默组合。
- `chain_nla.extend_upper_strip(strip, a_last)`：淡化延伸的唯一入口，别再在别处手写 shift。

## 给 M08 的验收

```powershell
python -m mmdpipe.chainplan out/subai/M05/fixtures/seg1_91.vmd out/subai/M05/fixtures/seg2_91.vmd out/subai/M05/fixtures/seg3_151.vmd --gap 2
# 预期：合计 337 帧；交接对 2 个

powershell -ExecutionPolicy Bypass -File out\subai\M05\probe2_tail.ps1
# 预期：pipeline_state.json  ok=true, final=true
#       S3_chain.metrics: expected=393 chain=393 requested=2 rendered=2
#       frame_conservation="truncated", explicit_truncated_frames=391
# 注意：必须用普通 blender -b；--factory-startup 会禁扩展仓库，mmd_tools 加载失败
```

## 证据文件

- `reports/subai/M05/frame_ledger_{baseline,final}.json`
- `reports/subai/M05/nla_stage_probe.json`（run1/2/4/5 + 导出对照）
- `reports/subai/M05/nla_stage_probe_run{1,2,4,5}.json`
- `out/subai/M05/{chain_baseline_overlap,chain_fixed_337,nla_export_run1,splice_ref_gap20}.vmd`
- `out/subai/M05/probe12b|probe2_tail/pipeline_state.json`
