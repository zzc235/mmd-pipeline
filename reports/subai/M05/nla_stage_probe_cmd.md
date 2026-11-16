# M05 · NLA 分阶段探针命令（本轮排队，未执行）

> 前置：`out/subai/locks/blender.lock` 不存在，且没有别的 `blender.exe` 在跑。
> 抢锁流程见 `10_并行执行准则` §4；本模块本轮**没有抢锁，也没有删除 M03 的锁**。

## 0. 为什么停在这里

- 21:0–21:2 期间 M01（`m01_shots.py`）与 M03（`diagnose_blender.py`）都在跑 Blender；
  M03 持有锁（owner.txt: `M03|E:/dsh pr/woker2|32316|…`）。
- 本机没有 NLA 坏姿态样本（`out/nla_chain.vmd` 是 11-09 旧产物），也没有 91/151 帧的三段 state。
- 按准则「Blender 忙时不要等待轮询」，本模块先做完纯 Python 部分，状态记 `QUEUED_BLENDER`。

## 1. 抢锁

```powershell
$lock = "E:\dsh pr\woker2\out\subai\locks\blender.lock"
New-Item -ItemType Directory -Path (Split-Path $lock) -Force | Out-Null
New-Item -ItemType Directory -Path $lock -ErrorAction Stop | Out-Null   # 已存在会抛错 = 没抢到
Set-Content -Path (Join-Path $lock "owner.txt") -Value "M05|E:/dsh pr/woker2|$PID|$(Get-Date -Format o)|nla_stage_probe.py" -Encoding utf8
```

## 2. 探针 A：两段 NLA 分阶段世界姿态

```powershell
& "E:\code\Blender\blender-5.2.2-windows-x64\blender.exe" -b --factory-startup `
  -P "E:\dsh pr\woker2\out\subai\M05\nla_stage_probe.py" -- `
  --pmx "E:\blender模型\星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309\星穹铁道—卡芙卡无外套\卡芙卡3.0.pmx" `
  --a "E:\blender模型\原神摇_by_ChildeDuck_c658aa3daba96482861d466e1f1868c7\原神摇\原神摇.vmd" `
  --b "E:\blender模型\活着dj_by_lucky破_923ad74feee8ea23a61ed34b5798a78e\活着dj\活着dj_VMD-TDA.vmd" `
  --gap 6 --align auto `
  --out "E:\dsh pr\woker2\reports\subai\M05\nla_stage_probe_run1.json"
```

判读顺序（**先找第一个偏离的 stage，再改那一层的唯一变量**）：

1. `1_import_a` / `2_import_b`：两段各自导入后，`センター`、`足首.L/R` 在 `a_last`、`b_first` 的值；
   两段本就不同姿态 → 这里**允许有差**，差多少是后面判「是否站位差」的基线。
2. `3_tracks`：track 顺序、strip 的 `frame_start/end`、`action_range`、`extrapolation`；
   若 B 条带没从 `b_first` 开始，先修排布，别动 bake。
3. `4_align`：`align_rep.mode`。`none` 表示按比例判为姿态差（30.53/351.46 → 0.087）。
4. `6_bake`：`bones_with_curves`、`fcurves`、`slots`；同帧世界姿态与 `4_align` 比。
   旧产物里见过「センター 在 A 段尾部写成常数 0」的平台，若 `6_bake` 复现，首错阶段就是 bake。
5. 导出→重导入：用 `chain_nla.concat_via_nla(..., out=...)` 导出后再 `import_vmd`，同帧比。

## 3. 探针 B：两段 NLA 导出产物 vs splice 对照

```powershell
& "E:\code\Blender\blender-5.2.2-windows-x64\blender.exe" -b --factory-startup `
  -P "E:\dsh pr\woker2\out\subai\M05\chain_nla_standalone.py" -- `
  --pmx "<同一 PMX>" --a "<A>" --b "<B>" --gap 6 --out "E:\dsh pr\woker2\out\subai\M05\nla_2seg_run2.vmd"
```

（`chain_nla.py` 自带 CLI，也可直接 `-P mmdpipe/chain_nla.py`；同一输入两次导出应得到相同
`センター` 曲线，若不同先查 NLA/bake 的非确定性。）

再与 splice 对照：

```powershell
python -m mmdpipe.concatvmd "<A>" "<B>" --out "E:\dsh pr\woker2\out\subai\M05\splice_2seg.vmd" --gap 6
```

两段在交接帧及其后 10 帧的 `センター`/`足首` 差值，用纯 Python 逐帧比较（脚本模板见
`out/subai/M05/ledger.py` 的 `_records_in`），把数值写进 `nla_stage_probe.json`。

## 4. 释放

```powershell
# 只删自己创建、且 owner.txt 里是本模块的锁
Get-Content "$lock\owner.txt"
Remove-Item -Recurse -Force $lock
```

## 5. 预算

两段 NLA 基线最多 2 次；同一层修最多 2 次；总实验最多 3 轮。
12 帧探针最多 2 次，**禁止**用 337 帧全片试错。
