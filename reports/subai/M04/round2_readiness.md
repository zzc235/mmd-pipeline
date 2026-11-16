# C/D 第二轮：准入就绪度（2026-11-16 18:52）

**一句话**：准入四件里三件齐了，**唯一缺的是「324 件上的动作」**，而它在 `M05` accepted 之后不在任何任务里。

本轮判词：`C@W1` / `C@W2` / `D` = **`UNMEASURED`**（不是 `FAIL`）。缺的具名物：**324 交付件上的骨骼动画**（`actions == []`）。

---

## 一、输入件（已冻结，身份可核）

| 项 | 读数 |
|---|---|
| 件 | `A1/out/subai/M08/frozen/delivery_324_ffaa6780.blend` |
| 字节 / sha256 | 6 102 478 / `ffaa6780a2f7e765512201403a21e34848837b5f1c7486e91a70442762857761` |
| 只读 | 真（我独立核过，不采信报告） |
| 刚体 | `u323=323` / `u324=324`，`body_read_errors=[]` |
| 掩码 | `WIRED` / `needed=10111` / `added=8298` / `already=1813` / `readback_mismatch=0` / `capped=False` / `skipped=0` / `verdict_reasons=[]` |
| 缓存 | `is_baked=False` / `is_outdated=True` / `has_physics=True` / `verdict=OK_UNBAKED` |
| 场景 | `fps=24` / `fps_base=1.0` / `frame_start=1` / **`frame_end=250`** |
| 动作 | **`actions=[]` / `active_action=None`** |
| 来源 run | `run_20261116_1847`，`commit_at_freeze=bbcc9ba` |

冻结件旁 `readback_frozen_ffaa6780.json`（206 289 B，`2cc761f1…`）是重新跑过的只读回读：`mask_triple` 现在四个数齐全且逐项等于 `mask_wired_record`，并带 `source` 逐键说明来源。**本报告的读数取自这份回读 + 我对冻结件的直接 sha 核对**，不采信任何口头转述。

## 二、准入四件

| 准入项 | 状态 | 依据 |
|---|---|---|
| ① 掩码通道 `WIRED` 且有数 | **成立** | `mask_wired_record`（10111/8298/1813/0/0） |
| ② 件已冻结、sha 可核 | **成立** | `frozen/delivery_324_ffaa6780.blend` 只读 + sha 逐位一致 |
| ③ `coordination.preflight` = `READY` | **成立** | 见下 §三 |
| ④ 姿态来源 `fresh_solve`（A1 口径） | **不成立** | `actions == []`，只能测静态基线 |

**②是第一次成立**：上一轮（312 件）读数钉的三个 sha 被同路径重跑覆盖，事后只能靠内容层等价补救（`D-202` 封顶 `T2`）。这一轮件先冻结再交，那条补救不需要第二次。

## 三、`preflight` 请求（第二轮，`4ef6f97`）

`reports/subai/M04/preflight_cd_spec_round2.json`：

```
python -m coordination.preflight --spec reports/subai/M04/preflight_cd_spec_round2.json --worktree E:\code\mmdpipe-ai\A2
⇒ READY  M04_CD_measure  EVIDENCE_COMPLETE
   [ok] provenance 2 项在 E:\code\mmdpipe-ai\A2
   [ok] capacity   needs=8298 <= cap=10111
   [ok] skipped    skipped=0
   [ok] lease      本任务不要求租约
   [ok] outputs    目标路径均不存在
```

- `needs=8298`、`cap=10111`：cap 由 `stage.constraint_limit(10111)` **现算**（`guardrail_hit=False`），不查表；
- `_derivation.numbers_source` 记那份回读件的 `bytes` + `sha256_raw` + `sha256_lf_normalized` + **`shape: mask_wired_record`** —— 取数有出处，不是凭记忆；
- **旧那份 `preflight_cd_spec.json`（312 树：`needs=6686 ≤ cap=8499`）不用于本轮**，两棵树的数不许拼。

## 四、缺的那件，以及它现在没有归属

`actions == []` 不是 `1号` 漏做一步：交付构建链里没有「应用动作」这一段（`D-186` 把它派给 `M05`）。`3号` 的 `apply_action` 已落地并在七臂上验过（`M05` accepted），但**「在 324 件上接动作」这项工作随 `M05` accepted 而不在任何任务里**。我已在 `thread:1b4bf99a-1ae6-4c81-aa42-f730a45c0c8a` 请 `3号` 在他回复 `总控` 的 (a)/(b) 取舍时把这条依赖带上去。

**我不会为了能开跑而接受假动作**：假动作会让三臂跑出一整套「看起来有结论」的数；缺动作只让我判 `UNMEASURED`。这两者的代价不对称。

## 五、件到手后怎么跑（一条命令，不占锁不排队）

```
python reports/subai/M04/scripts/m04_run_cd.py \
    --arms-dir <A3 的 324 四臂目录> \
    --input  E:\code\mmdpipe-ai\A1\out\subai\M08\frozen\delivery_324_ffaa6780.blend \
    --out-dir E:\dsh pr\woker2\out\subai\M04\penetration \
    --batch-id round2_324 --freeze
```

顺序与窗口（预注册 `v4+amendA1A3`，**不许改**）：`C@W1` 1..240 → `C@W2` 1..832 → `D` 1..832；基线在无动作输入上建一次、三臂共用；每臂开跑前核输入 sha；产物落 `<out-dir>/round2_324/` 并冻结，收尾 `manifest.json` 逐文件记 `bytes/sha256/lf 归一 sha/只读位`。

## 六、限定（必须与结论同行）

1. **`T2` 封顶**，与上一轮相同的性质：「`T2`，但仪器有效性在同场景自证」；`T3` 的门在契约 B（烘焙 + 行为探针），不在这个窗口。
2. **窗口 `C@W2`/`D` 要求 `frame_end ≥ 832`**。现在 `frame_end=250` 是空场景默认值。若动作末帧 < 832，**不许悄悄拉长场景或缩窗口**——那是改预注册，要 `总控` 裁。
3. 中间保持段（动作末帧 → 832）的深度与动画段不同（上一轮实测差 1.153 mm / 2.9%），分析时分开报，不混算。
4. 本轮准入是**在冻结件上**成立的；换件即重来，不继承任何读数。
