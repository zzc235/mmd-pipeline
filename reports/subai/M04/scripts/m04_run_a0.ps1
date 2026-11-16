# M04 A0 仪器灵敏度正控：一条命令跑完四步
#
#   1) 造 A0 副本（所有刚体 collision_collections 清零；标记写进 scene 属性）
#   2) A240 ：原场景 B_from_blend1.blend，胶囊探针 1..240
#   3) A0240：A0 副本，同一探针、同一基线、同一窗口
#   4) 判档 ：m04_a0_control.py（三档 + 方向；自检 8/8）
#
# 用法（在 E:\dsh pr\woker2 下；本机没有 pwsh 7，用 Windows PowerShell 5.1）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File reports\subai\M04\scripts\m04_run_a0.ps1 -Wait 300
#
# 退出码：0 = 判档成功 / 1 = 锁被占（没跑）/ 3 = 某一步失败 / 4 = 判档不可判或自检失败
#
# 约定：
#   * 源 .blend 只读，A0 写到**新路径**，绝不覆盖
#   * 三次 blend_sha256 必须一致（源两次、副本一次）；不一致即作废
#   * A0 副本**不进任何 wired 闸门**（它读出来是 EMPTY，那是预期）
#
# 本文件必须是 **UTF-8 with BOM**：Windows PowerShell 5.1 对无 BOM 文件按 GBK 读，
# 中文会变乱码、引号配对失效，报 "The string is missing the terminator"（实测踩过）。
# 改动时别让编辑器把 BOM 吃掉。
#
# 关于 Blender 退出码：5.2.2 + mmd_tools 在 --background 跑完后**退出清理阶段**会
# EXCEPTION_ACCESS_VIOLATION，退出码非 0，但 JSON 已经落盘且完整。这里不把它当成功也不
# 当失败：先验产物完整（帧数齐、字段在），完整才继续，并把真实退出码写进 a0_run_steps.json。
# 静默吞掉退出码是不允许的——那等于把「崩溃过」洗成「没崩」。

param([int]$Wait = 0)

# 只用 Continue：Windows PowerShell 5.1 在 EAP=Stop 下会把**子进程 stderr** 变成
# 终止性错误（NativeCommandError），那样 Blender 一句警告就能把整条流水线打断。
# 失败判定一律靠显式的 $LASTEXITCODE 检查。
$ErrorActionPreference = "Continue"
# 中文骨名要经两层进程边界（PowerShell → python / blender），统一钉成 UTF-8，
# 否则 `下擺_0_*` 会在 GBK 控制台上被改写，而 `--bones` 匹配失败会表现成「ROI 0 根」的假绿。
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Blender = "E:\code\Blender\blender-5.2.2-windows-x64\blender.exe"
$Root    = "E:\dsh pr\woker2"
$Src     = "out\subai\M02\blend\B_from_blend1.blend"
$A0      = "out\subai\M04\penetration\A0_collisions_off.blend"
$Pen     = "out\subai\M04\penetration"
$Base    = "reports\subai\M04\baselines\B_from_blend1_roi18_capsule_v1.json"

Set-Location $Root

# 产物完整性：JSON 能解析、帧数齐、关键字段在。崩溃之后还能继续的**唯一**依据。
function Test-CapsuleOutput([string]$Path) {
    if (-not (Test-Path $Path)) { return "missing" }
    try { $d = Get-Content $Path -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return "unparsable" }
    if ($null -eq $d.per_frame) { return "no_per_frame" }
    $n = [int]$d.frames[1] - [int]$d.frames[0] + 1
    if ([int]$d.per_frame.Count -ne $n) { return "per_frame_$([int]$d.per_frame.Count)_of_$n" }
    if ([int]$d.frames_measured -ne $n) { return "frames_measured_$([int]$d.frames_measured)_of_$n" }
    return "complete"
}

function Test-A0Output([string]$Path) {
    if (-not (Test-Path $Path)) { return "missing" }
    try { $d = Get-Content $Path -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return "unparsable" }
    if ([int]$d.bits_still_set_after -ne 0) { return "bits_still_set_$([int]$d.bits_still_set_after)" }
    if ([string]::IsNullOrWhiteSpace($d.a0_sha256)) { return "no_a0_sha256" }
    if (-not $d.must_not_enter_gates) { return "gate_eligible_flag_missing" }
    return "complete"
}

# --- 锁：拿不到就直接走人，不排队、不抢 ---
$LASTEXITCODE = 1
python -m coordination.lock acquire --owner "模块负责2|A2" --note "A0 仪器正控：造副本 + A240 + A0240 + 判档" --wait $Wait
if ($LASTEXITCODE -ne 0) { Write-Host "LOCK BUSY -> 不跑"; exit 1 }

$steps = New-Object System.Collections.ArrayList
$ok = 1
try {
    # 18 根 ROI 骨名：从只读 dump 里取，不手抄
    $LASTEXITCODE = 1
    $Bones = python -c "import json,io;d=json.load(io.open(r'out/subai/M04/penetration/rigid_mask_dump.json',encoding='utf-8'));print(','.join(sorted({r['bone'] for r in d['rows'] if (r['bone'] or '').startswith('下擺_0_')})))"
    Write-Host "ROI bones = $Bones"
    if ([string]::IsNullOrWhiteSpace($Bones)) { Write-Host "STEP0 失败：取不到 ROI 骨名"; exit 3 }

    # --- 1) 造 A0 副本 ---
    Write-Host "=== 1/4 造 A0 副本（碰撞全关）==="
    $log = "$Pen\A0run_step1.log"
    $LASTEXITCODE = 1
    & $Blender -b --python "reports\subai\M04\scripts\m04_make_a0_scene.py" -- `
        --blend $Src --out-blend $A0 --out-json "$Pen\a0_scene.json" *> $log
    $rc1 = $LASTEXITCODE
    Select-String -Path $log -Pattern "\[a0\]" | ForEach-Object { $_.Line }
    if ($rc1 -ne 0) {
        $st = Test-A0Output "$Pen\a0_scene.json"
        Write-Host "STEP1 exit=$rc1  产物=$st"
        if ($st -ne "complete") { Write-Host "STEP1 失败：退出码非 0 且产物不完整"; exit 3 }
        Write-Host "STEP1 说明：崩溃发生在产物落盘之后（见文件头）"
    }
    [void]$steps.Add(@{ step = 1; name = "make_a0"; exit = $rc1; output = (Test-A0Output "$Pen\a0_scene.json") })

    # --- 2) A240 ---
    Write-Host "=== 2/4 A240：原场景 1..240 ==="
    $log = "$Pen\A0run_step2.log"
    $LASTEXITCODE = 1
    & $Blender -b --python "reports\subai\M04\scripts\m04_capsule_probe.py" -- `
        --blend $Src --targets "$Pen\roi_align.json" --bones $Bones `
        --frames 1:240 --roi-label 18_skirt_rigid --baseline $Base `
        --out "$Pen\A240.jsonl" --meta "$Pen\A240.meta.json" *> $log
    $rc2 = $LASTEXITCODE
    Select-String -Path $log -Pattern "\[capsule\]" | ForEach-Object { $_.Line }
    if ($rc2 -ne 0) {
        $st = Test-CapsuleOutput "$Pen\A240.meta.json"
        Write-Host "STEP2 exit=$rc2  产物=$st"
        if ($st -ne "complete") { Write-Host "STEP2 失败：退出码非 0 且产物不完整"; exit 3 }
        Write-Host "STEP2 说明：崩溃发生在产物落盘之后（见文件头）"
    }
    [void]$steps.Add(@{ step = 2; name = "A240"; exit = $rc2; output = (Test-CapsuleOutput "$Pen\A240.meta.json") })

    # --- 3) A0240 ---
    Write-Host "=== 3/4 A0240：碰撞全关副本 1..240 ==="
    $log = "$Pen\A0run_step3.log"
    $LASTEXITCODE = 1
    & $Blender -b --python "reports\subai\M04\scripts\m04_capsule_probe.py" -- `
        --blend $A0 --targets "$Pen\roi_align.json" --bones $Bones `
        --frames 1:240 --roi-label 18_skirt_rigid --baseline $Base `
        --out "$Pen\A0240.jsonl" --meta "$Pen\A0240.meta.json" *> $log
    $rc3 = $LASTEXITCODE
    Select-String -Path $log -Pattern "\[capsule\]" | ForEach-Object { $_.Line }
    if ($rc3 -ne 0) {
        $st = Test-CapsuleOutput "$Pen\A0240.meta.json"
        Write-Host "STEP3 exit=$rc3  产物=$st"
        if ($st -ne "complete") { Write-Host "STEP3 失败：退出码非 0 且产物不完整"; exit 3 }
        Write-Host "STEP3 说明：崩溃发生在产物落盘之后（见文件头）"
    }
    [void]$steps.Add(@{ step = 3; name = "A0240"; exit = $rc3; output = (Test-CapsuleOutput "$Pen\A0240.meta.json") })

    # --- 4) 判档 ---
    Write-Host "=== 4/4 判档 ==="
    $LASTEXITCODE = 1
    python "reports\subai\M04\scripts\m04_a0_control.py" --selftest | Select-Object -Last 1
    if ($LASTEXITCODE -ne 0) { Write-Host "自检失败 -> A0 判定不许引用"; exit 4 }
    $LASTEXITCODE = 1
    python "reports\subai\M04\scripts\m04_a0_control.py" `
        --a "$Pen\A240.meta.json" --a0 "$Pen\A0240.meta.json" --json "$Pen\a0_control.json"
    $rc = $LASTEXITCODE
    Write-Host "a0_control exit=$rc"

    # --- 一致性：源文件前后 sha 必须一致（A0 副本 sha 由 a0_scene.json 记） ---
    $LASTEXITCODE = 1
    python -c "
import hashlib, json, io, sys
def sha(p):
    h = hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda: f.read(1<<20), b''): h.update(b)
    return h.hexdigest()
src = r'$Src'; a0 = r'$A0'
s = sha(src)
doc = json.load(io.open(r'$Pen\a0_scene.json', encoding='utf-8'))
ok = (doc['source_sha256_before'] == s == doc['source_sha256_after']
      and doc['bits_still_set_after'] == 0
      and doc['a0_sha256'] == sha(a0))
print('[consistency] source_sha=%s  a0_sha=%s  ok=%s' % (s[:16], doc['a0_sha256'][:16], ok))
sys.exit(0 if ok else 3)
"
    if ($LASTEXITCODE -ne 0) { Write-Host "一致性失败（源文件被改或位没清干净）"; exit 3 }

    # --- 步骤台账：真实退出码 + 产物状态，一起落盘，不许只留在控制台上 ---
    $LASTEXITCODE = 1
    python -c "
import io, json, sys
steps = json.loads(sys.argv[1])
doc = {
    'what': 'm04_run_a0.ps1 四步台账：真实退出码 + 产物完整性',
    'note': 'Blender 5.2.2 + mmd_tools 在 --background 退出清理阶段会 EXCEPTION_ACCESS_VIOLATION，'
            '退出码非 0 而产物完整。这里如实记录，不折算成 0。',
    'steps': steps,
    'judge_exit': int(sys.argv[2]),
    'all_outputs_complete': all(s['output'] == 'complete' for s in steps),
    'crash_after_output_steps': [s['step'] for s in steps if s['exit'] != 0],
}
io.open(r'$Pen\a0_run_steps.json', 'w', encoding='utf-8', newline='\n').write(
    json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
print('[steps] ' + json.dumps(doc['crash_after_output_steps'], ensure_ascii=False))
" ($steps | ConvertTo-Json -Compress -AsArray) $rc
    if ($LASTEXITCODE -ne 0) { Write-Host "台账落盘失败"; exit 3 }

    $ok = $rc
}
finally {
    $LASTEXITCODE = 1
    python -m coordination.lock release --owner "模块负责2|A2"
}
exit $ok
