# M01 · F3 冻结类修复：飞霄胸口 S3 + 卡芙卡袖子 S5（result）

## 1. 结论

- 模块：M01（物理修复 AI-A）
- 状态：**PARTIAL**（S3 = PASS；S5 = 技术验证完成但**没有拿到可用修复**，见 §5.2）
- 完成范围：
  - S3 单变量修复闭环：飞霄 24–29 号胸部刚体 `mode 2→0`，副本 6 字节差异，重建后胸口回到纯跟随，
    与「关物理」静态对照逐帧**完全相同（0.00000 m）**，并用第二个动作独立确认。
  - 可复用能力：`mmdpipe/pmx.py` 的 `patch_save(..., rigid_mode=...)`，解析时记录每个刚体 mode 的
    字节偏移、写前回读旧值、只改 1 字节、拒绝覆盖源文件；`tests/test_pmx_patch.py` 12 项测试。
  - S5 结构核对 + 静态策略对照（基线 vs `physics-policy strict`）跑完并量化。
- 未完成范围：
  - S5 没有可用修复。静态策略把「抖动」换成了「袖子被拉成刚性长条」，视觉不可接受（§5.2）。
  - 未验证 S3 副本对其它物理单元（裙/发/道具）的连锁影响，只验证了「非目标刚体 mode 未变」与
    「非目标骨的物理约束数量未变」。
  - 未做 GUI 人工验收（本模块全程 `blender -b`）。
- 实验计数：基线 1/2；S3 故障 3/3；S5 故障 2/3；全量回归 1/2；长渲染 0/2（只跑代表帧静态图）
- 是否触及停止条件：**是**。S5 在第 2 轮就出现「mode 分布与项目书假设不符 + 唯一既有策略视觉失效」，
  按任务书 §4「只验证已有静态策略，不另试多种 PMX 改法」停止，不再换参数。

## 2. 基线与源文件保护

| 文件 | 修改前 SHA256 | 修改后 SHA256 | 是否保持只读 |
|---|---|---|---|
| 飞霄（无外套）.pmx（3,316,950 B） | `2db720a2281a9ea954082fc4d7f42f0d50a6ca72235d345566fbf5a28549a267` | 同左 | 是 |
| 卡芙卡3.0.pmx（2,695,060 B） | `287a55563c5ec027127ce7289a022bddffac4cf4a67f175301de35e36de51f0e` | 同左 | 是 |
| 副本 `out/subai/M01/飞霄_s3_mode0.pmx`（新文件） | — | `c59460752835501ead6123b2d5f195bebc1356df29a8871f498ca1f12cf2f3da` | 长度与源一致 3,316,950 B，**仅 6 字节不同** |

> **勘误（2026-11-16，模块负责1）**：`joint_limit_layout.spring_rot` 初版写 `+78`，**实测为 `+84`**。
> 关节尾部共 24 float = 96 B：position +0 / rot +12 / lpm +24 / lpx +36 / lrm +48 / lrx +60 / sp +72 / **sr +84**。
> `+78` 落在 sp（平移弹簧）第 3 个 float 内部：写进去后 PMX 照样解析通过：`spring_rot` 仍读 0，sp 第 3 个 float 变成 1e-41 量级的反规格化数
> （飞霄 389 关节弹簧全为 0），语义字段完全看不出异常，只有逐字节比能抓——这类坏文件会在某天
> 有人真碰弹簧时才炸。实测证据：在 `o+84` 写 `(1,2,3)` 后重解析 `spring_max=3.0`、字节差异 5 个且
> 全部落在 `o+86…o+95`；在 `o+78` 写 `7.0` 后 `sp=(0.0,0.0,2.327e-41)`。
> 已同步改：`patch_manifest.json`、`measurements.json`、`handoff.md`、
> 共同工作区 `M02_F4下摆与F6碰撞映射.md` L163。**未改 `pmx.py`**（代码本就没有限位补丁能力）。

## 3. 实际改动

| 文件 | 类型 | 改了什么 | 为什么 |
|---|---|---|---|
| `mmdpipe/pmx.py` | 源码 | `PMXModel.rigid_mode_offsets`；`parse()` 在 `r.u8()` **之前**记下 mode 字节偏移；`patch_save()` 新增 `rigid_mode={index: 0/1/2}`，写前用旧值校验偏移未过期，非法 mode / 越界索引 / 覆盖源文件一律抛 `PMXError` | S3 需要「只改 mode、其它字节不动」的副本补丁；偏移靠解析器实测，不按 PMX 规范推断 |
| `tests/test_pmx_patch.py` | 测试 | 新增 12 项：6 个 mode 2→0、非目标 mode 不变、长度不变、diff 位置数 = 目标 mode 字段数、非 diff 区一致、截空补丁 = 逐字节相同、`rigid_pos` 回归、拒绝覆盖源文件、非法 mode（3/-1/255/1.0/"0"/True）、非法索引、偏移过期、`mode_off - pos_off == 44` 交叉校验；真实飞霄模型的 2 项 | 判据必须落在字节上；`mode` 偏移写错会静默改坏 mass/friction 字段 |
| `reports/subai/M01/scripts/*.py` | 实验脚本 | `m01_baseline.py`、`m01_env_probe.py`、`m01_make_patch.py`、`m01_chest_probe.py`、`m01_compare.py`、`m01_sleeve_probe.py`、`m01_shots.py`、`m01_sheet.py`、`m01_collect.py` | 全部可重跑；数字不手抄 |
| `out/subai/M01/**`、`reports/subai/M01/**` | 实验产物/报告 | 新建 | 本模块输出根 |
| `C:\Users\zzc\Desktop\ai用\dsh use\gongtonggzq\M01_F3冻结类修复_胸口与袖子.md`
`…\M02_F4下摆与F6碰撞映射.md` | 报告（共同工作区） | 末尾**只追加**不修改正文：M01 文件加「补充 · M01 执行记录」（15 步时间线 / 逐 hunk 改动 / 数值 / 文件清单 / 合规偏差 / 下游事实），M02 文件加「补充 · M01 → M02 交接」（补丁接口、关节字节布局、ROI 判据、环境坑） | 总控要求可追溯：每条改动都能按路径+命令+数值复核；追加脚本 `reports/subai/M01/scripts/m01_append_shared_doc.py` 幂等，可 `--check` / `--replace` |

未改动：`stage.py`、`physics.py`、`runner.py`、插件目录、任何 `.blend`、任何源 PMX/VMD。

> 共同工作区的补充落在：`C:\Users\zzc\Desktop\ai用\dsh use\gongtonggzq\`
> （`M01_F3冻结类修复_胸口与袖子.md` 158→307 行、`M02_F4下摆与F6碰撞映射.md` 131→192 行，均只追加）。
> `00_总控索引与执行顺序.md`、`09_子AI统一回报模板.md`、M03–M08 任务书未改动。

## 4. 实验记录

### 4.1 阶段 A：只读基线（结论与项目书一致，无数据漂移）

- 飞霄：312 刚体 / 389 关节 / 420 骨，mode 分布 `{0: 48, 2: 264}`。
- 目标 24–29 = `右胸 / 右胸１ / 右胸２ / 左胸 / 左胸１ / 左胸２`，**全部 mode2**，与刚体同名骨
  （Blender 侧 `rename_bones=True` 后变成 `胸.R / 胸１.R / 胸２.R / 胸.L / 胸１.L / 胸２.L`）。
- 与这 6 个刚体相连的 6 个关节（原始字节，非推测）：

| joint | a→b | 旋转限位 rot_min → rot_max（rad） | 平移限位 / 弹簧 | 判定 |
|---:|---|---|---|---|
| 0 | 6→24 | [0,0,0] → [0,0,0] | 全 0 / 全 0 | **完全焊死（根关节）** |
| 1 | 24→25 | [0,-0.1745,0] → [0.5236,0.0873,0] | 全 0 / 全 0 | 有限位、**无弹簧** |
| 2 | 25→26 | [-0.4363,-0.3491,-0.2618] → [0.6109,0.3491,0.2618] | 全 0 / 全 0 | 有限位、**无弹簧** |
| 3 | 6→27 | [0,-0,-0] → [0,-0,-0] | 全 0 / 全 0 | **完全焊死（根关节）** |
| 4 | 27→28 | [0,-0.0873,0] → [0.5236,0.1745,0] | 全 0 / 全 0 | 有限位、**无弹簧** |
| 5 | 28→29 | [-0.4363,-0.3491,-0.2618] → [0.6109,0.3491,0.2618] | 全 0 / 全 0 | 有限位、**无弹簧** |

  → 左右胸链的**根关节把刚体焊在 6 号刚体上**，符合「硬约束冻结」而非「动力学过冲」。
- 判定器（`physics.classify`）：`{physics: 261, welded: 8, welded_collider: 0, collider: 43, free: 0}`。
- 卡芙卡：145 刚体 / 182 关节 / 246 骨，mode 分布 `{0: 24, 1: 119, 2: 2}`。
- 卡芙卡袖筒：2 个单元，各 **25 刚体 / 48 关节 / 环 24 / 焊占比 50% / modes `{0:1, 1:24}`**，
  **单元内无 mode2**（全模型的 2 个 mode2 不在袖筒里）→ S3 的修法**不适用**，与任务书假设一致。
- `strict` 策略骨 = `force-static xk_` 匹配骨 = **同一组 48 根**（右侧袖筒骨名是 `zxk__*`，被 `xk_` 子串一并命中）。

### 4.2 阶段 B：补丁能力 + 测试

- 补丁落点（解析器实测字节偏移，非按规范推算）：3236857 / 3236934 / 3237011 / 3237086 / 3237163 / 3237240。
- `python -m unittest tests.test_pmx_patch tests.test_physics -v` → 16 项全绿。
- 全量回归 `tests.test_pmx_patch test_physics test_params test_vmd test_layout test_align test_statefile`
  → **60 项全绿，1 轮**。

### 4.3 阶段 C：S3 单变量修复（clip1 = PERF_Wushu_VoidStep，1–150 帧，连续步进）

环境事实（先确认再动手）：mmd_tools 导入 `types` **不含 PHYSICS 时 `Model.build()` 只建出 0 个刚体**；
含 PHYSICS 时导入后 `is_built=False`、0 条约束，`Model.build()` 才把 `is_built` 置真并建出 337 条约束
（其中 COPY_ROTATION 264 条）。胸口 6 根骨各挂 1 条 `COPY_ROTATION`，目标是对应刚体的
`mmd_bonetrack` 空物体（`mmd_type=TRACK_TARGET`），**不是**直接指向刚体的常规约束。

| 变体 | 物理 | is_built | 刚体 | 胸口 COPY_* | 约束直方图 |
|---|---|---:|---:|---:|---|
| baseline（原 PMX，mode2） | 开 | 是 | 312 | **6** | COPY_ROTATION **264**，其余同上 |
| static（关物理 = 纯跟随） | 关 | 否 | 0 | 0 | 无 COPY_ROTATION |
| mode0（补丁，mode 2→0） | 开 | 是 | 312 | **0** | COPY_ROTATION **258**，其余完全一致 |

- ROI：胸口 71 顶点（权重主导骨 ∈ 上述 6 根）；髋 1250 顶点（`下半身`/`腰`）；躯干参考 1309 顶点（`上半身2`）。
- 帧 1/15/30/45/60，全部**逐帧 `frame_set` 连续步进**（不跳帧），对比图同机位由静置胸骨推出。

| 帧 | baseline vs static（均值/最大，m） | mode0 vs static（均值/最大） | 胸 extent_x baseline → mode0 | 胸/髋 baseline → mode0 |
|---:|---|---|---|---|
| 1 | 0.22746 / 0.29213 | **0.00000 / 0.00000** | 0.11099 → 0.16981 | 0.4333 → 0.6629 |
| 15 | 0.22803 / 0.29307 | 0.00000 / 0.00000 | 0.10501 → 0.17423 | 0.4034 → 0.6693 |
| 30 | 0.22674 / 0.29135 | 0.00000 / 0.00000 | 0.10988 → 0.18234 | 0.4296 → 0.7129 |
| 45 | 0.22597 / 0.29177 | 0.00000 / 0.00000 | 0.13415 → 0.18405 | 0.5298 → 0.7268 |
| 60 | 0.22809 / 0.29358 | 0.00000 / 0.00000 | 0.13806 → 0.18409 | 0.5286 → 0.7049 |

→ baseline 的胸口被压到静态尺寸的 **60–75%**（同帧同 ROI），且胸/髋比例从 ~0.73 掉到 ~0.43；
mode0 与 static **每一位都相同**（差 0.00000，不是"接近"）。物理确实在跑：同一批刚体首末帧世界位移
0.60–0.68 m（baseline）/ 0.64–0.71 m（mode0），不是"整体没动所以看起来一样"。

### 4.4 阶段 D：S3 独立确认（clip2 = EMO_Sway，1–150 帧，另一条动作）

补丁字节不变，只换动作，重跑三个变体（4 个采样帧）：

| 帧 | baseline vs static | mode0 vs static | 胸 extent_x baseline → mode0 |
|---:|---|---|---|
| 1 | 0.23289 / 0.29900 | **0.00000 / 0.00000** | 0.10828 → 0.18528 |
| 20 | 0.23256 / 0.29864 | 0.00000 / 0.00000 | 0.10774 → 0.18639 |
| 40 | 0.23292 / 0.29990 | 0.00000 / 0.00000 | 0.11627 → 0.18593 |
| 60 | 0.23283 / 0.29996 | 0.00000 / 0.00000 | 0.11467 → 0.18630 |

→ 两条动作结论一致（baseline 偏离 ~0.23 m，mode0 与 static 完全重合），不是单段动作的偶然。

### 4.5 阶段 E：S5 卡芙卡袖筒（PERF_Wushu，连续步进 1–150 帧，逐帧统计）

| 指标 | base（policy=off） | static（policy=strict） |
|---|---|---|
| 静音约束数 / 仍生效 | 0 | **48**（48 根骨各 1 条）/ **0** |
| 袖筒骨逐帧最大转角（全局） | **343.35°**（f31，`xk_0_0`） | **12.61°**（f31，`xk_0_4`） |
| >45°/帧 次数（48 骨 × 150 帧） | **35**（集中在 f29–f33，单帧最多 13 根） | **0** |
| 每帧最大转角的均值 | 26.81° | 3.42° |
| 非袖子物理骨同期最大值（对照） | 359.26° | **359.26°（逐帧完全一致）** |
| 袖筒 ROI（397 顶点）包围盒 f45 | 0.126 × 0.308 × 0.340 m | **1.100 × 0.137 × 0.629 m** |

→ 静态策略**只影响袖筒**（非袖子骨的逐帧指标一位不差），确实消掉了抖动；但袖筒被拉成刚性长条，
f45 包围盒从 0.13 m 宽变成 1.10 m 宽。原因可解释：48 根袖筒骨父链挂在 `左ひじ/右ひじ` 上
（`左ひじ` 下 8 根、`右ひじ` 下 8 根，其余沿 `xk_*` 逐级），静音后就只剩骨架的静止局部旋转，
袖子回到 A-Pose 的直筒形状，不再随手臂折叠。

## 5. 验收结果

### 5.1 S3（PASS）

| 验收项 | 期望 | 实测 | PASS/FAIL | 证据路径 |
|---|---|---|---|---|
| 源 PMX SHA256 前后一致 | 一致 | 一致 | PASS | `measurements.json:sources_before/after` |
| 副本只含预期 mode 字节差异 | 6 字节 | diff 恰好 6 处，位于 6 个 mode 偏移 | PASS | `out/subai/M01/patch_manifest.json` |
| 6 个目标 mode=0、其他刚体不变、可重新解析 | 是 | 是（312 刚体中其余 mode 全等；`tail_error=null`） | PASS | `tests/test_pmx_patch.py`、`patch_manifest.json` |
| build 后目标骨物理回填消失 | 6 → 0 | 6 → 0；COPY_ROTATION 264 → 258，其它约束不变 | PASS | `out/subai/M01/probe/probe_mode0.json:after_build` |
| 非目标区域未批量变化 | 无批量变化 | 仅少 6 条 COPY_ROTATION；目标刚体变 `kinematic=true`（type 0） | PASS | 同上 |
| 动态证据来自连续步进/烘焙 | 是 | 逐帧 `frame_set(1..f)`，未跳帧 | PASS | `m01_chest_probe.py`、`probe_*.json:frames` |
| 与静态对照差异有数值 | 有 | baseline 偏离 0.227 m（clip1）/ 0.233 m（clip2）；mode0 = 0.00000 | PASS | `probe/comparison.md`、`probe2/comparison.md` |
| 独立确认结论一致 | 一致 | 两条动作同结论 | PASS | `probe2/comparison.md` |
| 同帧同机位对比图 | ≥1 张 | 6 张 + 拼版 1 张；视觉终审**待用户确认** | PASS（视觉项另列） | `out/subai/M01/compare_chest.png` |

### 5.2 S5（PARTIAL，判据分开写）

| 验收项 | 期望 | 实测 | PASS/FAIL | 证据路径 |
|---|---|---|---|---|
| 先报告真实 mode/关节结构，不套错 S3 修法 | 有 | 2 单元 × 25 体/48 关节/环 24/焊 50%；单元内 **无 mode2**；未生成 mode0 副本 | PASS | `baseline.json:kafka`、`measurements.json:s5` |
| 静态策略可重复 | 是 | 同一命令两次数值一致（48/48 静音，still 0） | PASS | `out/subai/M01/sleeve/sleeve_static.json` |
| 只影响目标袖子单元 | 是 | 非袖子物理骨逐帧最大值两变体完全相同（359.258°） | PASS | 同上 |
| 源文件未变 | 是 | SHA256 未变 | PASS | `measurements.json` |
| 有基线/静态对照数值与代表帧 | 是 | 有（上表 + 图） | PASS | `out/subai/M01/compare_sleeve.png` |
| 袖子静态结果可用 | 视觉可接受 | **否**：袖子变刚性长条，f45 包围盒 1.10×0.63 m | **FAIL** | `compare_sleeve.png` |

→ 技术项全过，产物项不过。按任务书「最终视觉是否满意留给用户确认」，这一项不能由我代替用户拍板；
但「包围盒从 0.13 m 变 1.10 m」已经是可量化的异常，故不写 PASS，写 **PARTIAL + FAIL 项**。

## 6. 复现命令

```powershell
Set-Location "E:\dsh pr\woker2"
$B = "E:\code\Blender\blender-5.2.2-windows-x64\blender.exe"
$V1 = "E:\flowhmr-test\library\vmd\PERF_Wushu_VoidStep_Once_F.vmd"
$V2 = "E:\flowhmr-test\library\vmd\EMO_Sway_Normal_Once_F.vmd"
$FX = "E:\blender模型\没有外套本家模型\星穹铁道—飞霄（无外套）.pmx"
$KF = "E:\blender模型\星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309\星穹铁道—卡芙卡无外套\卡芙卡3.0.pmx"
$OUT = "E:\dsh pr\woker2\out\subai\M01"

# 阶段 A 基线 + 阶段 B 测试
python reports\subai\M01\scripts\m01_baseline.py
python -m unittest tests.test_pmx_patch tests.test_physics -v

# 阶段 C/D：生成副本 + 三变体对照（每个 Blender 任务串行，别并发）
python reports\subai\M01\scripts\m01_make_patch.py
& $B -b --factory-startup -P reports\subai\M01\scripts\m01_chest_probe.py -- $FX $V1 baseline "$OUT\probe" --physics 1 --frames 1,15,30,45,60
& $B -b --factory-startup -P reports\subai\M01\scripts\m01_chest_probe.py -- $FX $V1 static   "$OUT\probe" --physics 0 --frames 1,15,30,45,60
& $B -b --factory-startup -P reports\subai\M01\scripts\m01_chest_probe.py -- "$OUT\飞霄_s3_mode0.pmx" $V1 mode0 "$OUT\probe" --physics 1 --frames 1,15,30,45,60
python reports\subai\M01\scripts\m01_compare.py "$OUT\probe"

# 阶段 E：S5
& $B -b --factory-startup -P reports\subai\M01\scripts\m01_sleeve_probe.py -- $KF $V1 base   "$OUT\sleeve" --policy off    --frames 1,15,30,45,60
& $B -b --factory-startup -P reports\subai\M01\scripts\m01_sleeve_probe.py -- $KF $V1 static "$OUT\sleeve" --policy strict --frames 1,15,30,45,60

# 汇总 + 代表帧对比图
python reports\subai\M01\scripts\m01_collect.py
python reports\subai\M01\scripts\m01_sheet.py
```

## 7. 已知限制与跨模块申请

- 未验证：
  - S3 副本对裙/发/配饰的连锁影响：只证明「其它刚体 mode 未变、其它骨约束未变」，
    但 6 个胸口刚体从动态变 `kinematic` 后仍作为碰撞体参与碰撞，是否改变邻近单元的接触行为没测。
  - 只测了两条 VMD（Wushu / Sway）、30 fps 步进；没测 IK 开启的手臂动作与极端弯腰。
  - 视觉终审（胸口形态是否满意、袖子怎么改）未做，需用户看 `compare_chest.png` / `compare_sleeve.png`。
- 新发现但不能在本模块处理：
  - **非袖子物理骨里存在 359° 量级的逐帧跳变**（两变体完全相同，说明与袖筒无关，是另一个单元的问题）
    → 建议 M03/M04 把它当成一个独立故障归因，别混进 S5。
  - 卡芙卡袖筒 48 骨的父链挂在 `ひじ` 上，静音后袖子回 A-Pose 直筒形；这是「静态策略」的结构性缺陷，
    不是参数问题。
  - 本机 Blender 5.2.2 只暴露 `BLENDER_EEVEE`（没有 Workbench），EEVEE 需要自行布光；
    每轮渲染后退出时偶发 `EXCEPTION_ACCESS_VIOLATION`（数据已落盘，属退出阶段崩溃）。
- 需要其他模块提供的接口/文件：
  - M04 若要把「胸口冻结」做成门禁，判据可直接复用 `chest_extent_x / hip_extent_x` 的比例
    （本模块实测：冻结 0.40–0.53，纯跟随 0.66–0.74），ROI 定义见 `handoff.md`。

## 8. 下一步（只给一条）

- 把 `out/subai/M01/飞霄_s3_mode0.pmx` 作为 M02 的输入基线，按 `handoff.md` 的关节限位接口扩展补丁，
  做 S2 下摆限位与 S8 掩码实验；S5 另开一个会话按 `handoff.md` 的候选假设推进，不要在本模块继续换参数。
