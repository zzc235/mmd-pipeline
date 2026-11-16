# M01 复现（PowerShell）

从干净 checkouts 可照做的最短路径。所有命令都在 `E:\dsh pr\woker2` 下执行。
同一个时刻只跑一个 Blender 任务（物理/渲染串行）。

```powershell
Set-Location "E:\dsh pr\woker2"
$B  = "E:\code\Blender\blender-5.2.2-windows-x64\blender.exe"
$V1 = "E:\flowhmr-test\library\vmd\PERF_Wushu_VoidStep_Once_F.vmd"      # clip1
$V2 = "E:\flowhmr-test\library\vmd\EMO_Sway_Normal_Once_F.vmd"          # clip2（独立确认）
$FX = "E:\blender模型\没有外套本家模型\星穹铁道—飞霄（无外套）.pmx"
$KF = "E:\blender模型\星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309\星穹铁道—卡芙卡无外套\卡芙卡3.0.pmx"
$OUT = "E:\dsh pr\woker2\out\subai\M01"
$PY  = "python"        # 本机 3.13.13；Blender 自带解释器只在 Blender 内用
```

## 0. 阶段 A：只读基线（不写任何模型）

```powershell
$PY reports\subai\M01\scripts\m01_baseline.py
# 期望：BASELINE ok / feixiao rigids=312 joints=389 modes={0: 48, 2: 264} targets_ok=True
#       kafka rigids=145 joints=182 modes={0: 24, 1: 119, 2: 2} / sleeve units=2
# 产物：out\subai\M01\baseline.json, baseline.md
```

## 1. 阶段 B：补丁能力 + 测试

```powershell
$PY -m unittest tests.test_pmx_patch tests.test_physics -v
# 期望：Ran 16 tests ... OK
$PY -m unittest tests.test_pmx_patch tests.test_physics tests.test_params tests.test_vmd `
            tests.test_layout tests.test_align tests.test_statefile
# 期望：Ran 60 tests ... OK（全量回归 1 轮）
```

## 2. 阶段 C：S3 副本 + 三变体对照（clip1）

```powershell
$PY reports\subai\M01\scripts\m01_make_patch.py
# 期望：PATCH ok / diff bytes: 6 / 源 sha256 unchanged: True

& $B -b --factory-startup -P reports\subai\M01\scripts\m01_chest_probe.py -- `
      $FX $V1 baseline "$OUT\probe" --physics 1 --frames 1,15,30,45,60
& $B -b --factory-startup -P reports\subai\M01\scripts\m01_chest_probe.py -- `
      $FX $V1 static   "$OUT\probe" --physics 0 --frames 1,15,30,45,60
& $B -b --factory-startup -P reports\subai\M01\scripts\m01_chest_probe.py -- `
      "$OUT\飞霄_s3_mode0.pmx" $V1 mode0 "$OUT\probe" --physics 1 --frames 1,15,30,45,60

$PY reports\subai\M01\scripts\m01_compare.py "$OUT\probe"
# 期望：mode0_vs_static mean=0.00000；baseline_vs_static mean≈0.227
```

## 3. 阶段 D：独立确认（clip2，换动作不换补丁）

```powershell
foreach ($pair in @(@("baseline",$FX,1), @("static",$FX,0), @("mode0","$OUT\飞霄_s3_mode0.pmx",1))) {
  & $B -b --factory-startup -P reports\subai\M01\scripts\m01_chest_probe.py -- `
        $pair[1] $V2 $pair[0] "$OUT\probe2" --physics $pair[2] --frames 1,20,40,60
}
$PY reports\subai\M01\scripts\m01_compare.py "$OUT\probe2"
# 期望：mode0_vs_static mean=0.00000；baseline_vs_static mean≈0.233（与 clip1 同结论）
```

## 4. 阶段 E：S5 袖筒（基线 vs 静态策略）

```powershell
& $B -b --factory-startup -P reports\subai\M01\scripts\m01_sleeve_probe.py -- `
      $KF $V1 base   "$OUT\sleeve" --policy off    --frames 1,15,30,45,60
& $B -b --factory-startup -P reports\subai\M01\scripts\m01_sleeve_probe.py -- `
      $KF $V1 static "$OUT\sleeve" --policy strict --frames 1,15,30,45,60
# 期望 base  : over45_total=35  global_max≈343.35°  other_global_max=359.258
# 期望 static: muted=48 still=0  over45_total=0  global_max≈12.61°  other_global_max=359.258
```

## 5. 代表帧对比图（静态图，不是序列渲染）

```powershell
# 胸口：clip2 的 f1 / f40，三个变体，中性灰材质（副本换目录会丢贴图，只比形状）
& $B -b --factory-startup -P reports\subai\M01\scripts\m01_shots.py -- `
      $FX $V2 baseline "$OUT\shots_chest3" 1,40 "胸.R" "-0.02,1.15,0.06" 60 1 1
& $B -b --factory-startup -P reports\subai\M01\scripts\m01_shots.py -- `
      $FX $V2 static   "$OUT\shots_chest3" 1,40 "胸.R" "-0.02,1.15,0.06" 60 0 1
& $B -b --factory-startup -P reports\subai\M01\scripts\m01_shots.py -- `
      "$OUT\飞霄_s3_mode0.pmx" $V2 mode0 "$OUT\shots_chest3" 1,40 "胸.R" "-0.02,1.15,0.06" 60 1 1

# 袖筒：clip1 的 f30 / f45，两个变体（同 PMX，保留贴图）
& $B -b --factory-startup -P reports\subai\M01\scripts\m01_shots.py -- `
      $KF $V1 base   "$OUT\shots_sleeve" 30,45 "ひじ.L" "-0.05,1.75,0.10" 45 0 0
& $B -b --factory-startup -P reports\subai\M01\scripts\m01_shots.py -- `
      $KF $V1 static "$OUT\shots_sleeve" 30,45 "ひじ.L" "-0.05,1.75,0.10" 45 1 0

$PY reports\subai\M01\scripts\m01_sheet.py
# 期望：compare_chest.png (1498x988) / compare_sleeve.png (1086x988)
```

## 6. 汇总 + 源文件复核

```powershell
$PY reports\subai\M01\scripts\m01_collect.py
# 期望：feixiao/kafka sha before/after same: True
$PY reports\subai\M01\scripts\m01_collect.py hashes
# 期望：两行 same=True
```

## 已知非阻塞现象

1. `--factory-startup` 下 `bpy.ops.mmd_tools.*` 不在，脚本里必须先
   `addon_utils.enable("bl_ext.user_default.mmd_tools")`。
2. `import_model(types=...)` 若不含 `"PHYSICS"`，`Model.build()` 会**静默**建出 0 个刚体。
3. `import_vmd` 前必须 `root.select_set(True)` + `view_layer.objects.active = root`。
4. 渲染结束退出 Blender 时偶发 `EXCEPTION_ACCESS_VIOLATION`（数据已写盘，属退出阶段崩溃）。
5. 本机可用引擎只有 `BLENDER_EEVEE`（没有 Workbench），需要自行加灯。
