# M00 · 最短复现步骤（PowerShell）

> 全部在 A4 工作树 `E:\code\mmdpipe-ai\A4` 执行。不需要 Blender，不需要联网。
> attempt 2 起 `--board` 可省略：缺省落在**主工作树** `E:\dsh pr\woker2\out\subai\coordination\board.db`（四棵树共享一份）。

## 0. 共享板位置（先确认）

```powershell
python -c "import sys;sys.path.insert(0,'.');from coordination import paths;print(paths.board_path())"
# → E:\dsh pr\woker2\out\subai\coordination\board.db
```

覆盖方式：`$env:MMDPIPE_BOARD = "D:\somewhere\board.db"`（测试与离线演示用）。

## 1. 跑测试

```powershell
Set-Location "E:\code\mmdpipe-ai\A4"
python -m unittest tests.test_coordination -v        # 35 条：13 §10 十二条 + H1–H6 + 闸门 6 + 共享路径 2
python -m unittest discover -s tests                 # 全量（本树 140 条 OK，15 skip 为既有 reports 依赖）
```

## 2. 建板 + 派工（共享单实例）

```powershell
python -m coordination.scheduler init
python -m coordination.scheduler add-task --task M01 --module M01 --lane A1 --status ready
python -m coordination.scheduler add-task --task M07 --module M07 --lane A4 --status ready --base <base_commit>
python -m coordination.dispatcher --write
python -m coordination.scheduler status
```

## 3. 格式闸门（files[] 必须覆盖 git diff base..HEAD）

```powershell
git diff --name-only <base>..HEAD        # 闸门用的就是这条命令的结果
python -m coordination.scheduler submit --task M01 --evidence evidence.json
# 缺任一文件 → {"state":"REJECTED","reason_code":"MISSING_EVIDENCE","missing":["..."]}，退出码 2
```

闸门默认用任务行的 `base_commit`；临时覆盖用 `--base <sha> --repo <git路径> --head <ref>`。

## 4. 走完一个任务的完整生命周期（合成证据）

```powershell
python -m coordination.scheduler claim --lane A1 --agent A1
python -m coordination.scheduler start --task M01
python -m coordination.scheduler submit --task M01 --evidence evidence.json
python -m coordination.scheduler verify-begin
python -m coordination.scheduler decide --task M01 --decision ACCEPT_MERGE
python -m coordination.scheduler merge-begin
python -m coordination.scheduler merge-done --task M01 --merge-commit <sha>
```

`evidence.json` 的最小形状（不合规会被拒，`spec` 必须是 `evidence/1`）：

```json
{"spec":"evidence/1","task_id":"M01","attempt":1,"status":"PASS",
 "files":[{"path":"mmdpipe/pmx.py","sha256":"<64 hex>","tracked":true}],
 "tests":[{"cmd":"python -m unittest discover -s tests","exit":0,"passed":12,"failed":0,"skipped":0}],
 "artifacts":[],"known_risks":[]}
```

## 5. 回收过期租约

```powershell
python -m coordination.scheduler reap
```
