# M03 · 复现（从干净环境照做）

> 终端：**PowerShell**。仓库根目录 `E:\dsh pr\woker2`。全部命令都是本轮实际执行过的。
> 依赖：Python 3.13（纯标准库）+ Blender 5.2.2（只有第 4/5 步需要）。
> 不需要联网安装任何东西。

## 0. 前置检查

```powershell
Set-Location "E:\dsh pr\woker2"
python --version                       # 期望 Python 3.13.x
Test-Path "E:\code\Blender\blender-5.2.2-windows-x64\blender.exe"   # True
Test-Path "E:\blender模型\没有外套本家模型\星穹铁道—飞霄（无外套）.pmx"  # True
```

## 1. 单元测试（不用 Blender，约 2 秒）

```powershell
python -m unittest tests.test_diagnose -v
```

期望末尾：`Ran 37 tests ... OK`。缺飞霄 PMX 时集成用例自动 skip，其余仍应全绿。

## 2. 静态归因（单个模型）

```powershell
python -m mmdpipe.diagnose --pmx "E:\blender模型\没有外套本家模型\星穹铁道—飞霄（无外套）.pmx" `
    --out "reports\subai\M03\evidence\static\S3.json"
```

期望 stdout：`primary=F3 [suspected]  secondary=F4(suspected), F5(suspected)  fingerprint=...`

## 3. 8 条样本 manifest / 覆盖矩阵 / 汇总

```powershell
python reports/subai/M03/scripts/m03_manifest.py     # 会重跑静态全样本
python reports/subai/M03/scripts/m03_examples.py     # schema 示例 + measurements.json
```

期望 stdout 打印 8 行样本表 + `coverage:` + `summary:`；
覆盖矩阵应仍是 F1/F3/F6 有 confirmed、F4/F5/R0 缺真实确认样本。

## 4. Blender 运行期采集（必须串行，先取锁）

```powershell
# 取锁：目录创建必须原子成功；已存在就说明别人在用，不要抢
$lock = "E:\dsh pr\woker2\out\subai\locks\blender.lock"
New-Item -ItemType Directory -Path (Split-Path $lock) -Force | Out-Null
New-Item -ItemType Directory -Path $lock -ErrorAction Stop | Out-Null
Set-Content -Path (Join-Path $lock "owner.txt") -Value "M03|E:/dsh pr/woker2|<PID>|<时间>|diagnose_blender.py" -Encoding utf8

# 元数据普查（快，约 3 秒；不出动态证据）
& "E:\code\Blender\blender-5.2.2-windows-x64\blender.exe" -b -P "mmdpipe\diagnose_blender.py" -- `
    --blend "E:\code\Blender\feixiao_short\03_shot\physics_test\飞霄_MMD物理_v1.blend" `
    --out "reports\subai\M03\evidence\blend\probe_v1.json" --frames 1

# 60 帧动态（F3 需要 f1 连续步进；已烘焙工程读的是缓存）
& "E:\code\Blender\blender-5.2.2-windows-x64\blender.exe" -b -P "mmdpipe\diagnose_blender.py" -- `
    --blend "E:\code\Blender\feixiao_short\03_shot\physics_test\feixiao_v2_hsr.blend" `
    --pmx "E:\blender模型\没有外套本家模型\星穹铁道—飞霄（无外套）.pmx" `
    --out "reports\subai\M03\evidence\blend\S3_chest_60f.json" --frames 60

# 释放锁（核对 owner.txt 是自己写的再删）
Remove-Item "$lock\owner.txt"; Remove-Item $lock
```

期望：`probe_v1` → `primary=F1 [confirmed]  secondary=F2(confirmed)`；
`S3_chest_60f` → `primary=F4 [suspected]  secondary=F5(suspected), F3(suspected)`。

## 5. S5 袖子（F3 confirmed 的那一次）

```powershell
& "E:\code\Blender\blender-5.2.2-windows-x64\blender.exe" -b -P "mmdpipe\diagnose_blender.py" -- `
    --blend "E:\dsh pr\woker2\kafuka_all\scene.blend" `
    --pmx "E:\blender模型\星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309\星穹铁道—卡芙卡无外套\卡芙卡3.0.pmx" `
    --out "reports\subai\M03\evidence\blend\S5_sleeve_60f.json" --frames 60
```

期望：`primary=F3 [confirmed]  secondary=F2(confirmed), F5(suspected), F4(suspected)`；
JSON 里 `frozen_candidates` 应有 16 条、`rot_delta_deg≈0`、`parent_rot_delta_deg≈66.41`。

## 6. 源文件保护核对

```powershell
Get-FileHash "E:\blender模型\没有外套本家模型\星穹铁道—飞霄（无外套）.pmx" -Algorithm SHA256
# 期望 2DB720A2281A9EA954082FC4D7F42F0D50A6CA72235D345566FBF5A28549A267
```

## 7. 常见坑

| 现象 | 原因 | 处理 |
|---|---|---|
| `primary=INSUFFICIENT_EVIDENCE`，`missing_evidence` 里是 `structure.*` | 只跑 Blender 没给 `--pmx` | 加 `--pmx` 合并静态结构证据 |
| F3 一直 suspected，`missing_evidence` 含 `structure.frozen_root_target_bones` | PMX 冻结根的目标骨在场景里改名/未导入 | 换用与该 PMX 对应的 `.blend` |
| Blender 退出码 4 | `status=partial`（没 rigidbody_world / 没动态帧） | 看 `warnings`，不是崩溃 |
| Blender 结尾没有 "Blender quit" | 采集器写完 JSON 后 `os._exit()`，绕析构段错误 | 正常现象，JSON 已 fsync |
| `frozen_roots` 里 `bone_bound=false` | 焊接的是纯碰撞体（不绑骨） | F3 会过滤掉，不影响判定 |
