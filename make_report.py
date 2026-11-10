"""生成 v1 任务报告 + 快照，落到 桌面/ai用/dsh use/。"""
import hashlib
import json
import os
import platform
import subprocess
import sys
import time

ROOT = r"E:/dsh pr/woker2"
OUTDIR = r"C:/Users/zzc/Desktop/ai用/dsh use"
STAMP = time.strftime("%Y-%m-%dT%H%M")
TODAY = time.strftime("%Y-%m-%d")
TASK = "MMD流水线v1"

DELIVERABLES = [
    ("mmdpipe/__init__.py", "包入口 / v1.0.0"),
    ("mmdpipe/pmx.py", "PMX 解析 + 字节偏移 + patch_save"),
    ("mmdpipe/vmd.py", "VMD 解析"),
    ("mmdpipe/match.py", "VMD×PMX 命名匹配"),
    ("mmdpipe/physics.py", "物理资格判断器"),
    ("mmdpipe/clearance.py", "净空检测与修复"),
    ("mmdpipe/verify_pmx.py", "C1–C8 验证套件"),
    ("mmdpipe/mergevmd.py", "表情 VMD 合并"),
    ("mmdpipe/concatvmd.py", "多动作拼接"),
    ("mmdpipe/chainplan.py", "拼接 dry-run 计划（只报不改）"),
    ("mmdpipe/chain_nla.py", "NLA 路线拼接（分层/淡化/烘焙/导出）"),
    ("addon/mmd_pipeline/__init__.py", "Blender 扩展：operator + 面板"),
    ("dist/mmd_pipeline-1.1.0.zip", "可直接安装的扩展包"),
    ("docs/多动作拼接_设计纪要.md", "拼接设计纪要（共识 + 待决策）"),
    ("mmdpipe/preset.py", "预设"),
    ("mmdpipe/report.py", "数据契约"),
    ("mmdpipe/preflight.py", "命令行预检"),
    ("mmdpipe/stage.py", "Blender 阶段"),
    ("mmdpipe/runner.py", "编排 + 状态落盘"),
    ("run_pipeline.py", "Blender 入口"),
    ("README.md", "使用说明 + 实测结论"),
    ("CHANGELOG.md", "v1 变更"),
    ("presets/feiying.json", "绯英项目预设"),
    ("presets/feiying_camera.json", "绯英冻结相机"),
    ("presets/kafuka_v2_camera.json", "卡芙卡 v2 冻结相机"),
    ("out/卡芙卡3.0_fixH_mine.pmx", "净空修复产物（v1 验证件）"),
    ("kafuka_v2ab/result.mp4", "卡芙卡 480 帧成片（strict 策略）"),
    ("kafuka_chain_30fps/result.mp4", "两段拼接 833 帧 / 27.77 s（gap 6）"),
    ("kafuka_gap20/result.mp4", "两段拼接 847 帧 / 28.23 s（gap 20，过渡 4.6°/帧）"),
]


def sha16(path, size=None):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%.1f TB" % n


rows = []
snap_files = []
for rel, desc in DELIVERABLES:
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        continue
    size = os.path.getsize(p)
    h = sha16(p)
    rows.append((rel.replace("\\", "/"), fmt_size(size), h, desc))
    snap_files.append({"path": rel.replace("\\", "/"), "bytes": size,
                       "sha256_16": h, "role": desc})

pyver = platform.python_version()
bt = ""
try:
    out = subprocess.run([r"E:/code/Blender/blender-5.2.2-windows-x64/blender.exe", "--version"],
                         capture_output=True, text=True, timeout=60)
    bt = out.stdout.splitlines()[0].strip()
except Exception as exc:
    bt = "读取失败: %s" % exc

table = "\n".join("| %d | `%s` | %s | `%s` | %s |" % (i + 1, r[0], r[1], r[2], r[3])
                  for i, r in enumerate(rows))

md = """# 任务报告 · {today} · MMD 流水线插件定版 v1

- **任务编号**：`{today}-mmdpipe-v1`
- **发起人**：zzc
- **执行**：芙宁娜（dsh，直做）
- **时间窗**：{today} 17:27 → 22:0x（Asia/Shanghai）
- **关联**：`MMD全流程_工程报告_2026-11-08.md`、`卡芙卡任务报告_2026-11-08.md`、`mmd-physics.zip`、`blender-project.zip`

## 0. 一页摘要

把"PMX + VMD → 成片"这条链路从一次性脚本做成可复现的工具链，并定版 **v1.0.0**。

三件新能力：**物理资格判断器**（决定哪些部位不该做物理）、**净空检测与修复**（导入前修初始穿透）、**源文件只读守卫**（全程只读，改动只落副本）。

结果：自动修复与手工修复实测等价——袖子静音 48 骨/48 约束/0 遗漏，成片对 v2 的 PSNR **71.82 dB**、SSIM **0.99999**；净空修复与手工 `fixH.pmx` **位置 0 差异**，验证 7/7。

还差：表情 VMD 合并、道具并入、多动作拼接；物理求解器跨进程残余抖动 0.18%。

## 1. 背景与目标

用户原话（关键句保留）：

> "先不增加功能，先保证能稳定复现本次工作项目即可，如非必要，勿增实体"
> "流程里少了一个判断什么部位去做物理效果，默认全部衣物做物理了，加一个判断器吧，判断标准就是原模型要是关节本来就是限位全 0、弹簧全 0 就不做物理"
> "记得把参考里的检测改成通用检测，防止换模型认不出模型名和其他补件的名字"
> "在副本上做检测，把这次工程改动定为 v1"

**成功标准**：换一个模型（卡芙卡 + 爱乐之城）不改代码能跑通；判断器与净空修复的处理结果与原工程手工版本一致。

## 2. 交付物清单

| # | 路径 | 大小 | SHA256(前16) | 作用 |
|---|---|---|---|---|
{table}

## 3. 修改详情

### 3.1 新增

| 文件 | 作用 |
|---|---|
| `mmdpipe/physics.py` | 物理资格判断器。关节连通分量＝物理单元；判据全为结构量 |
| `mmdpipe/clearance.py` | 净空检测 + 外移修复 + 关节锚点同步 |
| `mmdpipe/verify_pmx.py` | C1–C8 验证套件（删去模型专属的 C3 锚点检查） |
| `mmdpipe/mergevmd.py` | 表情 VMD 合并（字节拼接，不重编码） |
| `mmdpipe/concatvmd.py` | 多动作拼接（只改帧号，其余字节不动） |
| `mmdpipe/chainplan.py` | 拼接 dry-run：全轨道 / 骨集差 / 姿态差 / 根链位移 |
| `CHANGELOG.md` | v1 变更与已知限制 |
| `presets/*.json` | 项目预设与冻结相机 |

### 3.2 修改

| 文件 | 改前 → 改后 | 原因 |
|---|---|---|
| `pmx.py` | 关节只存布尔 → 存 `limit_span`/`spring_max` 原始值 | 判断器需要区分"限位全 0"与"焊接" |
| `pmx.py` | `Rigid` 无 size/rotation → 补齐 | 净空需要胶囊几何 |
| `pmx.py` | 无写回 → `patch_save()` 按字节偏移改位置 | 重序列化是写坏文件的主因 |
| `pmx.py` | 权重索引用 `vs` → 改用 `bs` | HSR 三模型 vs==bs 掩盖了 bug，素体模型暴露 |
| `pmx.py` | 面段按面数读 → 试两种解释取可验证者 | 字段存的是索引总数 |
| `pmx.py` | 材质变形偏移固定 → `extra=0/1/2` 试解析 | 该导出器多 1 字节 |
| `pmx.py` | 表示枠条目按骨骼宽度读 → 按类型选宽度 | 表情条目是 1 字节 |
| `stage.py` | G7 只看刚体 → 网格求值包围盒+骨骼+刚体并集 | 卡芙卡刚体只覆盖 1.258 m，实际 1.758 m |
| `stage.py` | G5 按名字找裙摆 → 找不到就选位移最大者 | 卡芙卡刚体全叫 `HairA1_JNT` |
| `stage.py` | G5 累计位移 → 相邻采样位移 | 报告中"每 10 帧变化量"是相邻差 |
| `stage.py` | 描边查材质槽 → 查几何节点修改器 | 描边是 NODES 修改器，原查法永远为 0 |
| `stage.py` | 阻尼匹配不到时静默 → 显式 WARN | 卡芙卡没有"裙"类刚体 |
| `runner.py` | 无物理判断 → `S1_physics` + `S2_policy` | 判断→匹配→修理 |
| `runner.py` | 无净空 → `S1_clearance`，产物写 `<out>/pmx/` | 只改副本 |
| `runner.py` | 无只读守卫 → `S0_readonly` 首尾哈希比对 | 用户要求"在副本上做检测" |
| `runner.py` | 相机每次测 → 支持冻结 `camera.json` | 三次测量三种结果 |
| `runner.py` | 净空产物只写 PMX → 同时复制其引用的贴图 | PMX 用相对路径，挪目录后渲染变成纯色剪影（实测全紫） |
| `preset.py` | 无强制声明 → `force_static` / `force_physics` | 头发刚性这类取舍应可声明，不该让算法猜 |
| `runner.py` | 存盘未打包 → `pack_all()` 后存 | 贴图绝对路径换机即断 |
| `preset.py` | 无策略字段 → `physics.policy` / `clearance` / `camera.loc` | 行为可声明 |
| `__init__.py` | 插件壳 register() → 纯包 + `__version__ = "1.0.0"` | 壳引用的 operators/ui 不存在 |
| `README.md` | 新建 → 补判断器/净空/门禁/实测结论 | 交付可读 |

### 3.3 删除

- `mmdpipe/__init__.py` 中的 `register()/unregister()` 插件壳（引用了不存在的 `operators`/`ui` 模块，是定时炸弹）。

### 3.4 未触碰（显式声明）

- `~/.dsh/AGENTS.md`、`~/.dsh/memory/*`、`profiles/*/cordis.patch.yml`：**未读改**（仅读 `dsh_task_reports.md`）
- `E:/code/Blender/kafuka_short/**`、`feixiao_short/**`：**只读参考**，未写入（`k1_clearance.py`/`pmx_geom.py` 仅 grep 读取）
- `E:/blender模型/**`：**只读**，源 PMX/VMD 哈希首尾一致（已实测）

## 4. 关键决策记录

| # | 决策 | 理由 | 被否决方案 |
|---|---|---|---|
| 1 | 内核是库、插件是外壳 | 预检可脱离 Blender 秒级回答"能不能复用" | 一上来写 addon UI |
| 2 | 相机冻结而非每次测 | 同一 .blend 两次进程测出 X=1.005/1.159；渲同一帧却逐像素相同 | 每次跑都测（省不掉，且引入抖动） |
| 3 | 物理资格用结构量 | 名字每换模型就漏：卡芙卡 `HairA1_JNT`、飞霄中文 | 扩名字模式表 |
| 4 | 净空写回用字节 patch | 重序列化要处理附加 UV/morph 偏移，易产坏文件 | 整份重序列化 |
| 5 | 源文件只读 + 哈希守卫 | 用户明确要求"在副本上做检测" | 直改源文件 |
| 6 | 不自动改 PMX 的 mode/掩码 | 方案未验证、且 E-02 实测一次自动修错误率 86% | 全自动修物理 |

## 5. 实测证据

### 5.1 通得过

| 项 | 数据 |
|---|---|
| 解析 | 10/10 PMX、6/6 VMD，字节全对齐 |
| 绯英普查 | 270 刚体 / 339 关节 / 37 材质 / 同组自撞 528（报告全中） |
| 飞霄普查 | 312 / 389 / 952（报告全中） |
| VMD 匹配 | 复现 mmd_tools 的 `not found bone 上半身3` |
| 物理资格 | 四模型零误报；卡芙卡袖子 48 骨/48 约束/0 遗漏 |
| 袖子自动修复 vs 手工 v2 | 480 帧 PSNR 71.82/69.34 dB，SSIM 0.999990/0.999983，最差帧仅 2 像素差>8 |
| 净空修复 | 3 刚体 + 3 关节，C1–C8 全过，与手工 fixH **位置 0 差异** |
| 复现（绯英） | 冻结相机 360 帧 vs 原片，平均差 0.436/255 |
| 卡芙卡全片 | 480 帧 / 20.000000 s / 24 fps，八门禁全过 |
| 赛飞儿净空 | 真侵入 16 / 已修 14 / 跳过 2（附原因），C1–C8 全过，新增重叠 0 |
| 三特性叠加 vs 手工 v4 | 480 帧 PSNR 60.03/58.80 dB，SSIM 0.999855/0.999790 |
| 多动作拼接 | 原神摇+活着dj → 0..832，43962 骨帧逐条与源文件一致；Blender `chain_bone` 1..833 / 665 曲线 |
| 测量口径统一 | chainplan 不再输出伪世界位移；实测世界差 30.5 mm（原报 124.6 mm）|
| 换模型（宵宫） | PMX 解析干净（324 骨/218 刚体/20193 顶点）；VMD 从 .blend 官方导出，匹配 pass 无缺骨 |
| 外观回退 | HSR 材质不适用 → native；三点光标定 ×0.05（亮度 0.475、过曝 2.2%）|
| 参数声明层 | 21 字段单一来源；面板与 CLI 同源（面板缺 0 项）|
| 测试护栏 | unittest 27 断言 + bpy 冒烟 4 项，全绿 |
| 联络表 | S8 自动产出 contact_sheet.png（ffmpeg tile，12 帧 4×3，零自研代码）|
| 确认门 | gap 6 → BLOCK（13.7°/帧）；gap 20 → 通过（4.6°/帧）|
| 对齐接线 | NLA 烘焙前注入；判定用比例（9% → none，4.35 → match）|
| 取景门禁 | 833 帧成片：质心跨度 0.331（G9 触发）、最窄边距 0.158、未出框 |
| 插件安装 | `--command extension install-file` 成功；`bpy.ops.mmd_pipeline.render` 返回 FINISHED |
| 插件全流程 | 833 帧 / 27.766667 s，物理 strict + 净空 + NLA 拼接，门禁全过 |
| 拼接 dry-run | 骨集并集 259/交集 45；交接 23 根超阈值（左ひじ 95.9°）；根链位移差 124.6 mm |
| 过渡速度 | 95.9° 摊开：gap6 = 13.7°/帧、gap20 = 4.6°/帧；自动选切点只降 4%（无效） |
| 补键实测 | hold 与 none 在 f100/f600 逐骨位置完全一致；rest 会让 B 段膝/踝偏约 10 cm |
| 全轨道保留 | 爱乐之城/和刻晴睡觉 各 1 条 IK 记录已随段偏移保留；零尾段用例字节不变 |
| 帧率口径 | 833 帧 @30fps = **27.766667 s**（@24fps 本会是 34.708 s，慢 25%）|
| 全特性组合 | 拼接+表情+净空+strict+道具 一次跑通，16 阶段全 PASS |
| 道具挂接 | 3 个道具（刀/枪白/子弹）挂到左右手，偏差 0.000 mm；跨帧 f1/60/200/360 距离全部 0.0000 m |
| 表情合并 | 骨骼段/表情段均与源文件逐字节一致；导入后 `morph animations: 41`；`まばたき` 随帧 0→0.041→0.126 |

### 5.2 失败记录（必须写全）

1. **PMX 骨骼 flag 写反**：IK(`0x0020`) 与外部親(`0x2000`) 互换 → 错位 365 万字节。修：查规范改正。
2. **面段计数字段含义**：当面数读，3 倍过量 → 后续段全乱。修：两种解释都试，以"紧跟的纹理表能读通"为准。
3. **材质变形每条多 1 字节**：`照れ` 吃掉 1649 字节。修：`extra=0/1/2` 三试，以"表示枠数合理"为准。
4. **表示枠条目宽度**：按骨骼宽度读 → 表情框爆。修：条目是"类型 + 索引"，索引宽度按类型。
5. **权重索引宽度用错**：用 `vs` 而非 `bs`。HSR 三模型两者都是 2，直到测素体模型才暴露。
6. **单位口径**：PMX 单位直接乘 1000 当毫米，算出 74/40/90 mm。正确 `×0.08×1000`，改后 5.94/3.22/7.17 与报告 5.9/3.2/7.2 吻合。
7. **胶囊互叠误报**：飞霄一次报 25 条侵入、最紧余量 1369 mm。真相是头部多胶囊两两互叠（报告 §7 已记录）。修：胶囊互叠单独统计。
8. **mode0 纯碰撞体误报**：`首` 胶囊插进 `頭` 报 +53 mm。修：只有 mode1/2 会回填骨骼，才计入。
9. **"无关节刚体会掉"是假警报**：实测 f60 刚体 `(-0.6502,0.1032)` vs 骨骼 `(-0.65,0.1056)`，差 2 mm。修：降为 `collider` 档。
10. **`bones_for_policy` 不认 `report`**：回归测试直接抛 `ValueError`。修：`off`/`report` 同义。
11. **`compare_psnr.py` 格式串参数错位**：把 mad 当 psnr 打印。修：显式按元组下标。
12. **插件壳留了空引用**：`register()` 引 `operators`/`ui` 两个不存在的模块。修：本轮直接删除（定了 v1 就不留半成品）。
13. **贴图相对路径断裂**：净空修好的 PMX 写到 `out/pmx/`，但 PMX 里存的是相对路径贴图名，挪目录后渲染变成整片纯色剪影（全紫，SSIM 0.17）。修：`--clearance` 同时复制引用的贴图，缺失报 WARN。
17. **道具对象识别错**：用 `[o for o in objects if mmd_type==ROOT][-1]` 抓道具，拿到的是角色自己，导致 `parent_type='BONE'` 报 enum 只有 OBJECT。修：按导入前后的对象集合差集找新 ROOT。
18. **骨父级空间里用世界位移**：设了 `parent_type=BONE` 后改 `obj.location += world_delta`，偏差 0.58 m。修：直接赋 `matrix_world = Translation(delta) @ matrix_world`。
19. **检查脚本选错骨架**：按字母序取第一个 ARMATURE 拿到的是道具的 `刀_arm`，`bones['手首.R']` KeyError。修：按骨骼数取最多的。
20. **拼接后 IK 缺口暴露**：原神摇 VMD 自带 `足IK親` 轨，而卡芙卡模型没有对应 IK 骨，`S3_match` 报「IK 缺口，脚会滑」。这是预期行为（匹配层本来就该报），不加静音也不蒙混。
20. **拼接后表情没跟随段偏移**：`活着dj/表情.vmd`（帧 0..402）直接合到 0..832 的拼接时间轴上，表情全落到第一段。修：`vmd.merge(offset=)` 支持整体帧偏移，流水线按「表情文件与哪段动作同目录」自动取该段 offset（实测 expression_segment=1，落点 453..855）。
22. **多动作拼接只做到字节级，姿态没接上**（用户评审时指出）。实测：A 52 骨 / B 252 骨 / 交集 45；A 独有 7 根（含 上半身3、左右足D/ひざD/足首D）在 B 段无键会冻结在 A 末姿态；B 独有 207 根在 A 段无键、到交界处同时生效；交接处 左ひじ 相差 95.9°、頭 22.5°、上半身 14.0°。根骨位移这次恰好都是 0 所以没暴露，属运气。修法（明日）：补键 → slerp 交叉淡化 → 根骨对齐。
23. **帧率口径错了（影响所有成片）**：预设 fps 随手写的 24，而 VMD 帧号以 30fps 为基准。不重采样改 fps = 变速：833 帧 24fps 播 34.71 s，30fps 播 27.77 s，慢 25%。历史样片时间口径全部偏慢（绯英 360 帧 @24 = 15 s，而 447 帧动作在 30fps 下本就是 14.9 s，等于只渲 80% 的动作又拉长成 100% 时长）。修：默认 fps 改 30，非 30 时 S3_motion 报 WARN 并给时长对照。
24. **根链用并集算**：`全ての親` 只在 B 段动，并集视角下 `センター` 被误判为"有动画祖先"，而它其实是 A 段的根。修：根链按段分别探测。
25. **变量名遮蔽**：`for b in model.bones` 把 Segment 变量 `b` 覆盖成 Bone，`b.bones` 抛 AttributeError。修：改名 `bone`。
26. **拼接丢全轨道**：相机/灯光/阴影/IK 开关表全部丢失。实测 `爱乐之城`、`和刻晴睡觉`、`和胡桃睡觉` 各带 1 条 IK 记录，丢掉会让作者特意关闭的腿 IK 在常开下解算。修：四段一起搬并跟随段偏移；零尾段用例字节完全一致。
27. **转义链塌陷写坏源文件**：用 heredoc 写补丁时 `\x00` 层层解码成了真 NUL，`vmd.py` 里出现一个 NUL 字节，py_compile 报 `source code string cannot contain null bytes`。修：改用 write 工具落修复脚本，按字节把 NUL 换回转义文本。
28. **自动选切点无效**：在 A 段末 147 帧里搜最接近 B 首帧姿态的切点，最优 435 帧平均差 28.4° vs 现用 446 帧 29.5°，只降 4%。两段舞蹈手部基本姿态本就不同，切点优化对这对动作没用——记下来避免以后重复尝试。
29. **mmd_tools 导入起点是 scene.frame_current**：NLA 拼接后残留 453，后续导入的 action 变成 [454,1286]，前半段全空（渲染站桩）。修：导入前强制复位为 1。
30. **扩展包里绝对导入失效**：`from mmdpipe import vmd` 在 `mmd_pipeline.mmdpipe` 包内找不到。修：相对导入 + 独立脚本回退。
31. **NLA 两条轨道都设 REPLACE+HOLD**：上层 HOLD 外插向回覆盖整段下层（A 段冻成 B 首帧）。修：下层 HOLD、上层 NOTHING。
32. **G4 在短片段上误报**：24 帧时首帧与中帧本就接近。修：<48 帧降级为 WARN。
33. **取景检查口径连错两次**：先按骨点（`つま先ＩＫ.L` 贴地 → NDC y -0.23 误报），再按网格包围盒（轴对齐+静止姿态 → -0.38 仍误报），最后按渲染像素才对。结论：判出框只能用观众看到的像素。
34. **能力写了没接线**：align.py 完整实现却只有独立脚本引用，主管线全程不 import。修：接到 chain_nla 烘焙前，改 B 的 action。
35. **两个测量模块给相反结论**：chainplan 的局部量被当成世界位移（124.6 mm vs 实际 30.5 mm）。修：改名 + 声明能力边界，纯 Python 不再产出世界位移。
36. **对齐判据用绝对阈值**：脚位移 30 mm 门槛在交接处天然失效（姿态差就 351 mm）。修：改看根位移/脚位移比例。
37. **refactor 带走返回路径**：抽 `_fit_camera` 后 `stage_camera` 在无 `--camera` 时返回 None，runner 解包崩溃。之前的测试都带 `--camera` 所以没暴露——补测无预设路径才发现。
38. **先写代码后盘点能力**：拆 lighting skill 时直接搬三点光，实际该用的是 HSR 插件自带的`import_post_processing`（11 个 operator 里我们只用 6 个）。教训：先盘 operator/面板/资产，再决定写不写。
39. **`look.route` 是死配置**：永远走 HSR 六步，原神模型直接 BLOCK。修：hsr/native/auto 三路 + 材料失败自动回退。
40. **native 路线没有灯**：场景只有世界背景，渲出来发闷。补社区三点光，并按实测把能量缩到 5%。
41. **面板/CLI/测试/续跑四处各写各的**（评审指出）：逐个补字段会一直漂移。修：params.py 单一声明源，argparse 与 PropertyGroup 都由它生成。
42. **扩展包内只能用包内路径**：`from mmdpipe import ...` 在 bl_ext 包里会失败，必须走 `bl_ext.user_default.mmd_pipeline.mmdpipe`（冒烟测试永久盯住）。
14. **赛飞儿两只兜帽无法外移**：单点平移与整组平移的所有候选方向都会撞上耳朵或相邻兜帽件；该刚体移动前已与 10 个刚体重叠，属于模型自带的密集穿插簇。修：不硬修，记为"跳过 + 原因"，验证改为契约式（C4 已修+跳过=真侵入，C5 残留只允许出现在跳过名单内）。
15. **表情合并时目录未建**：`vmd.merge` 直接写文件，`out/vmd/` 不存在 → `FileNotFoundError`。修：merge 内部 `makedirs`。
16. **误判表情没生效**：第一次拿 `怒り` 验证，全程 0.0，以为失败；实际该轨在 VMD 里就是全 0 占位（41 条只有 4 条非零）。修：先查原始权重再选测试对象。

### 5.3 已排除的假设

- 进程隔离能消除抖动：不能（两次纯步进不渲染，第 360 帧仍差 0.51/255，第 180 帧完全相同）
- 渲前重新加载 .blend 能消除抖动：不能（残余不变）
- 删掉多余预演能消除抖动：不能

## 6. 环境快照

| 项 | 值 |
|---|---|
| 主机 | {host} |
| 系统 | {osver} |
| Python（内核侧） | {pyver} |
| Blender | {bt} |
| 编码 | ffmpeg `C:/Users/zzc/ffmpeg/bin/ffmpeg.exe`，libx264 crf 18 |
| 渲染 | 720×576 / 24 fps / TAA 10 / EEVEE |
| 插件 | `bl_ext.user_default.mmd_tools`、`jinfengling_hsr_addon`（未启用 MikuMikuRig） |

文件哈希见同名 snapshot JSON。

## 7. 后续扩张建议

| 优先级 | 事项 | 依赖 | 预计 |
|---|---|---|---|
| P0 | 赛飞儿兜帽 37.6 mm 实修并验证 | 现有 clearance | **已完成：14/16 修好，2 个判定不可安全外移（有据）** |
| P0 | `force_static` 预设（把 v4 头发刚性变成声明） | preset | **已完成，叠加后对 v4 为 60.03 dB** |
| P1 | 表情 VMD 合并（两文件叠加） | vmd/import_vmd | 1 小时 |
| P1 | 道具并入（刀/枪/子弹）独立子命令 | 最近骨绑定 | 2 小时 |
| P2 | 多动作拼接 | NLA 层 | 半天 |
| P2 | dsh 内 orbit 视窗（glb + three.js） | 中央面板插件 | 半天 |

## 8. 未完成与风险

1. **物理位级一致性做不到**：残余 0.18% 像素抖动，随帧数累积（180 帧内为 0）。要位级需烘焙缓存后渲，代价 +0.25 s/帧且有无头存盘段错误风险。
2. **`head_capsules()` 仍依赖骨名** `頭/头/head`（有回退：半径最大的胶囊）。这是全流程唯一剩下的命名依赖。
3. **阻尼施加目标仍按名字匹配**（`裙/下擺/skirt`），匹配不到只警告不施加。
4. **净空只处理"球/胶囊 vs 头部胶囊"**，未覆盖盒体、未覆盖躯干区域。
5. **未做四模型的端到端成片回归**：绯英、卡芙卡有；飞霄、赛飞儿只有解析与净空数据。
6. **多动作拼接缺姿态对齐**：只保证字节与时间轴正确；骨集合不一致、交接姿态跳变、根骨位移均未处理。当前只适用于"骨骼体系一致 + 首尾姿态接近"的两段拼接。

## 9. 复现步骤

```powershell
cd "E:\\dsh pr\\woker2"

# 1) 预检（不开 Blender，秒级）
python -m mmdpipe.preflight "模型.pmx" "动作.vmd" --json 报告.json

# 2) 出片（源文件只读，产物与副本都在 out 下）
$env:EAP = "E:\\code\\Blender\\blender-5.2.2-windows-x64\\blender.exe"
& $env:EAP -b -P run_pipeline.py -- `
  --pmx "模型.pmx" --vmd "动作.vmd" --out "out\\run1" --frames 480 `
  --camera "presets\\kafuka_v2_camera.json" `
  --physics-policy strict --clearance
```

## 10. 附录 · 阶段与门禁

```
S0_env → S1_census → S1_physics → S1_clearance → S3_match
      → S2_import → S2_build → S2_policy → S3_motion
      → S5_look → S6_camera → S7_render → S4_probe → S8_verify
```

`G1` 刚体>0 · `G2` 约束链≥0.8×刚体 · `G3` 动作>100 曲线 · `G4` 首帧≠中帧 · `G5` 探针刚体每 10 帧位移>5 mm · `G6` 非黑片 · `G7` 取景在框内 · `G8` 帧数连续+时长吻合 · `S0_readonly` 源文件哈希不变
""".format(today=TODAY, table=table, host=platform.node(), osver=platform.platform(),
           pyver=pyver, bt=bt)

os.makedirs(OUTDIR, exist_ok=True)
md_path = os.path.join(OUTDIR, "%s_%s_任务报告.md" % (TODAY, TASK))
with open(md_path, "w", encoding="utf-8") as fh:
    fh.write(md)

snapshot = {
    "reportVersion": 1,
    "taskId": "%s-mmdpipe-v1" % TODAY,
    "title": "MMD 流水线插件定版 v1.0.0",
    "capturedAt": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    "executor": "furina (dsh)",
    "version": "1.0.0",
    "workspace": ROOT.replace("\\", "/"),
    "deliverables": snap_files,
    "v1_capabilities": ["物理资格判断器", "净空检测与修复", "C1–C8 验证", "源文件只读守卫",
                        "相机冻结", "预设分层", "门禁 G1–G8"],
    "evidence": {
        "parse": {"pmx": "10/10", "vmd": "6/6", "bytes_aligned": True},
        "census_match": {"feiying": "270/339/528", "feixiao": "312/389/952"},
        "physics_judge": {"false_positives": 0, "kafuka_sleeve_bones": 48,
                          "kafuka_muted_constraints": 48, "missing": 0},
        "sleeve_autofix_vs_manual_v2":
            {"frames": 480, "psnr_mean": 71.82, "psnr_min": 69.34,
             "ssim_mean": 0.999990, "ssim_min": 0.999983, "worst_frame_pixels_gt8": 2},
        "clearance": {"moved": [24, 26, 33], "joints_synced": 3, "rounds": 3,
                      "verify": "7/7", "vs_manual_fixh_positions_diff": 0},
        "reproduce": {"frames": 360, "mean_abs_diff_255": 0.436, "psnr_min": 20.39},
        "motion_chain": {"segments": 2, "gap": 6, "frame_range": [0, 832],
                         "bone_records": 43962, "byte_identical": True,
                         "blender_action_range": [1, 833], "fcurves": 665},
        "clearance_saifeier": {"truth": 16, "moved": 14, "skipped": 2,
                                "verify": "8/8", "new_overlaps": 0,
                                "blocked_reason": "两只兜帽位于密集穿插簇，任何平移都会撞耳朵"},
        "three_features_vs_manual_v4":
            {"frames": 480, "psnr_mean": 60.03, "psnr_min": 58.80,
             "ssim_mean": 0.999855, "ssim_min": 0.999790},
        "kafuka_full": {"frames": 480, "duration_s": 20.0, "gates": "8/8 passed"},
        "expression_merge": {"bone_tracks": 252, "morph_tracks": 41,
                             "morph_coverage": 0.9756, "byte_identical": True,
                             "blender_morph_animations": 41},
        "contact_sheet": {"tool": "ffmpeg tile", "tiles": 12, "grid": "4x3",
                          "auto": True, "custom_code_lines": 0},
        "align_wired": {"path": "chain_nla 烘焙前", "rule": "根位移/脚位移 比例 <0.30 判姿态差",
                        "samples": {"原神摇+活着dj": [30.5, 351.5, "none"],
                                    "爱乐之城+和刻晴睡觉": [1202.0, 276.8, "match"]}},
        "framing_gate": {"centroid_span": 0.331, "worst_margin": 0.158,
                         "worst_frame": 821, "gate": "G9 WARN", "clipped": False},
        "addon": {"package": "dist/mmd_pipeline-1.1.0.zip", "installed": True,
                  "operator": "mmd_pipeline.render", "full_render_frames": 833,
                  "full_render_seconds": 27.766667, "all_gates_pass": True},
        "chain_dryrun": {"bone_union": 259, "bone_common": 45,
                         "pose_over_threshold": 23, "max_angle_deg": 95.9,
                         "root_shift_mm": 124.6,
                         "roots_per_segment": [["グルーブ"], ["全ての親", "操作中心"]]},
        "junction_speed": {"max_angle_deg": 95.9, "gap6_deg_per_frame": 13.7,
                           "gap20_deg_per_frame": 4.6, "recommended_gap": 19,
                           "auto_cut_gain_pct": 4},
        "fill_modes": {"hold_equals_none_at": [100, 600], "rest_knee_delta_m": 0.11,
                       "rest_ankle_delta_m": 0.10, "conclusion": "补键不改画面，也不消除跳变"},
        "full_tracks": {"ik_preserved": 2, "zero_tail_bytes_unchanged": True},
        "fps_convention": {"default": 30, "frames": 833,
                           "duration_30fps_s": 27.766667, "duration_24fps_s": 34.708333,
                           "note": "VMD 以 30fps 为基准；改 fps 不重采样即变速"},
        "full_composition": {"stages": 16, "all_pass": True,
                             "chain_segments": 2, "expression_segment": 1,
                             "clearance_moved": [24, 26, 33], "muted": 48, "props": 1},
        "props_attach": {"props": ["刀", "枪白", "子弹"], "bones": ["手首.R", "手首.L", "手首.R"], "err_mm": 0.0,
                         "follow_frames": [1, 60, 200, 360], "follow_distance_m": 0.0},
        "source_readonly": {"pmx_sha16_before_after_equal": True,
                            "guard_refuses_same_path": True},
    },
    "failures_recorded": 41,
    "untouched": ["~/.dsh/AGENTS.md", "~/.dsh/memory/*", "profiles/*/cordis.patch.yml",
                  "E:/code/Blender/kafuka_short/**", "E:/code/Blender/feixiao_short/**",
                  "E:/blender模型/**"],
    "known_gaps": [
        "物理求解器跨进程非位级一致，残余 0.18% 像素抖动",
        "head_capsules 仍按骨名识别（带回退）",
        "阻尼目标仍按名字匹配",
        "净空未覆盖盒体与躯干区域",
        "飞霄/赛飞儿未做端到端成片回归",
        "表情 VMD 合并、道具并入、多动作拼接未做",
    ],
    "nextSteps": [
        {"priority": "P0", "item": "赛飞儿兜帽实修并验证", "status": "done: 14/16，2 个不可安全外移（有据）"},
        {"priority": "P0", "item": "force_static 预设", "status": "done: 叠加后对 v4 为 60.03 dB"},
        {"priority": "P1", "item": "表情 VMD 合并", "status": "done: 41 轨导入，逐字节无损"},
        {"priority": "P1", "item": "道具并入子命令", "status": "done: --prop PMX@BONE，3 道具实测不脱手"},
        {"priority": "P2", "item": "多动作拼接（字节级）", "status": "done: 逐条字节一致；但姿态未对齐，见下条"},
        {"priority": "P0", "item": "多动作拼接的姿态对齐（补键 / slerp 交叉淡化 / 根骨对齐）", "status": "未做——明天的第一件事"},
        {"priority": "P2", "item": "dsh 内 orbit 视窗（未做）"},
    ],
}

snap_path = os.path.join(OUTDIR, "snapshot-%s.json" % STAMP)
with open(snap_path, "w", encoding="utf-8") as fh:
    json.dump(snapshot, fh, ensure_ascii=False, indent=1)

print("报告：%s" % md_path)
print("快照：%s" % snap_path)
print("交付物 %d 项" % len(rows))
