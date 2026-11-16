# M07 · reproduce（attempt 2）

> 全部命令在 A4 工作树 `E:\code\mmdpipe-ai\A4`、HEAD `d059a7f` 上跑过。Blender = `E:\code\Blender\blender-5.2.2-windows-x64\blender.exe`（5.2.2 LTS）。
> 凡是开 Blender 的命令，都在锁 `E:\dsh pr\woker2\out\subai\locks\blender.lock` 内跑（`New-Item -ItemType Directory` 原子取锁，跑完删目录）。

## 0. 纯 Python（不需要锁）

```powershell
cd E:\code\mmdpipe-ai\A4
python -m unittest discover -s tests -t tests -p "test_*.py"   # 242 passed / 0 failed / 15 skipped, 16.4 s
```

## 1. D 段：validate + build

```powershell
python E:\code\mmdpipe-ai\A4\build_addon.py
# → Success parsing TOML / 暂存 42 个文件 / created …\dist\mmd_pipeline-1.3.0.zip, 144742
# → SHA256 981ce1a38229ab2878bb087c9e7b6c9f8aa1700ce5b0d09fb8f501f3d5a7d21f
```

拒绝例（**必须喂一个应当被拒的输入**）：

```powershell
$bad = "$env:TEMP\m07_bad_stage2"
Copy-Item -Recurse E:\code\mmdpipe-ai\A4\build\mmd_pipeline $bad
$mf = Join-Path $bad "blender_manifest.toml"
(Get-Content $mf -Raw) -replace 'version = "1\.3\.0"', 'version = "1.3.0' | Set-Content $mf -Encoding utf8
& "E:\code\Blender\blender-5.2.2-windows-x64\blender.exe" -b --command extension validate $bad
# → exit 1，"Invalid statement (at line 1, column 1)"，目录里没有 zip
```

包内条目与 HEAD 一一比对（纯 Python，不需要锁）：

```python
import zipfile, hashlib, os
root = r"E:\code\mmdpipe-ai\A4"
z = zipfile.ZipFile(os.path.join(root, "dist", "mmd_pipeline-1.3.0.zip"))
for n in z.namelist():
    if n.endswith("/"):
        continue
    src = os.path.join(root, n) if (n.startswith("mmdpipe/") or n.startswith("presets/")) else \
          os.path.join(root, "run_pipeline.py") if n == "run_pipeline.py" else \
          os.path.join(root, "addon", "mmd_pipeline", n)
    assert hashlib.sha256(z.read(n)).hexdigest() == hashlib.sha256(open(src, "rb").read()).hexdigest(), n
print("42/42 equal to HEAD")
```

## 2. E 段：真隔离安装 + smoke

```powershell
$env:BLENDER_USER_EXTENSIONS = "$env:TEMP\m07_ext"     # 注意：不是 BLENDER_USER_SCRIPTS
blender --factory-startup -b --python-expr "import bpy;print(bpy.utils.user_resource('EXTENSIONS'))"
blender --factory-startup -b --command extension install-file -r user_default --no-prefs <zip>
blender --factory-startup -b -P tests_bpy/smoke.py
```

- 不带 `-e`（`-e` 会触发 `blender_preferences_write()` 写 `userpref.blend`）；`--no-prefs` 兜底；
- 反证隔离成功：安装前后 `%APPDATA%\…\user_default\mmd_pipeline\run_pipeline.py` 的 `sha256` 与 `userpref.blend` 的 mtime 都不变。

`:smoke` 期望输出 8 行 `PASS` + `SMOKE RESULT OK (0 failed)`。

## 3. F 段：12 帧 E2E（新建工程）

输入（只读，首尾各算一次 sha256）：

- PMX `E:\blender模型\星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309\星穹铁道—卡芙卡无外套\卡芙卡3.0.pmx`（`287a5556…`）
- VMD `E:\blender模型\原神摇_by_ChildeDuck_c658aa3daba96482861d466e1f1868c7\原神摇\原神摇.vmd`（`a2e5f978…`）

```powershell
blender -b -P tests_bpy/run_e2e.py -- `
  --pmx <PMX> --vmd <VMD> --out "$env:TEMP\m07_e2e4" --frames 12 --layout isolated `
  --preset presets\kafuka_hsr_look.json
# → E2E_SCAFFOLD mmd_tools 已在本会话启用（不写偏好），import_model=True
# → 15 行 [PASS]，PIPELINE_EXIT=0，exit 0，约 16 s
python addon\mmd_pipeline\status.py "$env:TEMP\m07_e2e4"
ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames,r_frame_rate,duration,width,height -of default=noprint_wrappers=1 <out>\final\<run>\result.mp4
# → 720x576 / 30:1 / 0.4 s / 12 帧
```

**为什么需要 `tests_bpy/run_e2e.py`**：本机 `bl_ext.user_default.mmd_tools` 已安装但未启用，`wheels/opencc*.whl` 未解包 ⇒ 直接 import 报 `No module named 'opencc'` ⇒ `bpy.ops.mmd_tools.import_model` 不存在 ⇒ `S2_import` 失败。脚手架只做 `addon_utils.enable(..., default_set=False, persistent=False)`，**不写偏好**。

跑**包内**那份入口（更强的主张：装好的包里那份也能跑）：

```powershell
# 1) 把包装进临时仓库（§2），拿到 $pkg = "$env:TEMP\m07_ext\user_default\mmd_pipeline"
# 2) 去掉 BLENDER_USER_EXTENSIONS（否则临时仓库遮住真实 repo，mmd_tools 不可见 ⇒ S2_import exit 2）
Remove-Item Env:\BLENDER_USER_EXTENSIONS
# 3) 用只做"会话内启用 mmd_tools"的包装器 exec 包内 run_pipeline.py：
@"
import addon_utils
addon_utils.enable('bl_ext.user_default.mmd_tools', default_set=False, persistent=False)
entry = r'$pkg\run_pipeline.py'
with open(entry, 'r', encoding='utf-8') as fh:
    src = fh.read()
exec(compile(src, entry, 'exec'), {'__name__': '__main__', '__file__': entry})
"@ | Set-Content "$env:TEMP\m07_pkg_entry.py" -Encoding utf8
blender -b -P "$env:TEMP\m07_pkg_entry.py" -- --pmx <PMX> --vmd <VMD> --out "$env:TEMP\m07_pkg_e2e2" --frames 12 --layout isolated --preset presets\kafuka_hsr_look.json
```

## 4. 受控失败（**判据必须是进程退出码，不是日志**）

```powershell
blender -b -P run_pipeline.py -- --pmx <PMX> --vmd "X:\nope\missing.vmd" --out "$env:TEMP\m07_fail3" --frames 12 --layout isolated
# → 读不到输入文件 … / PIPELINE_EXIT=1 / 进程 exit 1
# → "$env:TEMP\m07_fail3\final" 不存在；pipeline_state.json 不存在
```

## 5. 已知不可复现的部分

同一入口跑两次，PNG 清单摘要与 mp4 字节都不同（`f05f2d94…` vs `2a8dbff6…`；27600 B vs 27675 B）。
**这不是失败**，是渲染有随机成分。回归请比：阶段序列、`[PASS]` 集合、帧数 12、`720×576`、`30/1`、`0.4 s`、`S8_verify` 判据结论。
