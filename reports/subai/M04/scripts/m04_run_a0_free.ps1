# M04 A0 正控（第二版）：清位 **并且** 清点缓存，位才进解算
#
# 为什么有第二版：第一版只清位，A 与 A0 在 240/240 帧上逐位相同。机制已查
# （`m04_a0_why_blind.py`）：`point_cache.is_baked=true`（frame 1..326、240 帧在内存），
# 探针顺序走帧读的是**已烘焙的旧解算结果**；ROI 18 根骨 0 关键帧、靠 `_arm_rig` 上
# 511 条 pose 约束跟刚体走 ⇒ 不是「骨被键钉死」、也不是「没有解算」。
#
# 本脚本跑三条臂：
#   R_free  : 位不动 + 清缓存  ← 对照臂：证明"重新解算一遍"本身不会凭空改变读数
#   A0_free : 清位   + 清缓存  ← 实验臂：碰撞状态真的变了，探针应当看得见
#   判档两次：① 灵敏度 = R_free vs A0_free（预注册 §二 三档）
#             ② 可重现 = A240（缓存回放）vs R_free（重解）——只看 identical / Δ，
#                方向判据在这一对上不适用（两组不是"开/关碰撞"的关系）
#
# 用法（E:\dsh pr\woker2 下，Windows PowerShell 5.1；本文件必须是 UTF-8 with BOM）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File reports\subai\M04\scripts\m04_run_a0_free.ps1 -Wait 420
#
# 退出码：0 = 两档都判出 / 1 = 锁被占 / 3 = 某一步失败 / 4 = 自检失败

param([int]$Wait = 0)

$ErrorActionPreference = "Continue"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Blender = "E:\code\Blender\blender-5.2.2-windows-x64\blender.exe"
$Root    = "E:\dsh pr\woker2"
$Src     = "out\subai\M02\blend\B_from_blend1.blend"
$Pen     = "out\subai\M04\penetration"
$RFree   = "$Pen\R_free.blend"
$A0Free  = "$Pen\A0_free.blend"
$Base    = "reports\subai\M04\baselines\B_from_blend1_roi18_capsule_v1.json"

Set-Location $Root

function Test-CapsuleOutput([string]$Path) {
    if (-not (Test-Path $Path)) { return "missing" }
    try { $d = Get-Content $Path -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return "unparsable" }
    if ($null -eq $d.per_frame) { return "no_per_frame" }
    $n = [int]$d.frames[1] - [int]$d.frames[0] + 1
    if ([int]$d.per_frame.Count -ne $n) { return "per_frame_$([int]$d.per_frame.Count)_of_$n" }
    if ([int]$d.frames_measured -ne $n) { return "frames_measured_$([int]$d.frames_measured)_of_$n" }
    return "complete"
}

function Test-VariantOutput([string]$Path) {
    if (-not (Test-Path $Path)) { return "missing" }
    try { $d = Get-Content $Path -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return "unparsable" }
    if (-not $d.cache_free_ok) { return "cache_not_freed" }
    if ($d.cache_state_after.is_baked) { return "cache_still_baked" }
    if (-not $d.source_unchanged) { return "source_changed" }
    if (-not $d.bits_readback_ok) { return "bits_readback_bad" }
    return "complete"
}

$LASTEXITCODE = 1
python -m coordination.lock acquire --owner "模块负责2|A2" --note "A0 正控 v2：清位+清缓存，R_free/A0_free 两臂各跑 1..240" --wait $Wait
if ($LASTEXITCODE -ne 0) { Write-Host "LOCK BUSY -> 不跑"; exit 1 }

$rc = @{}
$st = @{}
$ok = 1
try {
    $LASTEXITCODE = 1
    $Bones = python -c "import json,io;d=json.load(io.open(r'out/subai/M04/penetration/rigid_mask_dump.json',encoding='utf-8'));print(','.join(sorted({r['bone'] for r in d['rows'] if (r['bone'] or '').startswith('下擺_0_')})))"
    Write-Host "ROI bones = $Bones"
    if ([string]::IsNullOrWhiteSpace($Bones)) { Write-Host "取不到 ROI 骨名"; exit 3 }

    $mk = "reports\subai\M04\scripts\m04_make_a0_scene.py"
    $pb = "reports\subai\M04\scripts\m04_capsule_probe.py"

    # --- 1) 对照臂 R_free：位不动 + 清缓存 ---
    Write-Host "=== 1/5 造 R_free（位不动 + 清缓存）==="
    $log = "$Pen\A0free_step1.log"
    $LASTEXITCODE = 1
    & $Blender -b --python $mk -- --blend $Src --out-blend $RFree --out-json "$Pen\r_free.json" `
        --keep-bits --free-cache *> $log
    $rc[1] = $LASTEXITCODE
    Select-String -Path $log -Pattern "\[a0\]|Traceback" | ForEach-Object { $_.Line }
    $st[1] = Test-VariantOutput "$Pen\r_free.json"
    if ($st[1] -ne "complete") { Write-Host "STEP1 失败 产物=$($st[1]) exit=$($rc[1])"; exit 3 }
    if ($rc[1] -ne 0) { Write-Host "STEP1 exit=$($rc[1]) 但产物完整（Blender 退出清理阶段崩溃）" }

    # --- 2) 实验臂 A0_free：清位 + 清缓存 ---
    Write-Host "=== 2/5 造 A0_free（清位 + 清缓存）==="
    $log = "$Pen\A0free_step2.log"
    $LASTEXITCODE = 1
    & $Blender -b --python $mk -- --blend $Src --out-blend $A0Free --out-json "$Pen\a0_free.json" `
        --clear-bits --free-cache *> $log
    $rc[2] = $LASTEXITCODE
    Select-String -Path $log -Pattern "\[a0\]|Traceback" | ForEach-Object { $_.Line }
    $st[2] = Test-VariantOutput "$Pen\a0_free.json"
    if ($st[2] -ne "complete") { Write-Host "STEP2 失败 产物=$($st[2]) exit=$($rc[2])"; exit 3 }
    if ($rc[2] -ne 0) { Write-Host "STEP2 exit=$($rc[2]) 但产物完整（Blender 退出清理阶段崩溃）" }

    # --- 3) 探针 R_free ---
    Write-Host "=== 3/5 探针 R_free 1..240（会在走帧时重新解算）==="
    $log = "$Pen\A0free_step3.log"
    $LASTEXITCODE = 1
    & $Blender -b --python $pb -- --blend $RFree --targets "$Pen\roi_align.json" --bones $Bones `
        --frames 1:240 --roi-label 18_skirt_rigid --baseline $Base `
        --out "$Pen\R_free.jsonl" --meta "$Pen\R_free.meta.json" *> $log
    $rc[3] = $LASTEXITCODE
    Select-String -Path $log -Pattern "\[capsule\]" | ForEach-Object { $_.Line }
    $st[3] = Test-CapsuleOutput "$Pen\R_free.meta.json"
    if ($st[3] -ne "complete") { Write-Host "STEP3 失败 产物=$($st[3]) exit=$($rc[3])"; exit 3 }
    if ($rc[3] -ne 0) { Write-Host "STEP3 exit=$($rc[3]) 但产物完整（Blender 退出清理阶段崩溃）" }

    # --- 4) 探针 A0_free ---
    Write-Host "=== 4/5 探针 A0_free 1..240 ==="
    $log = "$Pen\A0free_step4.log"
    $LASTEXITCODE = 1
    & $Blender -b --python $pb -- --blend $A0Free --targets "$Pen\roi_align.json" --bones $Bones `
        --frames 1:240 --roi-label 18_skirt_rigid --baseline $Base `
        --out "$Pen\A0_free.jsonl" --meta "$Pen\A0_free.meta.json" *> $log
    $rc[4] = $LASTEXITCODE
    Select-String -Path $log -Pattern "\[capsule\]" | ForEach-Object { $_.Line }
    $st[4] = Test-CapsuleOutput "$Pen\A0_free.meta.json"
    if ($st[4] -ne "complete") { Write-Host "STEP4 失败 产物=$($st[4]) exit=$($rc[4])"; exit 3 }
    if ($rc[4] -ne 0) { Write-Host "STEP4 exit=$($rc[4]) 但产物完整（Blender 退出清理阶段崩溃）" }

    # --- 5) 判档两次 ---
    Write-Host "=== 5/5 判档 ==="
    $LASTEXITCODE = 1
    python "reports\subai\M04\scripts\m04_a0_control.py" --selftest | Select-Object -Last 1
    if ($LASTEXITCODE -ne 0) { Write-Host "自检失败 -> A0 判定不许引用"; exit 4 }

    Write-Host "--- ① 灵敏度：R_free（位不动）vs A0_free（位全清），两边都是重新解算 ---"
    $LASTEXITCODE = 1
    python "reports\subai\M04\scripts\m04_a0_control.py" `
        --a "$Pen\R_free.meta.json" --a0 "$Pen\A0_free.meta.json" --json "$Pen\a0_free_sensitivity.json"
    $rc[5] = $LASTEXITCODE
    Write-Host "灵敏度判档 exit=$($rc[5])"

    Write-Host "--- ② 可重现：A240（缓存回放）vs R_free（重解），只看 identical / Δ ---"
    $LASTEXITCODE = 1
    python "reports\subai\M04\scripts\m04_a0_control.py" `
        --a "$Pen\A240.meta.json" --a0 "$Pen\R_free.meta.json" --json "$Pen\a0_free_reproducibility.json"
    $rc[6] = $LASTEXITCODE
    Write-Host "可重现判档 exit=$($rc[6])（方向判据在这一对上不适用）"

    $st[5] = if (Test-Path "$Pen\a0_free_sensitivity.json") { "complete" } else { "missing" }
    $st[6] = if (Test-Path "$Pen\a0_free_reproducibility.json") { "complete" } else { "missing" }

    # --- 台账 ---
    $LASTEXITCODE = 1
    python -c "
import io, json, sys
names = ['build_R_free', 'build_A0_free', 'probe_R_free', 'probe_A0_free',
         'judge_sensitivity', 'judge_reproducibility']
v = sys.argv[1:]
n = len(names)
steps = [{'step': i + 1, 'name': names[i], 'exit': int(v[i]), 'output': v[n + i]} for i in range(n)]
doc = {
    'what': 'm04_run_a0_free.ps1 台账：A0 正控 v2（清位 + 清缓存）',
    'note': 'Blender 5.2.2 + mmd_tools 在 --background 退出清理阶段会 EXCEPTION_ACCESS_VIOLATION，'
            '退出码非 0 而产物完整；这里如实记录，不折算成 0。',
    'why_v2': 'v1 只清位不清缓存 ⇒ 240/240 帧逐位相同（见 a0_why_blind_A.json）。',
    'steps': steps,
    'all_outputs_complete': all(s['output'] == 'complete' for s in steps),
    'nonzero_exit_steps': [s['step'] for s in steps if s['exit'] != 0],
}
io.open(r'$Pen\a0_free_run_steps.json', 'w', encoding='utf-8', newline='\n').write(
    json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
print('[steps] nonzero_exit=%s all_complete=%s' % (doc['nonzero_exit_steps'], doc['all_outputs_complete']))
" $rc[1] $rc[2] $rc[3] $rc[4] $rc[5] $rc[6] $st[1] $st[2] $st[3] $st[4] $st[5] $st[6]
    if ($LASTEXITCODE -ne 0) { Write-Host "台账落盘失败"; exit 3 }

    $ok = $rc[5]
}
finally {
    $LASTEXITCODE = 1
    python -m coordination.lock release --owner "模块负责2|A2"
}
exit $ok
