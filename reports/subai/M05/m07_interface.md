# M05 → M07 接口使用说明（`chain/junctions+frames+nla_guard@1`）

> 面向：A4 / M07（插件四区面板与接线）。
> 事实来源：`e205151` 入库的 `mmdpipe/{chainplan,concatvmd,chain_nla,runner}.py`，**本文件所有字段与数值都在 2026-11-16 实跑过**（纯 Python，无 Blender）。
> 完整真实样例：`reports/subai/M05/plan_sample.json`（本文件 §3 是它的精简版）。
> 状态：接口本身 `interface_ready`；**§7 那四条是 `UNVERIFIED`，别把接口当物理结论读。**

---

## 1. 三条入口（M07 只需要这三条）

```python
from mmdpipe import chainplan, concatvmd

plan  = chainplan.plan(paths, pmx_path=None, gap=DEFAULT_GAP, fps=30.0, limit=12)   # 只读 dry-run，不写文件
crep  = concatvmd.concat_vmd(paths, out_path, gap=2, verbose=False, frames=244)
ok, why = chainplan.nla_segments_check(len(paths))                        # (bool, str)
```

> `DEFAULT_GAP` 来自 `mmdpipe/chain_defaults.py`（**唯一声明处**，当前 `= 0`）。两个 CLI、两个函数签名都引它，不许再各写一个字面量（见 §1.1 第 2 条）。

- **`chainplan.plan()`**：不写任何文件、不需要 Blender。面板「拼接预检」就调它。
- **`concat_vmd()`**：真的写 `chain.vmd`。面板不要在用户点「开始」之前调它。
- **`nla_segments_check(n)`**：N>2 时必须**在写文件之前**拦，`why` 是给用户看的中文原因（见 §5）。
- **`chain_nla.extend_upper_strip(strip, a_last)`**：只在 Blender 里（`bpy`）可用，是交叉淡化延伸的**唯一入口**。M05 不导出第二个改 strip 帧值的地方；插件层若要碰 strip，请调它，不要自己算 `blend_in`。

### 1.1 命令行吃法（面板只吃 JSON 时用这两条）

两个 CLI 都支持 `--json <路径>`，写出来的就是函数返回的那个 dict（同一份，不裁剪）：

```powershell
# 预检：不写 .vmd，只出 JSON
python -m mmdpipe.chainplan <seg1.vmd> <seg2.vmd> <seg3.vmd> --gap 2 --quiet --json out/subai/M05/cli_samples/plan_cli.json

# 真拼接：写 .vmd + 出 JSON
python -m mmdpipe.concatvmd <seg1.vmd> <seg2.vmd> <seg3.vmd> --out <chain.vmd> --gap 2 --frames 244 --json out/subai/M05/cli_samples/concat_cli.json
```

三条**必须知道**：

1. **`--json` 收的是文件路径，不是"打到 stdout"**；父目录会自动创建。白名单里要带路径参数，不能只给 flag。
2. **`--gap` 仍然是显式传最稳，但两个 CLI 的默认值已经同源**：早先 `chainplan` 默认 `6`、`concatvmd` 默认 `0`，两段 91+91 不传 `--gap` 时预检 188 帧、拼接 182 帧，两个数都"正常"却永远对不上（D-040 的缺陷）。现在默认值只在 `mmdpipe/chain_defaults.py` 声明一次、两边都引用（当前 `= 0`），不传时两边都是 **182 帧**。面板仍应显式传 `--gap`，并在读数时看下面这条。
3. **帧账有两列，文本与 JSON 各一份**（新增）：`render_text()` 末尾打 `帧账校核：本段 gap=6 → 188 帧；不传 --gap 真拼接会是 182 帧（差 6 帧）`，gap 与默认值一致时打 `…与默认 gap=0 的真拼接一致`；**同一对数也进了 JSON**——`frames_if_default_gap`（见 §2.1）。M07 只吃 JSON，所以显示「预检 vs 成片会不会差帧」直接读这个键，不用解析文本。
4. `plan()` 的 `limit` **CLI 没有对应参数**，固定按默认 `12` 走（`missing_in` 最多 12 条骨名）。

---

## 2. `plan()` 返回字段（字段级）

### 2.1 顶层

| 字段 | 类型 | 单位 | 取值 / 语义 | 空值语义 |
|---|---|---|---|---|
| `inputs` | `list[str]` | — | 输入路径，**原样回显**（未规范化，可能是相对路径） | 至少 1 条 |
| `gap` | `int` | 帧 | 段间空档帧数，≥0 | — |
| `fps` | `float` | 帧/秒 | 默认 `30.0`；**只影响 `duration_s` 与 `deg_per_frame` 的换算，不重采样** | — |
| `segments` | `list[obj]` | — | 每段一条，见 2.2 | 至少 1 条 |
| `bone_sets` | `obj \| 缺省` | — | 仅 `len(segments) ≥ 2` 时存在，见 2.3 | 单段时**整个键不存在**（不是 `null`） |
| `junctions` | `list[obj]` | — | 每个相邻交接对一条，长度 = `n_segments - 1`；单段时 `[]` | `[]` |
| `pose_diff` | `list[obj]` | — | **兼容字段**：与 `junctions[0].pose_diff` **同一份内容**（两段时完全等价）；长度 = `bone_sets.common`（样例 45 条）；单段时 `[]` | `[]` |
| `overlaps` | `list[[pathA, pathB]]` | — | 时间轴重叠的相邻段对；空表示不重叠 | `[]` |
| `max_junction_angle` | `float` | 度 | 所有交接对里最大的 `max_angle_deg` | 单段时 `0.0` |
| `deg_per_frame` | `float \| null` | 度/帧 | `max_junction_angle / (gap+1)`；**`gap < 0` 时为 `null`** | `null` |
| `recommended_gap` | `int` | 帧 | `max(0, ceil(max_junction_angle / 5.0) - 1)`，按「5°/帧」的舞蹈观感阈值给的建议值 | ≥0 |
| `last_frame` | `int` | 帧 | 最后一段的末帧 | — |
| `total_frames` | `int` | 帧 | `last_frame + 1`（帧号 0 起算） | — |
| `total_duration_s` | `float` | 秒 | `total_frames / fps`，3 位小数 | — |
| `frames_if_default_gap` | `int` | 帧 | **同一份 segments 换成默认 `gap`（`DEFAULT_GAP`，当前 0）真拼接会得到多少帧** = `Σ段内帧数 + DEFAULT_GAP×(段数-1)`。面板拿它和 `total_frames` 比，就知道「现在这个 gap 会不会让预检与成片差帧」（D-040） | — |
| `roots_per_segment` | `list[list[str]]` | — | **仅传了 `pmx_path` 时**：每段按父链算出的根骨名 | 键缺失 |
| `roots` | `list[str]` | — | 上述的并集，最多 `limit` 条。**键恒在**：未传 `pmx_path` 时是 `[]`（不是 `null`，也不是键缺失——这一点和 `roots_per_segment` 不同） | `[]` |
| `local_root_pos_delta` | `list[obj]` | PMX 单位 | **仅传 `pmx_path`**：`{bone, local_pos_delta, a_pos, b_pos}`；**局部量，不是世界位移**（世界位移只能在 Blender 里测，见 §7-②） | 键缺失 |
| `pos_movers` | `list[obj]` | — | `junctions[0].pose_diff` 里 `pos_delta > 1e-6` 的，按 `pos_delta` 降序，最多 `limit` 条 | `[]` |
| `key_additions` | `obj` | 条 | 每段 `{"missing_bones": n, "would_add_keys": 2n}`；**估算值**，dry-run 不写文件 | 单段时 `{}` |
| `joint_gaps` | `list` | — | 预留（当前恒 `[]`，别接） | `[]` |

### 2.2 `segments[i]`

| 字段 | 类型 | 单位 | 语义 |
|---|---|---|---|
| `index` | `int` | — | 0 起 |
| `path` | `str` | — | 该段输入路径（回显） |
| `bones` | `int` | **条（记录数）** | ⚠️ 是**骨骼关键帧记录条数**，不是骨数。样例里 91 帧的一段是 `4732` 条；骨**种类**要看 `bone_sets.per_segment` |
| `bone_range` | `[int, int]` | 帧 | 源文件里的首末帧（未加偏移） |
| `morphs` | `int` | 条 | 表情记录数 |
| `morph_range` | `[int,int] \| null` | 帧 | 无表情记录时 `null` |
| `camera` / `light` / `shadow` / `ik` | `int` | 条 | 对应轨道记录数 |
| `ik_range` | `[int,int] \| null` | 帧 | 无 IK 开关记录时 `null` |
| `tail_valid` | `bool` | — | 文件尾部轨道能否解析到结尾；`false` 表示文件头计数与实际不符 |
| `offset` | `int` | 帧 | 该段在拼成的时间轴上被放到哪一帧起 |
| `timeline` | `[int, int]` | 帧 | `[offset + 段内首帧, offset + 段内末帧]` —— **面板显示这一对** |
| `expected_count` | `int` | 帧 | `timeline[1] - timeline[0] + 1` |
| `gap_after` | `int` | 帧 | 本段之后留的空档（最后一段也照写，便于统一渲染） |
| `duration_s` | `float` | 秒 | `timeline[1] / fps`（3 位小数） |

### 2.3 `bone_sets`

| 字段 | 类型 | 语义 |
|---|---|---|
| `union` / `common` | `int` | 所有段的骨名并集 / 交集 |
| `per_segment` | `list[int]` | 每段的骨**种类数**（样例 `[52, 252, 252]`） |
| `missing_counts` | `obj[str,int]` | 键是段序号字符串，值是「并集 − 本段」的骨数 |
| `missing_in` | `obj[str,list[str]]` | 同上，但只给前 `limit` 条名字（**有截断，别当全量**） |

### 2.4 `junctions[k]`（每个交接对一条）

| 字段 | 类型 | 单位 | 语义 |
|---|---|---|---|
| `pair` | `[int,int]` | — | 段序号对，如 `[1,2]` |
| `a_path` / `b_path` | `str` | — | 两段路径 |
| `a_last_frame` / `b_first_frame` | `int` | 帧 | 用于比姿态的源帧号（A 的末帧 / B 的首帧） |
| `timeline` | `[int,int]` | 帧 | `[A.timeline[1], B.timeline[0]]`，中间就是空档 |
| `gap` | `int` | 帧 | 空档帧数 |
| `over_threshold` | `int` | 根 | 角或位置超阈值的骨数 |
| `max_angle_deg` | `float` | 度 | 该交接对里最大的角差（`pose_diff` 已降序） |
| `pose_diff` | `list[obj]` | — | **完整列表，不是 top-N**：长度 = `bone_sets.common`（样例每对 **45 条**），按 `angle_deg` 降序；元素见 2.5。面板要前几名自己截，别以为里面只有 3 条 |

### 2.5 `pose_diff[i]`

| 字段 | 类型 | 单位 | 语义 |
|---|---|---|---|
| `bone` | `str` | — | 骨名（源文件里的名字，可能是日文/中文） |
| `angle_deg` | `float` | 度 | 两帧姿态的旋转夹角（2 位小数） |
| `pos_delta` | `float` | PMX 单位 | 三轴位移最大绝对值（3 位小数） |
| `pos_delta_mm` | `float` | mm | `pos_delta × 80` 的粗换算（⚠️ 只对已知比例模型准，别当精确值） |
| `severity` | `str` | — | `info` / `warn` / `error`；阈值：角 `20°/45°`，位置 `1.0/2.5` PMX 单位 |

---

## 3. 真实输出样例（2026-11-16 实跑，91/91/151、gap=2）

完整版见 `reports/subai/M05/plan_sample.json`。精简：

```json
{
 "gap": 2, "fps": 30.0,
 "total_frames": 337, "last_frame": 336, "total_duration_s": 11.233,
 "frames_if_default_gap": 333,
 "overlaps": [],
 "segments": [
  {"index": 0, "bones": 4732, "bone_range": [0, 90], "morphs": 0, "morph_range": null,
   "camera": 0, "light": 0, "shadow": 0, "ik": 0, "ik_range": null, "tail_valid": true,
   "offset": 0, "timeline": [0, 90], "expected_count": 91, "gap_after": 2, "duration_s": 3.0}
 ],
 "bone_sets": {"union": 259, "common": 45, "per_segment": [52, 252, 252],
               "missing_counts": {"0": 207, "1": 7, "2": 7}},
 "junctions": [
  {"pair": [0, 1], "timeline": [90, 93], "gap": 2, "over_threshold": 26, "max_angle_deg": 106.47},
  {"pair": [1, 2], "timeline": [183, 186], "gap": 2, "over_threshold": 30, "max_angle_deg": 112.01}
 ],
 "pose_diff": [
  {"bone": "右手首", "angle_deg": 106.47, "pos_delta": 0.0, "pos_delta_mm": 0.0, "severity": "error"},
  {"bone": "左腕",   "angle_deg": 91.98,  "pos_delta": 0.0, "pos_delta_mm": 0.0, "severity": "error"},
  {"bone": "右腕",   "angle_deg": 89.08,  "pos_delta": 0.0, "pos_delta_mm": 0.0, "severity": "error"}
 ],
 "max_junction_angle": 112.01, "deg_per_frame": 37.34, "recommended_gap": 22,
 "pos_movers": [{"bone": "グルーブ", "angle_deg": 13.34, "pos_delta": 2.769,
                 "pos_delta_mm": 221.6, "severity": "error"}],
 "key_additions": {"0": {"missing_bones": 207, "would_add_keys": 414}}
}
```

⚠️ 上面是**精简版**（列表按可读性截断）。`plan_sample.json` 里完整的是：

- `pose_diff`：**45 条**（= `bone_sets.common`）；本节只摘前 3 条。`junctions[0]` / `junctions[1]` 各自也带一份 45 条的 `pose_diff`；
- `frames_if_default_gap`：上面那个 **333** 是同一份三段换成默认 `gap=0` 真拼接会得到的帧数（本例 `gap=2` → 337，**差 4 帧**）。面板用它和 `total_frames` 比就知道差帧；
- `segments[1]` / `segments[2]` 全文（本节只留 `segments[0]`，且省了它的 `path` 字段）；
- `inputs`（原样回显的三个输入路径）；
- `bone_sets.missing_in`：被 `limit=12` 截断的骨名（`missing_counts` 才是真实条数 207/7/7）；
- `joint_gaps`：恒 `[]`，预留，别接；
- `roots`：**恒在**，本例没传 `pmx_path` 所以是 `[]`；`roots_per_segment` / `local_root_pos_delta` 只在传了 `pmx_path` 时才出现（本例没有这两个键）。

**M07 请以 `plan_sample.json` 为解析样本**（它是 `chainplan.plan()` 的原样输出，未手工改过），本节只作导读。

**面板要显示什么**：`total_frames` / `total_duration_s` / 每段 `timeline` / `junctions[].timeline` 与 `max_angle_deg` / `recommended_gap`。**不要**显示 `pose_diff`（兼容字段，只覆盖第一个交接对）。

---

## 4. `concat_vmd()` 返回字段

| 字段 | 类型 | 单位 | 语义 / 空值 |
|---|---|---|---|
| `out` | `str` | — | 写出的路径 |
| `bytes` / `bytes_final` | `int` | 字节 | 拼接文件大小 / 加上表情合并后的大小 |
| `spans` | `list[obj]` | — | 每段 `{path, src_range, offset, dst_range, bone_records, morph_records}`，均帧/条 |
| `bone_records` / `morph_records` | `int` | 条 | 全文件记录数（守恒检查用） |
| `camera_records` / `light_records` / `shadow_records` / `ik_records` | `int` | 条 | 尾部轨道记录数 |
| `bone_tracks` / `morph_tracks` | `int` | 种 | 出现的骨名/表情名种类 |
| `fill` / `fill_added` | — | — | 缺键补齐信息（dry-run 口径，`key_additions` 的实测版） |
| `frame_range` | `[int,int]` | 帧 | 首末帧 |
| `final_range` | `[int,int]` | 帧 | 表情合并后的首末帧 |
| `total_frames` | `int` | 帧 | `max(spans.dst_range[1]) + 1` |
| `tracks_complete` | `bool` | — | 尾部轨道是否完整解析 |
| `overlaps` | `list` | — | 时间轴重叠段对，**非空表示丢段** |
| `requested_render_frames` | `int \| 缺省` | 帧 | **仅当调用时传了 `frames=`** 才有 |
| `explicit_truncated_frames` | `int \| 缺省` | 帧 | 同上：`max(0, total_frames - frames)` |
| `unexplained_gap_frames` | `int \| 缺省` | 帧 | 同上：现有实现恒 `0`（丢段走 `overlaps`/`runner` 的 BLOCK） |

**三笔账必须分开显示，不要合成一个「帧数」**：
`total_frames`（文件账本）／`requested_render_frames`（用户要渲多少）／`explicit_truncated_frames`（差的那些是**没渲**，不是**丢了**）。
实测：三段 337 帧、`frames=244` → `explicit_truncated_frames = 93`、`unexplained_gap_frames = 0`。

`runner` 把这三笔 + 渲染回填写进 `state["stages"]["S3_chain"]["metrics"]`，键名：`expected_total_frames` / `chain_total_frames` / `requested_render_frames` / `rendered_frames` / `frame_conservation`（枚举 `ok` / `truncated` / `mismatch`）。**面板读 `frame_conservation` 就够判断「这次成片是不是被截断了」。**

### 4.1 退出码：`2` 在 M05 和 M04 里是**两件不同的事**

| 工具 | 0 | 2 | 1 |
|---|---|---|---|
| `python -m mmdpipe.chainplan` | 正常出计划（JSON 已写） | **时间轴有重叠**（`overlaps` 非空），**JSON 照样写了**。实测只在 `--gap < 0` 时触发（自动排布下 `gap ≥ 0` 不会重叠） | 输入读不了（VMD/PMX/OSError），不写 JSON |
| `python -m mmdpipe.concatvmd` | 正常拼接（JSON 已写） | **时间轴有重叠**，**JSON 照样写了**。`--offsets` 手动排布时会出现 | 同上，不写 JSON |
| `physics_gate`（**M04**） | `PASS` | **`ERROR`：出异常，不产出任何 JSON** | `FAIL` |

**所以面板不能共用一条「退出码 2 = 出错、别读 JSON」的判定**：M04 的 2 确实没有 JSON 可读，M05 的 2 是「跑完了但有重叠」，JSON 必须读，而且 `overlaps` 正是要显示的东西。M04 的契约见 `reports/subai/M04/m07_interface.md` §4.1。

**重叠时 `total_frames` 会缩水，别拿它当帧账本**：实测两段都落在 `0..90` 时，`total_frames` 从 182 掉到 **91**（后一段被完全盖住），同时 `overlaps` 有 1 对。**判丢段只看 `overlaps`，不看帧数。**

`--json` 写盘用的是 `mmdpipe.report.dump()`：`ensure_ascii=False`、`indent=2`、UTF-8、**没有 `sort_keys`**（键序＝字典插入序）。要做哈希比对先自己规范化，别指望两次 dump 的字节序相同。

实测样本（命令见 §1.1，均在 2026-11-16 由 **CLI 实际产出**，不是手写）：

| 文件 | 说明 | sha256 |
|---|---|---|
| `out/subai/M05/cli_samples/plan_cli.json` | 三段 `--gap 2` 的预检 JSON（= Python 返回值） | `58609d8c…` |
| `out/subai/M05/cli_samples/concat_cli.json` | 三段 `--gap 2 --frames 244` 的拼接 JSON | `ee93063d…` |
| `out/subai/M05/cli_samples/concat_overlaps.json` | `--offsets 0,0` 造重叠：`exit 2` + `overlaps` 1 对 + `total_frames 91` | `b90c845d…` |
| `out/subai/M05/cli_samples/plan_cli_no_gap.json` | **不传 `--gap`** 的预检（默认 0 → **182** 帧，`frames_if_default_gap` 也是 182） | `b561a1d4…` |
| `out/subai/M05/cli_samples/concat_cli_no_gap.json` | **不传 `--gap`** 的拼接（默认 0 → **182** 帧，与上一行一致） | `aeb9d1e6…` |
| `out/subai/M05/cli_samples/plan_negative_gap.json` | `--gap -1` 造重叠：`exit 2` + `overlaps` 1 对 + `deg_per_frame null` + `total_frames 181` + `frames_if_default_gap 182` | `e5173e0f…` |
| `out/subai/M05/cli_samples/preflight_gap_delta.txt` | 预检文本（`--gap 6`）：`帧账校核…差 6 帧` | `6166adf9…` |
| `out/subai/M05/cli_samples/preflight_default.txt` | 预检文本（不传 gap）：`与本段默认 gap=0 的真拼接一致` | `aef8a7f5…` |

**D-040 的修复已在这一版代码里**：`mmdpipe/chain_defaults.py` 是 `DEFAULT_GAP = 0` 的唯一声明处，`chainplan.plan()` / `concatvmd.concat_vmd()` 两个签名、两个 CLI 的 `--gap` 全部引用它；`chainplan.total_frames_for_gap(rep, gap)` 负责把「另一个 gap 会得到多少帧」算出来给预检打印。**产出字节没变**（`concatvmd` 原本默认就是 0），只有预检数字的口径统一了。

---

## 5. `nla_segments_check(n)`

```python
(False, "NLA 模式一次只支持 2 段（当前 3 段）：在写 chain.vmd 之前 BLOCK，不静默丢段。改用 --chain-mode splice，或拆成两次两段任务。")
(True,  "")
```

- `n == 2` → `(True, "")`
- `n < 2` → `(False, ...)`
- `n > 2` → `(False, ...)`，**必须在写 `chain.vmd` 之前拦**。原实现是 `warn` 后继续用 `paths[0]/[1]`，等于静默丢掉第 3 段起的所有内容，state 还报成功。
- M07 面板：「3 段 + NLA」这个组合要么禁用，要么点了就给这条 `why` 并**不启动**。

---

## 6. 两张清单

### 6.1 「面板可直接显示」——这些是 M05 自己的、已实测

| 面板项 | 数据来源 | 备注 |
|---|---|---|
| 段数 / gap / fps | `plan().gap/fps`、`len(segments)` | — |
| 每段时间轴 | `segments[i].timeline` | 帧号 0 起 |
| 总帧数 / 总时长 | `total_frames` / `total_duration_s` | — |
| 交接对数量 | `len(junctions)` | 必须显示，别只显示第一个 |
| 每个交接的姿态差 | `junctions[k].max_angle_deg` / `over_threshold` | — |
| 建议 gap | `recommended_gap` | 按 5°/帧 的观感阈值 |
| 时间轴重叠 | `overlaps` | 非空 = 丢段风险 |
| 骨集缺失 | `bone_sets.missing_counts` | 名字样例有截断 |
| 帧数守恒 | `frame_conservation` + 四笔账 | `ok`/`truncated`/`mismatch` |
| NLA 段数门禁 | `nla_segments_check(n)` | N>2 直接拦 |

### 6.2 「不归 M05，别算到这条接口上」

| 面板项 | 归属 | 说明 |
|---|---|---|
| 物理门禁结论（PASS/FAIL/UNKNOWN） | **M04** | `physics_gate` 的输出，M05 不产出（`runner` 只有 `G1–G9` 的流程门禁） |
| 归因结论 `primary`/`confidence` | **M03** | `diagnose/1` |
| 材质/外观路线 `look.route` | **M07 自己** | `stage_look` 是舞台层，属 M07 的 M07 四区面板 |
| 相机取景 / `G7` / `G9` | **M07 舞台层** | 取景是 `stage.py` 的事，M05 只负责把时间轴接对 |
| 资产库统计（27 条等） | **M06** | 见 `asset_ledger.json` |
| 世界空间位移 | **Blender 侧** | `chainplan` 只有局部量，见 §7-② |

---

## 7. `UNVERIFIED`（接口背后**没有**验过的东西，别当结论读）

| # | 项 | 状态 | 具体 |
|---|---|---|---|
| ① | 「悬空坐姿」视觉复现 | **UNVERIFIED / 无样本** | 已修的是**帧映射**（f846 1.00696 m → ≤0.00007 m），但原始坏样本找不到，**没有做同机位视觉 A/B**，不能宣称「悬空坐姿已修」 |
| ② | 导出 VMD 再导入 Blender 的世界姿态 | **UNVERIFIED** | 只比到「导出文件 vs splice 文件」在 380 个共有帧上差 0.0000；**没有再导入 Blender 求世界矩阵**。`local_root_pos_delta` 是局部量，**不是世界位移**（同一对动作，纯 Python 报 124.6 mm，Blender 实测 `センター` 只有 30.5 mm） |
| ③ | freeze 后 f1 的 bake 差 | **UNVERIFIED** | f1 处 bake 前后差 **12.96 mm**，只有首帧，未查原因 |
| ④ | `blend > gap`（淡化比空档长） | **UNVERIFIED** | 未测。此时 `extend_upper_strip` 会让 B 提前覆盖 A 尾部，行为未知 |

另外两条实现层限制（不是风险，是已知设计）：
- 12 帧探针预算 **2/2 已用尽**（M05 任务书 §4），后续只能用 2 帧回归。
- NLA 只支持 2 段（泛化未做，改为 BLOCK）。

---

## 8. 兼容与版本

- 接口标签：`chain/junctions+frames+nla_guard@1`（M05 `e205151` 起）。
- 2026-11-16 补 §1.1 与 §4.1（CLI 吃法、退出码语义、重叠口径）：**只补文档、没改一行代码**，所以标签不升版。但**退出码判定必须从这一版开始按 §4.1 写**——M05 的 `2` 是「跑完了但有重叠（JSON 照写）」，不是 M04 的「`ERROR` 不出 JSON」。
- 2026-11-16 晚些（D-040）**改了代码**：`gap` 默认值收到 `mmdpipe/chain_defaults.py` 一处声明（`DEFAULT_GAP = 0`），两个 CLI 与两个函数签名都引用；`render_text()` 末尾新增「帧账校核」两列。**接口标签仍不升版**——字段名、JSON 键序、`exit 2` 语义、产出字节都没动，改的是「默认值从哪来」和「预检多打一行」。M07 若要忽略这一行，解析侧不受影响。
- `pose_diff` 旧语义保留＝首个交接对；**N 交接请读 `junctions`**。
- 字段只增不改；要改语义必须升 `@2` 并同步本文件与 `reports/subai/M05/handoff.md`。
