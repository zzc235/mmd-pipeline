# `m08_extra_bodies_patch_v1`：324 缺口的有声明输入补丁（格式 + 校验 + 控制）

**背景**：交付件 `B_from_blend1.blend` 有 324 个刚体，`stage_import` 重建出来的只有 312。
差的 12 个是 `$name_j` / `.001`–`.010`（11 个 BOX，`kinematic=True`，挂 `下擺_11_7..17`）
加 `地面_物理`（凸包，`z=-0.01`，**唯一的地面**）。它们不在 PMX 里，也没有任何代码生成它们
（`stage.py:263` 的原话是「旧场景里手工加的对象」）。清单与双向差集见 `m08_gap324.md`。

**裁决**：总控 2026-11-16 18:08 选 **A（有声明的输入补丁）**。理由：A 是唯一「来源可追溯」的
那条 —— 属性从旧件读出、补丁带 sha、重建时显式读一步。B（反推生成器）在没有规格时等于照字节
编语义；C（保持 312）等于承认交付件永远重建不出来。

## 一、总控那四条要求，逐条落法

| 要求 | 落法 | 证据 |
|---|---|---|
| ① 补丁是**数据文件**，12 个属性**从旧件读出、无手填值** | `m02_dump_extra_bodies.py --patch-out` 用 `m02_patch_bpy.body_spec()` 逐条实测（矩阵 16 位、网格顶点/面、rigid body 全部属性、`mmd_rigid`）写进 JSON | 该函数只读 `bpy` 属性，没有任何字面量默认值；读不到就抛 `PATCH_SPEC_NO_RIGID_BODY` |
| ② 补丁带来源三件套 | `source.blend` + `source.blend_sha256` + `source.extractor{path,sha256}` + `patch_sha256`（自洽哈希，改一个字节就对不上） | `--verify` 会重算 `patch_sha256` |
| ③ 重建时是**一个具名步骤**，identity 记补丁 sha | `m02_rebuild_scene_v3.py --patch` 里的 `apply_input_patch()`（报告里 `input_patch.step = "apply_input_patch"`）；`m02_build_delivery.py` 的身份记录写 `input_patch.{path,file_sha256,patch_sha256}` | 补丁不合法 ⇒ v3 **不建场景**、退 4、写 `status=PATCH_REFUSED` + `reason_code` |
| ④ 补完必须验回来 | 造完在同一次调用里 `body_spec()` 回读，`split_diff()` 分**硬/软**两层比；硬字段不一致 ⇒ 抛 `PATCH_READBACK_MISMATCH` 退 4 | 交叉点：刚体数 324 / `constraints_needed=10111` / `to_add=8298` / `already=1813`（下一窗口量） |

**硬字段**（不一致就停）：`name` / `name_stripped` / `type` / `mmd_type` / `parent` / `parent_type` /
`parent_bone` / `matrix_world` / `mesh` / `rigid_body` / `mmd_rigid`。
**软字段**（不一致写进报告、不判失败）：`matrix_parent_inverse` / `location` / `rotation_mode` /
`rotation_quaternion` / `scale` / `dimensions` —— 它们与 `matrix_world` 是同一个变换的不同写法，
判物理等价的是 `matrix_world` + `mesh` + `rigid_body`。四元数 `q` 与 `-q` 视为同一个旋转（实测控制覆盖）。

**空值规则（总控 18:18 §一 的口子，已补）**：只有**可为空白名单**
`NULLABLE_BODY_FIELDS = (parent, parent_type, parent_bone, mmd_rigid)` 允许两边都是 `null`；
其余字段**任一侧 `null` 一律判差异**，理由写「字段为空」而不是「不一致」。

为什么必须这样：v1 的 `diff_body` 里 `None == None` 为真 ⇒ 若补丁把 `matrix_world` / `mesh` /
`rigid_body` 之一写成 `null`、回读那边也是 `null`，strict 会判**一致** —— 等于「把刚体装到没有位置
的地方，而账面上合格」。这与 `mask_wired_checks` 缺 `skipped_count` 就要判红是同一件事：
**「没读到」与「读到空」必须分开**。白名单必须窄，不许顺手整类放行（有控制证明它是窄的）。

## 二、文件格式

```jsonc
{
  "patch_version": "m08_extra_bodies_patch_v1",
  "source": {
    "blend": "<旧件的绝对路径>",
    "blend_sha256": "<旧件 sha256>",
    "rigids_total": 324,            // 读完那一刻旧件的刚体总数
    "count_found": 12,
    "blender": "5.2.2",
    "extractor": {"path": "<抽取脚本绝对路径>", "sha256": "<脚本 sha256>"},
    "extractor_sha256": "<同上，便于单字段引用>"
  },
  "bodies": [
    {
      "name": "000_$name_j",        // 交付件里的对象名（带 NNN_ 前缀）
      "name_stripped": "$name_j",   // 去前缀后的名字（与清单对齐用）
      "type": "MESH", "mmd_type": "RIGID_BODY",
      "parent": "星穹铁道—飞霄（无外套）_arm", "parent_type": "ARMATURE",
      "parent_bone": "下擺_11_7",
      "matrix_world": [16 个数], "matrix_parent_inverse": [16 个数],
      "location": [3], "rotation_mode": "QUATERNION", "rotation_quaternion": [4],
      "scale": [3], "dimensions": [3],
      "mesh": {"vertices": [[x, y, z], ...], "faces": [[i, j, k, l], ...]},
      "rigid_body": {"mass", "friction", "restitution", "kinematic", "collision_shape",
                     "collision_collections": [20 个 0/1], "collision_margin",
                     "linear_damping", "angular_damping", "use_margin", "enabled"},
      "mmd_rigid": null             // 读不到也必须写 null：「读不到」≠「没读过」
    }
  ],
  "patch_sha256": "<对除本键外全部内容按 canonical json 取 sha256>"
}
```

**算法**：`sha256(b"m08_extra_bodies_patch_v1\n" + canonical_json(patch 去掉 patch_sha256))`，
`canonical_json` = `json.dumps(..., sort_keys=True, ensure_ascii=False, separators=(",", ":"))`。

网格必须进补丁的原因：BOX 的凸包由对象自身网格（× scale）决定，`地面_物理` 是 `CONVEX_HULL`——
只记「形状枚举」造不出同一个碰撞体。顶点/面是**数据**，不是选型。

## 三、拒绝码（全部 fail-closed，不编默认值）

| reason_code | 什么时候 |
|---|---|
| `PATCH_NOT_FOUND` / `PATCH_NOT_JSON` | 文件不在 / 不是 JSON |
| `PATCH_VERSION_MISMATCH` | 版本串不是 `m08_extra_bodies_patch_v1` |
| `PATCH_SHA_MISSING` / `PATCH_SHA_MISMATCH` | 没盖 sha / 盖了但内容被改过 |
| `PATCH_SOURCE_MISSING` / `PATCH_SOURCE_INCOMPLETE` | 没有 `source` / 缺字段（含 `extractor`） |
| `PATCH_INVALID` | 12 条不齐、重名、缺字段、`name` 与 `name_stripped` 不自洽、`mmd_rigid` 键被删 |
| `PATCH_SOURCE_SHA_MISMATCH` | 来源件在盘上，但重算 sha 与补丁记的不一致 |
| `PATCH_NAME_EXISTS` | 场景里已有同名对象（补丁不许覆盖既有内容） |
| `PATCH_PARENT_MISSING` / `PATCH_BONE_MISSING` | 父级/父骨不在场景里 |
| `PATCH_MESH_FAILED` / `PATCH_RIGIDBODY_ADD_FAILED` / `PATCH_PROPERTY_FAILED` | 造网格 / 加刚体 / 写属性失败 |
| `PATCH_COUNT_MISMATCH` / `PATCH_READBACK_MISMATCH` | 装上的条数不对 / 装上了但硬字段回读对不上 |

## 四、控制（哪些已跑、哪些还没跑）

**已跑（纯 Python，`python reports/subai/M02/scripts/m02_patch_format.py --selftest`，19 条 / 失败 0 / exit 0；
GBK 控制台下同样 exit 0 —— 入口已 `sys.stdout.reconfigure(encoding="utf-8")`，不会再崩在打印上）**：

| # | 项 | 实测 |
|---|---|---|
| 1–2 | 正控：合法补丁通过；12 条都在 | 通过 / 12 |
| 3 | 手改一个质量、不重盖 sha | `PATCH_SHA_MISMATCH` |
| 4 | 删一条 body、重盖 sha | `PATCH_INVALID`（报「缺 `地面_物理`」） |
| 5 | 删 `mesh` | `PATCH_INVALID` |
| 6 | 删 `source` | `PATCH_SOURCE_MISSING` |
| 7 | 重盖后改版本串（像手改文件） | `PATCH_VERSION_MISMATCH` |
| 8 | 删 `mmd_rigid` 键 | `PATCH_INVALID` |
| 9 | 抽掉 `extractor` | `PATCH_SOURCE_INCOMPLETE` |
| 10–12 | 一致性：kinematic 翻一位 ⇒ diff 非空；同一份 ⇒ 空；改过内容 ⇒ sha 变 | 对 |
| 13–14 | 分层：只改 `location` ⇒ 硬空/软非空；改质量 ⇒ 硬非空 | 对 |
| 15 | 四元数 `q` 与 `-q` 视为同一旋转 | 0 处差异 |
| 16 | 空值①：`matrix_world` 两边都 `null` ⇒ **strict 非空** | 非空 |
| 17 | 空值②：`rigid_body` 两边都 `null` ⇒ **strict 非空** | 非空 |
| 18 | 空值③：白名单 `parent_bone` 两边 `null` ⇒ strict 为空（证明白名单是窄的） | 空 |
| 19 | 空值④：白名单字段一边 `null` ⇒ strict 非空 | 非空 |

**反向控制**（证明自检会红）：把 `compute_patch_sha` 改成「只盖 source、不盖 bodies」
（回到「补丁被改过也看不出来」的形状）⇒ **2 条红**（第 3 条与第 12 条），exit 1。

**文件级控制**（`--verify`，四个方向都有读数）：

| 输入 | 结果 |
|---|---|
| 合法补丁 | `OK`，exit 0，打印 `patch_sha256` / 来源件 sha / 抽取脚本 sha / 12 条 |
| 手改一条质量 | 拒绝 `PATCH_SHA_MISMATCH`，exit 2 |
| 只有 11 条（自洽但不完整） | 拒绝 `PATCH_INVALID`「补丁缺这 1 条：['地面_物理']」，exit 2 |
| 文件不存在 | 拒绝 `PATCH_NOT_FOUND`，exit 2 |

**还没跑（必须在 Blender 窗口内，未做就是未做）**：`apply_input_patch` 的造对象/父骨/刚体属性
写入与回读比对、`PATCH_SOURCE_SHA_MISMATCH` 的真实来源件路径、以及 324 刚体的四个交叉点数字。
它们下一次锁窗口验证；在那之前本文档只能说「格式层已验、apply 层待验」。

## 五、实现分布（只许一份）

| 文件 | 职责 |
|---|---|
| `m02_patch_format.py` | 纯 Python：格式、canonical、`seal`/`verify`/`load`、`diff_body`/`split_diff`、前缀规则 `strip_prefix`、自检 |
| `m02_patch_bpy.py` | Blender 侧：`body_spec()`（读）与 `create_body_from_spec()`（造）——读与造**同一套字段名**，回读才能直接比 |
| `m02_dump_extra_bodies.py --patch-out` | 从旧件抽 12 条 → 盖 sha → 落盘（缺一条就 `exit 4`，不产出残缺补丁） |
| `m02_rebuild_scene_v3.py --patch` | 具名步骤 `apply_input_patch()`：校验 → 造 → 回读 → 不一致就停 |
