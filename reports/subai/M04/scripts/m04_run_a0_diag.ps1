# M04 A0 机制诊断驱动：为什么「碰撞全关」读不出差（只读，不改任何 blend）
#
#   blender -b m04_a0_why_blind.py -- --blend A_from_blend1 --out a0_why_blind_A.json
#   blender -b m04_a0_why_blind.py -- --blend A0_collisions_off --out a0_why_blind_A0.json
#
# 用法（E:\dsh pr\woker2 下，Windows PowerShell 5.1；本文件必须是 UTF-8 with BOM）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File reports\subai\M04\scripts\m04_run_a0_diag.ps1 -Wait 300
#
# 退出码：0 = 两份诊断都完整 / 1 = 锁被占 / 3 = 某一步失败

param([int]$Wait = 0)

$ErrorActionPreference = "Continue"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Blender = "E:\code\Blender\blender-5.2.2-windows-x64\blender.exe"
$Root    = "E:\dsh pr\woker2"
$Src     = "out\subai\M02\blend\B_from_blend1.blend"
$A0      = "out\subai\M04\penetration\A0_collisions_off.blend"
$Pen     = "out\subai\M04\penetration"

Set-Location $Root

$LASTEXITCODE = 1
python -m coordination.lock acquire --owner "模块负责2|A2" --note "A0 机制诊断：为何位清零读不出差（只读）" --wait $Wait
if ($LASTEXITCODE -ne 0) { Write-Host "LOCK BUSY -> 不跑"; exit 1 }

$ok = 0
try {
    $LASTEXITCODE = 1
    $Bones = python -c "import json,io;d=json.load(io.open(r'out/subai/M04/penetration/rigid_mask_dump.json',encoding='utf-8'));print(','.join(sorted({r['bone'] for r in d['rows'] if (r['bone'] or '').startswith('下擺_0_')})))"
    Write-Host "ROI bones = $Bones"
    if ([string]::IsNullOrWhiteSpace($Bones)) { Write-Host "取不到 ROI 骨名"; exit 3 }

    foreach ($case in @(@{ blend = $Src; tag = "A" }, @{ blend = $A0; tag = "A0" })) {
        $log  = "$Pen\a0_why_blind_$($case.tag).log"
        $json = "$Pen\a0_why_blind_$($case.tag).json"
        Write-Host "=== 诊断 $($case.tag)：$($case.blend) ==="
        $LASTEXITCODE = 1
        & $Blender -b --python "reports\subai\M04\scripts\m04_a0_why_blind.py" -- `
            --blend $case.blend --out $json --bones $Bones --frames 1:240 *> $log
        $rc = $LASTEXITCODE
        Select-String -Path $log -Pattern "\[why-blind\]|Traceback" | ForEach-Object { $_.Line }
        if (-not (Test-Path $json)) { Write-Host "诊断 $($case.tag) 没落盘 exit=$rc"; exit 3 }
        if ($rc -ne 0) { Write-Host "诊断 $($case.tag) exit=$rc 但 JSON 已落盘（Blender 退出清理阶段崩溃，见 m04_run_a0.ps1 文件头）" }
    }
    Write-Host "=== 两份诊断产物 ==="
    Get-ChildItem "$Pen\a0_why_blind_*.json" | Select-Object Name,Length | Format-Table -AutoSize
    $ok = 0
}
finally {
    $LASTEXITCODE = 1
    python -m coordination.lock release --owner "模块负责2|A2"
}
exit $ok
