# M07 · 最短复现（PowerShell，A4 树）

> 不需要 Blender 的部分现在就能复现；标 **LOCK** 的必须拿到 `out\subai\locks\blender.lock`。

## 0. 位置

```powershell
Set-Location "E:\code\mmdpipe-ai\A4"      # 分支 ai/a4
git log --oneline -4                       # 066d520 / 571483b / a5513bf / fc48f63
```

## 1. 纯 Python 部分（无需锁）

```powershell
python -m unittest discover -s tests            # 期望 Ran 228 tests, OK (skipped=15)
python -m unittest tests.test_coordination      # 37
python tests_bpy/test_status.py                 # 18（状态层：路径/进度/失败原因/报告行）
python tests_bpy/test_zones.py                  # 6 （四区分区）
python -c "import build_addon as b; print(b.read_version()); b.stage()"   # 1.3.0 / 42 文件
```

## 2. 覆盖闸门自检（提交前必跑）

```powershell
git diff --name-only main...HEAD                 # 三点式：只算本分支带来的差异
python -c "import sys;sys.path.insert(0,'.');from coordination import gate;print(gate.check_coverage([{'path':'addon/mmd_pipeline/status.py'}],'main'))"
# 缺文件会抛 CoverageError 并列出 missing[]
```

## 3. **LOCK** 打包与校验

```powershell
New-Item -ItemType Directory -Path "E:\dsh pr\woker2\out\subai\locks\blender.lock" -ErrorAction Stop | Out-Null
python "build_addon.py"                          # 校验失败返回 2 且不产物；成功打印 PACKAGE + SHA256
```

## 4. **LOCK** 隔离安装 + smoke（不动用户全局配置）

```powershell
$env:BLENDER_USER_SCRIPTS = "$env:TEMP\m07_scripts"      # 隔离脚本目录
& "E:\code\Blender\blender-5.2.2-windows-x64\blender.exe" --factory-startup -b `
  --command extension install-file -r user_default -e "dist\mmd_pipeline-1.3.0.zip"
& "E:\code\Blender\blender-5.2.2-windows-x64\blender.exe" --factory-startup -b `
  -P "E:\code\mmdpipe-ai\A4\tests_bpy\smoke.py"          # 期望 SMOKE RESULT OK (0 failed)
```

> 写用户全局配置目录那一步**未获批准，不做**（11 §9 要 D0 + Owner 双批准）。

## 5. **LOCK** 12 帧端到端

```powershell
& "E:\code\Blender\blender-5.2.2-windows-x64\blender.exe" -b -P "run_pipeline.py" -- `
  --pmx "<模型.pmx>" --vmd "<动作.vmd>" --out "$env:TEMP\m07_e2e" --frames 12 --layout isolated
python "addon\mmd_pipeline\status.py" "$env:TEMP\m07_e2e"   # 状态/阶段/帧数/落点
& "C:\Users\zzc\ffmpeg\bin\ffprobe.exe" -v error -count_frames -select_streams v:0 `
  -show_entries stream=nb_read_frames,r_frame_rate,duration "$env:TEMP\m07_e2e\final\*\result.mp4"
```
