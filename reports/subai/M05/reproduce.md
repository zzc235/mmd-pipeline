# M05 · 复现（PowerShell）

> 全部命令都在 `E:\dsh pr\woker2` 下执行；路径含空格必须加引号。
> 纯 Python 部分不需要 Blender。

## 0. 环境

```powershell
Set-Location "E:\dsh pr\woker2"
python --version        # 实测 3.13.13
python -c "import mmdpipe; print(mmdpipe.__version__)"
```

## 1. 生成 91/91/151 三段夹具（不改源文件）

```powershell
python out/subai/M05/make_fixtures.py
```

期望输出：`seg1_91.vmd [0,90]`、`seg2_91.vmd [0,90]`、`seg3_151.vmd [0,150]`，尾部解析均为 True。

## 2. 基线（旧代码复现 244）

旧代码 = `git stash` 掉 `mmdpipe/vmd.py` 的游标修复：

```powershell
git stash push -- mmdpipe/vmd.py
python -m mmdpipe.concatvmd out/subai/M05/fixtures/seg1_91.vmd out/subai/M05/fixtures/seg2_91.vmd out/subai/M05/fixtures/seg3_151.vmd --out out/subai/M05/chain_baseline_overlap.vmd --gap 2
python out/subai/M05/ledger.py --gap 2 --chain out/subai/M05/chain_baseline_overlap.vmd --out reports/subai/M05/frame_ledger_baseline.json
git stash pop
```

期望（错误态）：

```
seg2 +93 时间轴 93..183
seg3 +93 时间轴 93..243     <- 压在第 2 段上
合计 帧范围 0..243 = 244 帧
!! 时间轴有重叠：[seg2, seg3]
账本：期望 337 / 实际 244 / 未解释缺口 93 / 骨记录守恒 True
```

## 3. 修复后（337）

```powershell
python -m mmdpipe.concatvmd out/subai/M05/fixtures/seg1_91.vmd out/subai/M05/fixtures/seg2_91.vmd out/subai/M05/fixtures/seg3_151.vmd --out out/subai/M05/chain_fixed_337.vmd --gap 2
python out/subai/M05/ledger.py --gap 2 --chain out/subai/M05/chain_fixed_337.vmd --requested-frames 360 --out reports/subai/M05/frame_ledger_final.json
```

期望：`seg3 +186 时间轴 186..336`；合计 0..336 = **337 帧**；无重叠；未解释缺口 0。

## 4. 独立确认（同输入两次位级一致）

```powershell
python -m mmdpipe.concatvmd out/subai/M05/fixtures/seg1_91.vmd out/subai/M05/fixtures/seg2_91.vmd out/subai/M05/fixtures/seg3_151.vmd --out out/subai/M05/chain_fixed_337_b.vmd --gap 2
python -c "import hashlib; a=hashlib.sha256(open(r'out/subai/M05/chain_fixed_337.vmd','rb').read()).hexdigest(); b=hashlib.sha256(open(r'out/subai/M05/chain_fixed_337_b.vmd','rb').read()).hexdigest(); print(a); print(b); print(a==b)"
```

期望两个 sha256 都是 `38b788f7…758f48`，比较为 True。

## 5. 回归

```powershell
python -m unittest tests.test_chain tests.test_vmd tests.test_align tests.test_params tests.test_layout tests.test_statefile -v
```

期望：70 tests OK（新增 14 条在 `tests/test_chain.py`）。

## 6. Blender 部分（本轮未执行，等锁）

```powershell
# 12 帧 splice 探针：验证 state 帧数守恒字段与显式截断记账
& "E:\code\Blender\blender-5.2.2-windows-x64\blender.exe" -b --factory-startup -P "E:\dsh pr\woker2\run_pipeline.py" -- `
  --pmx "E:\blender模型\星穹铁道—卡芙卡无外套_by_崩坏：星穹铁道_31cc0fe7cc29460474ff5e5cd7188309\星穹铁道—卡芙卡无外套\卡芙卡3.0.pmx" `
  --motions "E:\dsh pr\woker2\out\subai\M05\fixtures\seg1_91.vmd;E:\dsh pr\woker2\out\subai\M05\fixtures\seg2_91.vmd;E:\dsh pr\woker2\out\subai\M05\fixtures\seg3_151.vmd" `
  --out "E:\dsh pr\woker2\out\subai\M05\probe12" --frames 12 --chain-mode splice --chain-gap 30
```

期望 `probe12/pipeline_state.json` 的 `stages.S3_chain.metrics`：
`expected_total_frames=393`、`chain_total_frames=393`、`requested_render_frames=12`、
`rendered_frames=12`、`frame_conservation="truncated"`，且 `E-00` 是 WARN 不是 BLOCK。

NLA 两段坏姿态探针见 `reports/subai/M05/nla_stage_probe_cmd.md`。
