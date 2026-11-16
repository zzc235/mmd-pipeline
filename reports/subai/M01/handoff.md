# M01 handoff（给总控 / M02 / M04）

## 1. 已证实

1. **飞霄胸口冻结 = 硬约束，不是动力学过冲。**
   24–29 号刚体全 `mode2`，左右胸链的**根关节**（joint 0: 6→24、joint 3: 6→27）6DOF 限位与弹簧
   全为 0（完全焊死）；链内 joint 1/2/4/5 有限位（30°/35°）但弹簧 0。
2. **`mode 2→0` 一条命令就能让胸口回到纯跟随**：副本只 6 字节差异，重建后胸口 6 根骨上的
   `COPY_ROTATION` 从 6 条变 0 条（全模型 264→258，其它约束一条不差），胸口顶点与「关物理」静态
   对照**逐帧完全相等（0.00000 m）**，两条不同动作都成立。
3. **冻结的可量化特征**：胸口 ROI（71 顶点）横向尺寸在冻结时只有纯跟随的 60–75%，
   `chest_extent_x / hip_extent_x` 从 ~0.73 掉到 ~0.43，胸口顶点偏离纯跟随 0.23 m（均值）。
4. **卡芙卡袖筒结构**：2 个单元各 25 刚体/48 关节/环 24/焊 50%，单元内**没有 mode2**（全模型的 2 个
   mode2 在别处）→ S3 的修法不适用；`strict` 策略与 `force-static xk_` 命中的是**同一组 48 根骨**。
5. **静态策略的边界**：48 条约束全静音、`still_unmuted=0`，袖筒骨 >45°/帧 从 35 次降到 0、
   全局最大逐帧转角 343.35°→12.61°，且非袖子物理骨的逐帧指标**一位不差**（359.258° 两边相同）。

## 2. 未证实

1. S3 副本对裙/发/配饰的连锁影响（6 个胸口刚体变 `kinematic` 后仍是碰撞体，接触行为未测）。
2. 仅两条 VMD、30 fps 连续步进；未测 IK 手臂动作、极端弯腰、更长片段。
3. 静态策略的视觉可接受性：代表帧显示袖筒被拉成刚性长条（f45 包围盒 1.10×0.63 m，base 0.13×0.34 m）。
4. GUI 人工验收（全程 `blender -b`，未点过面板）。

## 3. 剩余风险

- `patch_save(rigid_mode=...)` 依赖解析期记下的字节偏移；对**另一个版本的 PMX** 必须先 `load` 再写，
  直接拿旧 model 写新文件会被「偏移过期」校验拒掉（这是设计行为，不是 bug）。
- `mode 2→0` 是**去掉胸部物理**，不是"修好胸部物理"。若产品要求胸口有独立摆动，需要
  「保留 mode2 + 解开根关节焊死」的另一种修法（M02 的关节限位补丁方向），本模块未做。
- 非袖子物理骨存在 359° 量级跳变，与本模块修复无关，但会干扰后续门禁阈值。

## 4. 给 M02 的接口（不是口头"可以复用"，是可直接照抄的坐标）

**刚体 mode 补丁（已实现、已测）**

```python
from mmdpipe import pmx
m = pmx.load(SRC)                        # 必须 load 一次，偏移来自解析
pmx.patch_save(m, DST, rigid_mode={24: 0, 25: 0, 26: 0, 27: 0, 28: 0, 29: 0})
```

- 参数校验：index ∈ [0, len(rigids))；mode ∈ {0,1,2}；`dst != 源路径`；写前回读旧值，偏移过期即抛错。
- 只写单字节，不重序列化，输出长度 = 源长度。

**关节限位/弹簧补丁（本模块未实现，但结构已探明，扩展方式如下）**

PMX 关节段每条 = `name, name_en, kind(u8), a(index rs), b(index rs)`，接着从 `position` 起：

| 字段 | 相对 `joint_pos_offsets[i]` | 宽度 |
|---|---|---|
| position | +0 | 3f |
| rotation | +12 | 3f |
| 平移下限 / 平移上限 | +24 / +36 | 3f / 3f |
| 旋转下限 / 旋转上限 | +48 / +60 | 3f(rad) / 3f(rad) |
| 平移弹簧 / 旋转弹簧 | +72 / +84 | 3f / 3f |

> **勘误 2026-11-16（模块负责1）**：旋转弹簧初版写 `+78`，实测为 **`+84`**。关节尾部共 24 float = 96 B
> （position +0 / rot +12 / lpm +24 / lpx +36 / lrm +48 / lrx +60 / sp +72 / **sr +84**）。
> `+78` 落在 sp 第 3 个 float 内部，写进去 PMX 仍能解析、`spring_rot` 仍读 0，sp 第 3 个 float 变成 1e-41 量级的反规格化数，
> 语义字段看不出异常，只有逐字节比能抓。已同步改 `patch_manifest.json` / `measurements.json` / `result.md` §2
> 与共同工作区的 `M02_F4下摆与F6碰撞映射.md`。

- 这组偏移是**逐字节核对过的**（飞霄 joint 0/1/2：焊死关节 12 个限位全 0；有限位关节
  例如 joint 1 = 旋转 [0,-0.1745,0] → [0.5236,0.0873,0]），不是按规范猜的。
- 读取代码可直接抄 `reports/subai/M01/scripts/m01_baseline.py` 的 `joint_limits()`。
- 扩展建议：照 `rigid_mode` 的模式加 `joint_limit={index: (6 floats)}` / `joint_spring=...`，
  写前同样回读旧值校验；**不要**在 `patch_save` 里重排关节段顺序（PMX 关节的 `a/b` 索引宽度是 rs，
  不同模型不同）。
- 飞霄的 S2 下摆目标：改用 `physics.classify` 找 `suspect_units`/`welded` 单元，再按 `Unit.joint_ids`
  反查要改的关节索引，不要按名字猜。

**ROI 与判据（M04 做门禁时直接用）**

```
胸口骨（Blender 名，rename_bones=True 后）：胸.R 胸１.R 胸２.R 胸.L 胸１.L 胸２.L
髋骨：下半身 腰 / 躯干参考：上半身2
ROI 取法：顶点「权重最大的**骨骼**组」落在上述集合（必须排除 mmd_tools 的 mmd_edge_scale /
          mmd_vertex_order 非骨骼组，否则所有顶点都被归到 mmd_edge_scale 名下 —— 本模块踩过）
实测：胸口 71 顶点 / 髋 1250 / 躯干 1309（sc＝0.08 的世界坐标，单位 m）
判据：chest_extent_x / hip_extent_x，冻结 0.40–0.53，纯跟随 0.66–0.74
      或直接比「与关物理静态的逐顶点距离」，冻结 ≥0.22 m，正常 ≤0.0001 m
```

## 5. 环境复用提示

- 必须 `addon_utils.enable("bl_ext.user_default.mmd_tools")`（`--factory-startup` 下不会自动启用，
  `bpy.ops.mmd_tools.import_model` 会报 not found）。
- `import_model(types=...)` **必须含 `"PHYSICS"`**，否则 `Model.build()` 建出 0 个刚体（不会报错，静默为 0）。
- `import_vmd` 前要 `root.select_set(True)` + `view_layer.objects.active = root`，否则
  `poll() failed, context is incorrect`。
- `scene.rigidbody_world.enabled` 建完是 False，要手动开，并设 `substeps_per_frame=10`、
  `solver_iterations=20`（与预设一致）。
- 本机只有 `BLENDER_EEVEE` 可用（无 Workbench）；EEVEE 需自行加灯。副本 PMX 换目录会丢贴图，
  形状对照要统一材质。
