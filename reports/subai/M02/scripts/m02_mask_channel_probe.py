"""M02 · S8 前置探头：掩码通道**接没接上**（设计无关，只读场景）。

    blender -b <scene.blend> -P m02_mask_channel_probe.py -- <out.json>

为什么先写这个而不是直接写 A/B 实验：S8 第三层与 S2 重测都假设「刚体之间的碰撞由 PMX 掩码
决定」。如果场景里 324 个刚体的 `collision_collections` 全是同一个位型，那说明掩码还在
`mmd_rigid.collision_group_mask` 里躺着、没接到 Blender 的解算上——这时候跑 A/B 只会量到
「两个一样的场景差 0」，那个 0 会被读成「掩码不影响结果」，正好反过来。

判据（`coordination/mask_channel_spec.md` §4 的单一定义，`D-145`；四条**同时**成立才 WIRED）：
    ① `collision_collections` 出现 ≥2 种位型；
    ② 回读零失败（`mask_read_failures == 0`）；
    ③ 每一对「PMX 掩码说不该碰」的对都被分开 —— 位分开**或**既有约束挡着（两桶都可）；
    ④ `--stage-json`（4号 `stage.stage_mask` 的输出）里 `constraints_capped == false`
       且 `skipped_count == 0`。没给 `--stage-json` ⇒ ④ 判不了，WIRED 不可给。

判词（同 §4 词表）：WIRED / PARTIAL（有理由但没全成立）/ EMPTY（一个位都没设）/ UNWIRED
（位型 <2 且没有分开任何一对，典型「通道没接」）。有理由还硬判 WIRED 是这支仪器今天
被抓住的缺陷（cap 过的场景旧口径会报 WIRED），所以理由非空一律不许 WIRED。

退出码（**判词与闸门分开**，别再一个数两个意思）：
    0  WIRED
    1  判词不是 WIRED，且调用方给了 `--expect wired` ⇒ **闸门不通过**
    2  判词不是 WIRED（PARTIAL / UNWIRED / EMPTY），没要求闸门 ⇒ 这是**读数**，不是失败
    3  CANNOT：读不到 / 参数错 / 脚本异常（`D-135`；Blender 的 0 会吞掉 `-P` 脚本的异常）
"""
import hashlib
import json
import os
import sys
import traceback

import bpy
import addon_utils

PREFIXES = ("000_", "001_", "002_", "003_", "004_", "005_", "006_", "007_", "008_", "009_", "010_")

CANNOT = 3          # 读不到 / 参数错 / 脚本异常。与判词无关，绝不与 EMPTY/PARTIAL 共用数字。


def ensure_mmd():
    """扩展注册的 RNA 属性只有在 enable 之后才存在——读不到 ≠ 不存在（D-0xx）。"""
    for mod in addon_utils.modules():
        if "mmd_tools" in getattr(mod, "__name__", ""):
            addon_utils.enable(mod.__name__, default_set=True, handle_error=None)
            return mod.__name__
    return None


def _sha256(path: str) -> str:
    if not path:
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def mask_bits(mr):
    """`collision_group_mask` 是 16 个布尔（位集合），不是 int —— 直接 int() 会抛，
    然后被 except 吞掉、把「读不到」变成「没有不该互撞的对」（我第一次就是这样得到
    disallowed_pairs=0 的假结论）。所以这里显式按位折算。"""
    value = getattr(mr, "collision_group_mask", None)
    if value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        bits = 0
        for i, flag in enumerate(value):
            if flag:
                bits |= 1 << i
        return bits
    except TypeError:
        return None


def group_id(mr):
    value = getattr(mr, "collision_group_number", None)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


BRANCH_HITS = {"bits": 0, "constraint_preexisting": 0,
               "constraint_added_by_channel": 0, "unseparated": 0,
               "calls": 0}


def bucket_pairs(names, per_body, masks_by_name, groups_by_name, ncc_pairs, ncc_prefix):
    """纯函数：把「PMX 说不该互撞」的刚体对分到三桶。便于 `--selftest` 用合成输入走一遍。

    单位一律是**对**；约束条数不在这里算。

    `BRANCH_HITS` 是**调用计数**（D-127 三问里的「那段代码真被调用了吗」）：
    没有它，一个「改了但没生效」的变异体会让自检照样绿——今天已经出现过一次。
    """
    disallowed = 0
    sep_bits = 0
    sep_pre = 0
    sep_new = 0
    unseparated = []
    BRANCH_HITS["calls"] += 1
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            ia, ib = groups_by_name.get(a), groups_by_name.get(b)
            maska, maskb = masks_by_name.get(a), masks_by_name.get(b)
            if None in (ia, ib, maska, maskb):
                continue
            # PMX: a 的掩码决定它是否与 b 的组互撞（对称检查两边）
            allowed = bool(maska & (1 << ib)) and bool(maskb & (1 << ia))
            if allowed:
                continue
            disallowed += 1
            if not any(x and y for x, y in zip(per_body[a], per_body[b])):
                sep_bits += 1
                BRANCH_HITS["bits"] += 1
                continue
            owner = ncc_pairs.get(frozenset((a, b)))
            if owner is None:
                BRANCH_HITS["unseparated"] += 1
                if len(unseparated) < 10:
                    unseparated.append([a, b])
            elif owner.startswith(ncc_prefix):
                sep_new += 1
                BRANCH_HITS["constraint_added_by_channel"] += 1
            else:
                sep_pre += 1
                BRANCH_HITS["constraint_preexisting"] += 1
    return {
        "disallowed_pairs": disallowed,
        "separated_by_bits": sep_bits,
        "separated_by_constraint_preexisting": sep_pre,
        "separated_by_constraint_added_by_channel": sep_new,
        "unseparated_sample": unseparated,
    }


def selftest():
    """合成输入走一遍纯逻辑。D-xxx 第七条：检查通过 ≠ 行为正确，必须有最小真实路径。

    关键是**三个正控各自能被区分**：位分开 / 预存约束 / 通道新增约束各走一条分支；
    再配一个负控：位相同的对如果没有约束，必须落进 `unseparated` 而不是任何「分开」桶。
    """
    failures = []

    for key in BRANCH_HITS:
        BRANCH_HITS[key] = 0

    seen = [0]

    def check(label, got, want):
        seen[0] += 1
        if got != want:
            failures.append("%s: got %r want %r" % (label, got, want))

    # 位集合折算：16 个布尔 → int；`int([...])` 必须抛（这正是早先版本被吞掉的那个异常）
    check("mask_bits 位折算", mask_bits(type("M", (), {"collision_group_mask": [False] * 8 + [True] + [False] * 7})()), 256)
    check("mask_bits 全假", mask_bits(type("M", (), {"collision_group_mask": [False] * 16})()), 0)
    try:
        int([False] * 16)          # noqa: F841 —— 负控：确认 int(list) 会抛，才说明按位折算是必要的
        failures.append("负控 int(list) 竟然没抛")
    except TypeError:
        pass

    # 掩码 0 ⇒ 谁都不碰。两个刚体位相同 ⇒ 都不该碰，且没有约束 ⇒ 落进 unseparated
    r = bucket_pairs(["A", "B"], {"A": (True, False), "B": (True, False)},
                     {"A": 0, "B": 0}, {"A": 0, "B": 1}, {}, "ncc_mask_")
    check("负控/未分开", (r["disallowed_pairs"], r["separated_by_bits"],
                          len(r["unseparated_sample"])), (1, 0, 1))

    # 正控①：位不同 ⇒ separated_by_bits
    r = bucket_pairs(["A", "B"], {"A": (True, False), "B": (False, True)},
                     {"A": 0, "B": 0}, {"A": 0, "B": 1}, {}, "ncc_mask_")
    check("正控①位分开", (r["disallowed_pairs"], r["separated_by_bits"]), (1, 1))

    # 正控②：位相同，但有**预存**约束 ⇒ preexisting 桶
    r = bucket_pairs(["A", "B"], {"A": (True,), "B": (True,)},
                     {"A": 0, "B": 0}, {"A": 0, "B": 1},
                     {frozenset(("A", "B")): "ncc_0123"}, "ncc_mask_")
    check("正控②预存约束", (r["separated_by_constraint_preexisting"],
                              r["separated_by_constraint_added_by_channel"]), (1, 0))

    # 正控③：位相同，约束名带通道前缀 ⇒ added_by_channel 桶
    r = bucket_pairs(["A", "B"], {"A": (True,), "B": (True,)},
                     {"A": 0, "B": 0}, {"A": 0, "B": 1},
                     {frozenset(("A", "B")): "ncc_mask_0007"}, "ncc_mask_")
    check("正控③通道新增", (r["separated_by_constraint_preexisting"],
                              r["separated_by_constraint_added_by_channel"]), (0, 1))

    # 正控④：PMX 说该碰 ⇒ 不计入 disallowed
    r = bucket_pairs(["A", "B"], {"A": (True,), "B": (True,)},
                     {"A": 1 << 1, "B": 1 << 0}, {"A": 0, "B": 1}, {}, "ncc_mask_")
    check("正控④该碰不计", r["disallowed_pairs"], 0)

    # D-135：Blender 的退出码吞异常，判词只能由脚本自己写 ⇒ 这一层也必须**行为**断言。
    # 「崩了」与「读完了」在调用方看起来一样，这是今天已经被咬过的那类同形。
    check("D-135 正常返 0", _run_guarded(lambda: 0, quiet=True), 0)
    check("D-135 判词透传 2", _run_guarded(lambda: 2, quiet=True), 2)
    check("D-135 异常 ⇒ CANNOT", _run_guarded(_boom, quiet=True), CANNOT)
    check("D-135 SystemExit(0) 透传", _run_guarded(_exit0, quiet=True), 0)

    # 产物完整性：调用方按「文件完整」判成功（退出码两个方向都不可信），
    # 所以原子写这一层也要有行为断言，而不是「用了 os.replace 就当然对」。
    import shutil
    import tempfile
    tmp_dir = tempfile.mkdtemp(prefix="m02probe_")
    try:
        outp = os.path.join(tmp_dir, "r.json")
        write_report(outp, json.dumps({"output_complete": True}) + "\n")
        check("原子写后可解析", json.load(open(outp, encoding="utf-8"))["output_complete"], True)
        check("无残留 .tmp", os.path.exists(outp + ".tmp"), False)
        write_report(outp, json.dumps({"output_complete": True, "n": 2}) + "\n")
        check("覆盖写生效", json.load(open(outp, encoding="utf-8"))["n"], 2)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 调用计数：「那段代码真被调用了吗」。四条分支都必须真的走到过，
    # 否则一个「改了但没生效」的变异体会让上面所有断言看起来仍成立。
    for key in ("bits", "constraint_preexisting", "constraint_added_by_channel", "unseparated"):
        if BRANCH_HITS[key] == 0:
            failures.append("分支 %s 一次都没走到（BRANCH_HITS=%r）" % (key, dict(BRANCH_HITS)))
    if BRANCH_HITS["calls"] == 0:
        failures.append("bucket_pairs 一次都没被调用")

    for line in failures:
        print("SELFTEST FAIL", line)
    print("SELFTEST %s  cases=%d failures=%d branch_hits=%r"
          % ("PASS" if not failures else "FAIL", seen[0], len(failures), dict(BRANCH_HITS)))
    return 0 if not failures else 1


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--selftest" in argv:
        return selftest()
    expect = None
    stage_json = None
    positional = []
    i = 0
    while i < len(argv):
        if argv[i] == "--expect" and i + 1 < len(argv):
            expect = argv[i + 1].strip().lower()
            i += 2
            continue
        if argv[i] == "--stage-json" and i + 1 < len(argv):
            stage_json = argv[i + 1]
            i += 2
            continue
        positional.append(argv[i])
        i += 1
    out_path = positional[0] if positional else None
    if expect not in (None, "wired"):
        print("--expect 只接受 wired（收到 %r）⇒ CANNOT" % (expect,), file=sys.stderr)
        return CANNOT

    addon = ensure_mmd()
    rigids = [ob for ob in bpy.data.objects
              if getattr(ob, "rigid_body", None) is not None]
    # `rigid_body is not None` 与 `mmd_type == "RIGID_BODY"` 是不是同一个集合？
    # `mmdpipe/stage.py` 的 `rigid_bodies()` 用后者，历史脚本用前者；不预设一致——
    # 差值非 0 时必须先知道差的是哪些对象，否则「324 个刚体」这句话指的是哪一批都说不清。
    by_mmd_type = {ob.name for ob in bpy.data.objects
                   if getattr(ob, "mmd_type", None) == "RIGID_BODY"}
    by_rb = {ob.name for ob in rigids}
    set_diff = {
        "only_by_rigid_body": sorted(by_rb - by_mmd_type)[:10],
        "only_by_mmd_type": sorted(by_mmd_type - by_rb)[:10],
        "count_only_by_rigid_body": len(by_rb - by_mmd_type),
        "count_only_by_mmd_type": len(by_mmd_type - by_rb),
        "same_set": by_rb == by_mmd_type,
    }
    patterns = {}
    per_body = {}
    for ob in rigids:
        cols = tuple(bool(v) for v in ob.rigid_body.collision_collections)
        patterns[cols] = patterns.get(cols, 0) + 1
        per_body[ob.name] = cols

    masks = {}
    groups = {}
    read_failures = []
    for ob in rigids:
        mr = getattr(ob, "mmd_rigid", None)
        if mr is None:
            continue
        bits = mask_bits(mr)
        if bits is None:
            read_failures.append(ob.name)
            continue
        masks[bits] = masks.get(bits, 0) + 1
        gid = group_id(mr)
        groups[gid] = groups.get(gid, 0) + 1

    constraints = {}
    disable_flag = 0
    ncc_pairs = {}
    NCC_PREFIX = "ncc_mask_"      # 4号 的 `_new_constraint_object("ncc_mask_%04d")`
    for ob in bpy.data.objects:
        rbc = getattr(ob, "rigid_body_constraint", None)
        if rbc is None:
            continue
        constraints[getattr(rbc, "type", "?")] = constraints.get(getattr(rbc, "type", "?"), 0) + 1
        # **`DISABLE_COLLISIONS` 不是约束类型，是约束上的一个布尔**
        # （mmd_tools 的 ncc 物体用 `constraint_add(type="GENERIC")` 再置 `disable_collisions=True`）。
        # 按 `rbc.type == "DISABLE_COLLISIONS"` 去数永远是 0 —— 那是本脚本 2026-11-16 早先版本的错，
        # 由此报出的「0 条关碰撞约束」不可引用。这里按布尔数，并顺带收约束对。
        if getattr(rbc, "disable_collisions", False):
            disable_flag += 1
            o1 = getattr(rbc, "object1", None)
            o2 = getattr(rbc, "object2", None)
            if o1 is not None and o2 is not None:
                ncc_pairs[frozenset((o1.name, o2.name))] = ob.name

    # 「按掩码不该互撞」的刚体对：分桶——位分开 / 约束分开（预存 / 通道新增）/ 都没分
    masks_by_name = {}
    groups_by_name = {}
    for ob in rigids:
        mr = getattr(ob, "mmd_rigid", None)
        if mr is None:
            continue
        masks_by_name[ob.name] = mask_bits(mr)
        groups_by_name[ob.name] = group_id(mr)

    buckets = bucket_pairs(sorted(per_body), per_body, masks_by_name,
                           groups_by_name, ncc_pairs, NCC_PREFIX)
    disallowed_pairs = buckets["disallowed_pairs"]
    sep_bits = buckets["separated_by_bits"]
    sep_ncc_pre = buckets["separated_by_constraint_preexisting"]
    sep_ncc_new = buckets["separated_by_constraint_added_by_channel"]
    unseparated = buckets["unseparated_sample"]
    sep_ncc = sep_ncc_pre + sep_ncc_new
    separated_pairs = sep_bits + sep_ncc
    # 验收行 1c：两桶 + 约束分开（预存 ∪ 新增）必须可加总对上「PMX 说不该互撞」的总数
    fully_covered = separated_pairs == disallowed_pairs
    # D-3xx：`patterns >= 2` 单独不构成 WIRED —— 位型存在不等于分得对，
    # 还要回读零误差，且位型种类数与 PMX 的组号种数对得上。
    # ---- 判词：与 `coordination/mask_channel_spec.md` §4 同一套（D-20261116-145）----
    # WIRED 四条缺一不可：①位型 ≥2 ②回读零失败 ③每一对「PMX 不该碰」都被分开（位或约束）
    # ④无 cap、无 skipped。第 ④ 条只能从 `stage_mask()` 的返回里读，所以必须给 `--stage-json`；
    # 不给就**不许判 WIRED**——「不知道有没有被截断」和「没被截断」不能同形。
    stage = {}
    if stage_json:
        with open(stage_json, encoding="utf-8-sig") as fh:
            stage = json.load(fh)
    capped = stage.get("constraints_capped")
    skipped_n = stage.get("skipped_count")
    reasons = []
    if len(patterns) < 2:
        reasons.append("位型只有 %d 种（掩码没进碰撞位）" % len(patterns))
    if read_failures:
        reasons.append("掩码读取失败 %d 个刚体" % len(read_failures))
    if not fully_covered:
        reasons.append("仍有 %d 对「PMX 不该碰」没有分开（位+约束）"
                       % (disallowed_pairs - separated_pairs))
    if not stage_json:
        reasons.append("未提供 --stage-json：cap / skipped 未知，按判据不能判 WIRED")
    else:
        if capped is not False:
            reasons.append("constraints_capped=%r（通道被截断）" % (capped,))
        if skipped_n != 0:
            reasons.append("skipped_count=%r（有东西被跳过）" % (skipped_n,))
    if not rigids:
        verdict = "EMPTY"
        reasons = ["场景里没有刚体（不是「通道接好了」，是没东西可接）"]
    elif len(patterns) < 2:
        verdict = "UNWIRED"
    elif reasons:
        verdict = "PARTIAL"
    else:
        verdict = "WIRED"
    word = ("%s：%s" % (verdict, "；".join(reasons))) if reasons else \
        "WIRED：位型 ≥2、回读零失败、每一对「PMX 不该碰」都已被分开、无 cap 无 skipped"
    if verdict == "WIRED":
        exit_code = 0
    elif expect == "wired":
        # 判词不是 WIRED 而调用方要闸门 ⇒ 闸门不通过。EMPTY/PARTIAL/UNWIRED 同码，
        # 因为闸门只需要「过 / 不过」；具体是哪一个看 `verdict` 与 `verdict_reasons`。
        exit_code = 1
    else:
        # 没要闸门 ⇒ 这是读数。PARTIAL/UNWIRED/EMPTY 都是「读到了什么」，不是失败。
        exit_code = 2
    report = {
        "task": "M02",
        "stage": "E-s8",
        "probe": "mask_channel",
        "blend": bpy.data.filepath,
        # D-118：数不许漫游。数源绑定**内容**而不是路径——同名的两个文件今天已经出现过一次。
        "blend_sha256": _sha256(bpy.data.filepath),
        # D-136：口径写在数旁边。`.blend` 是二进制，行尾归一化不适用，所以这里是原始字节；
        # 文本件的三数（raw / lf_normalized / crlf）由 `m02_verify_evidence.py` 那侧打印。
        "blend_sha256_basis": "raw_bytes_v1",
        "addon": addon,
        "rigid_objects": len(rigids),
        "rigid_objects_by_mmd_type": len(by_mmd_type),
        "rigid_object_set_diff": set_diff,
        "collection_patterns": [
            {"bits": [i for i, v in enumerate(bits) if v], "count": n}
            for bits, n in sorted(patterns.items(), key=lambda kv: -kv[1])
        ],
        "distinct_patterns": len(patterns),
        "mmd_rigid_objects": sum(1 for ob in rigids if getattr(ob, "mmd_rigid", None) is not None),
        "distinct_group_mask": len(masks),
        "distinct_group_number": len(groups),
        "mask_read_failures": len(read_failures),
        "constraint_types": constraints,
        "disable_collisions_flag_count": disable_flag,
        "ncc_pair_count": len(ncc_pairs),
        "pmx_pairs_not_allowed": disallowed_pairs,
        "separated_by_bits": sep_bits,
        "separated_by_constraint": sep_ncc,
        "separated_by_constraint_preexisting": sep_ncc_pre,
        "separated_by_constraint_added_by_channel": sep_ncc_new,
        "constraint_attribution_basis": "约束所属对象名是否以 `%s` 开头（4号 的命名）；这是命名约定，不是硬标识" % NCC_PREFIX,
        "separated_total": separated_pairs,
        "unseparated_sample": unseparated,
        "buckets_sum_equals_disallowed": fully_covered,
        "expect": expect,
        "stage_json": stage_json,
        "constraints_capped": capped,
        "skipped_count": skipped_n,
        "verdict": verdict,
        "verdict_reasons": reasons,
        "verdict_exit_code": exit_code,
        # 2号 §三.3：读数来源要自报。这支探头**不碰 `frame_set`**、不读任何姿态，
        # 所以缓存回放（`cache_replay`）与它无关；显式写出来，而不是省掉字段——
        # 字段缺失会被读成「读的是缓存」。
        "pose_source": "not_applicable_static_read",
        # 调用方按产物完整性判成功（Blender 退出码两个方向都不可信）：
        # 这个键在 ⇒ 这份 JSON 序列化完整；半截文件不会有它。
        "output_complete": True,
        "note": word,
    }
    text = json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True)
    print(text)
    if out_path:
        write_report(out_path, text + "\n")
    print("VERDICT %s  patterns=%d  disallowed_pairs=%d  separated=%d  exit=%d"
          % (verdict, len(patterns), disallowed_pairs, separated_pairs, exit_code))
    return exit_code


def write_report(path, text):
    """原子写：先 `.tmp` 再 `replace`。

    为什么不是直接 `open(path,"w")`：调用方现在按**产物完整性**判成功（不是按退出码——
    Blender 两条方向都不可信：脚本抛异常仍退出 0，正常跑完退出清理段也能 `0xC0000005`）。
    半截 JSON 一旦落盘，「文件存在」就被读成「跑完了」。`replace` 之后要么旧内容要么新内容。
    """
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _boom():
    raise ValueError("selftest 故意抛")


def _exit3():
    raise SystemExit(3)


def _exit0():
    raise SystemExit(0)


def _run_guarded(fn=None, quiet=False):
    """`D-135`：Blender 的进程退出码**不反映** `-P` 脚本抛没抛异常（实测 raise 之后仍是 0）。
    所以「脚本崩了」和「场景读完了」在调用方眼里一模一样 —— 判词只能由脚本自己写出来。

    正常路径返回 `main()` 的整数判词；`SystemExit` 原样透传；其余一切（含 KeyboardInterrupt，
    因为「中途被杀」不许看起来像成功）都变成 `CANNOT = 3` 并打印 traceback。
    """
    fn = main if fn is None else fn
    try:
        return int(fn())
    except SystemExit as exc:
        code = exc.code
        return 0 if code is None else int(code)
    except BaseException:
        # quiet 只用于自检内部（自检要断言的是退出码，不是这行字）。
        if not quiet:
            traceback.print_exc()
            print("VERDICT CANNOT  exit=%d  （脚本异常，不是读数；D-135）" % CANNOT)
        return CANNOT


if __name__ == "__main__":
    sys.exit(_run_guarded())
