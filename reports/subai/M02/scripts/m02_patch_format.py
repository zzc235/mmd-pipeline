# -*- coding: utf-8 -*-
"""`m08_extra_bodies_patch_v1` 的格式层（纯 Python，可在 Blender 之外自检）。

## 这是什么

`324 − 312 = 12`：交付件里有 12 个刚体（11 个 `$name_j*` 占位 BOX + 1 个 `地面_物理` 凸包）
**不是 PMX 带来的**、也没有任何代码生成它们。总控 18:08 定选 **A：有声明的输入补丁**——
12 个属性**全部从旧件读出**、补丁自带来源与 sha、重建时是一个**具名步骤**、补完要验回来。

本模块只做「格式 + 校验 + 摘要」，不碰 `bpy`：

| 谁 | 用它干什么 |
|---|---|
| `m02_dump_extra_bodies.py --patch-out` | 从旧件读出 12 条，`seal()` 盖 sha 后落盘 |
| `m02_rebuild_scene_v3.py --patch` | `verify()` 校验来源与完整性，逐条 apply，`diff_body()` 验回来 |
| 复核者 | `python m02_patch_format.py --selftest` 看它**会不会红** |

## 契约（不满足就拒绝，绝不编默认值）

- `patch_version` 必须等于 `PATCH_VERSION`；
- `patch_sha256` 必须等于对其余内容做 `canonical()` 后的 sha256；
- `source` 必须带 `blend` / `blend_sha256` / `rigids_total` / `extractor{path,sha256}`；
- `bodies` 必须**恰好**是 `WANT_NAMES` 那 12 条，不许多、不许少、不许重名；
- 每条 body 的 `BODY_FIELDS` / `mesh` / `rigid_body` 必须齐全（缺一个就拒，不做默认）；
- 12 条里 `mmd_rigid` 允许是 `null`（实测这 12 个本来就不是 MMD 刚体，`getattr` 读会抛），
  但**这个键必须存在** —— 「读不到」和「没读过」要能分开。

## 为什么单独一层

抽取在 Blender 里、apply 也在 Blender 里，但「补丁合法吗」不该只能在 Blender 里判——
格式判据能纯 Python 测，就先把它测到会红（`--selftest` 12 条，含 5 个篡改负控）。

退出码：`--selftest` 0 通过 / 1 失败；`--verify <patch>` 0 通过 / 2 拒绝。
"""

import argparse
import hashlib
import io
import json
import sys

PATCH_VERSION = "m08_extra_bodies_patch_v1"

WANT_NAMES = ["$name_j"] + ["$name_j.%03d" % i for i in range(1, 11)] + ["地面_物理"]

SOURCE_FIELDS = ("blend", "blend_sha256", "rigids_total", "extractor",
                 "extractor_sha256", "count_found", "blender")
BODY_FIELDS = ("name", "name_stripped", "type", "mmd_type", "parent", "parent_type",
               "parent_bone", "matrix_world", "matrix_parent_inverse", "location",
               "rotation_mode", "rotation_quaternion", "scale", "dimensions",
               "mesh", "rigid_body", "mmd_rigid")
MESH_FIELDS = ("vertices", "faces")
RB_FIELDS = ("mass", "friction", "restitution", "kinematic", "collision_shape",
             "collision_collections", "collision_margin", "linear_damping",
             "angular_damping", "use_margin", "enabled")
TOL = 1e-6


class PatchError(Exception):
    """补丁不合法。`reason_code` 是要写进报告的机器可读原因。"""

    def __init__(self, reason_code, message, problems=None):
        Exception.__init__(self, "[%s] %s" % (reason_code, message))
        self.reason_code = reason_code
        self.message = message
        self.problems = list(problems or [])


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def strip_prefix(name):
    """交付件的对象名带 `NNN_` 前缀（`000_$name_j`）；**只此一份实现**，`m02_patch_bpy` 直接复用。"""
    if len(name) > 4 and name[:3].isdigit() and name[3] == "_":
        return name[4:]
    return name


def compute_patch_sha(patch):
    """对「除 `patch_sha256` 以外的全部内容」做 sha256（所以它是自洽的，不可单方面改）。"""
    body = {k: v for k, v in patch.items() if k != "patch_sha256"}
    return hashlib.sha256(PATCH_VERSION.encode("ascii") + b"\n" + canonical(body)).hexdigest()


def seal(patch):
    """盖 sha（就地写并返回）。"""
    patch = dict(patch)
    patch["patch_version"] = PATCH_VERSION
    patch.pop("patch_sha256", None)
    patch["patch_sha256"] = compute_patch_sha(patch)
    return patch


def _check_float_list(value, n, label, problems):
    if not isinstance(value, list) or len(value) != n:
        problems.append("%s 需要 %d 个数的列表，实际 %r" % (label, n, type(value).__name__))
        return
    for v in value:
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            problems.append("%s 里有非数字 %r" % (label, v))
            return


def _check_body(body, problems):
    missing = [f for f in BODY_FIELDS if f not in body]
    if missing:
        problems.append("body %r 缺字段 %r" % (body.get("name"), missing))
        return
    for key, n in (("matrix_world", 16), ("matrix_parent_inverse", 16),
                   ("location", 3), ("rotation_quaternion", 4), ("scale", 3),
                   ("dimensions", 3)):
        _check_float_list(body.get(key), n, "%s.%s" % (body.get("name"), key), problems)
    mesh = body.get("mesh")
    if not isinstance(mesh, dict):
        problems.append("body %r 的 mesh 不是对象" % (body.get("name"),))
    else:
        miss = [f for f in MESH_FIELDS if f not in mesh]
        if miss:
            problems.append("body %r 的 mesh 缺 %r" % (body.get("name"), miss))
        else:
            if not isinstance(mesh["vertices"], list) or not mesh["vertices"]:
                problems.append("body %r 的 mesh.vertices 空" % (body.get("name"),))
            if not isinstance(mesh["faces"], list) or not mesh["faces"]:
                problems.append("body %r 的 mesh.faces 空" % (body.get("name"),))
    rb = body.get("rigid_body")
    if not isinstance(rb, dict):
        problems.append("body %r 的 rigid_body 不是对象" % (body.get("name"),))
    else:
        miss = [f for f in RB_FIELDS if f not in rb]
        if miss:
            problems.append("body %r 的 rigid_body 缺 %r" % (body.get("name"), miss))
        else:
            coll = rb.get("collision_collections")
            if not isinstance(coll, list) or len(coll) != 20:
                problems.append("body %r 的 collision_collections 需要 20 项" % (body.get("name"),))
    if "mmd_rigid" not in body:
        problems.append("body %r 缺 mmd_rigid 键（读不到也要写 null）" % (body.get("name"),))


def verify(patch, want_names=None):
    """校验补丁，返回 `(bodies_by_name, warnings)`；不合法则抛 `PatchError`。"""
    want_names = list(want_names or WANT_NAMES)
    problems = []
    warnings = []
    if not isinstance(patch, dict):
        raise PatchError("PATCH_NOT_OBJECT", "补丁不是 JSON 对象")
    if patch.get("patch_version") != PATCH_VERSION:
        raise PatchError("PATCH_VERSION_MISMATCH",
                         "patch_version=%r，本模块只认 %r"
                         % (patch.get("patch_version"), PATCH_VERSION))
    expect = patch.get("patch_sha256")
    if not expect:
        raise PatchError("PATCH_SHA_MISSING", "补丁没有 patch_sha256")
    got = compute_patch_sha(patch)
    if got != expect:
        raise PatchError("PATCH_SHA_MISMATCH",
                         "patch_sha256 对不上：补丁写的是 %s，现算是 %s（补丁被改过或来源不明）"
                         % (expect, got))

    src = patch.get("source")
    if not isinstance(src, dict):
        raise PatchError("PATCH_SOURCE_MISSING", "补丁没有 source 段")
    miss = [f for f in SOURCE_FIELDS if f not in src]
    if miss:
        raise PatchError("PATCH_SOURCE_INCOMPLETE", "source 缺字段 %r" % (miss,))
    ext = src.get("extractor")
    if not isinstance(ext, dict) or not ext.get("path") or not ext.get("sha256"):
        raise PatchError("PATCH_EXTRACTOR_MISSING",
                         "source.extractor 必须带 path 与 sha256（抽取脚本要能追到）")

    bodies = patch.get("bodies")
    if not isinstance(bodies, list):
        raise PatchError("PATCH_BODIES_NOT_LIST", "bodies 不是列表")
    names = [b.get("name") for b in bodies if isinstance(b, dict)]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        problems.append("重名：%r" % (dup,))
    stripped = sorted(b.get("name_stripped") for b in bodies if isinstance(b, dict))
    # 清单比的是**去前缀**后的名字（交付件里是 `000_$name_j`，清单里是 `$name_j`）
    extra = sorted(set(stripped) - set(want_names))
    absent = [n for n in want_names if n not in stripped]
    if absent:
        problems.append("补丁缺这 %d 条：%r" % (len(absent), absent))
    if extra:
        warnings.append("补丁里有清单外的对象名：%r（按 name_stripped 判，交由调用方决定）"
                        % (extra,))
    for b in bodies:
        if not isinstance(b, dict):
            continue
        n, s = b.get("name"), b.get("name_stripped")
        if isinstance(n, str) and isinstance(s, str) and strip_prefix(n) != s:
            problems.append("name %r 与 name_stripped %r 不自洽" % (n, s))
    for b in bodies:
        if isinstance(b, dict):
            _check_body(b, problems)
        else:
            problems.append("bodies 里混进非对象：%r" % (type(b).__name__,))
    if problems:
        raise PatchError("PATCH_INVALID", "补丁不合法：%s" % "；".join(problems[:6]), problems)

    by_name = {}
    for b in bodies:
        by_name[b["name"]] = b
        by_name.setdefault(b["name_stripped"], b)
    return by_name, warnings


def load(path, want_names=None):
    """从文件读并校验；文件不存在/不是 JSON 都抛 `PatchError`。"""
    try:
        with io.open(path, encoding="utf-8-sig") as fh:
            patch = json.load(fh)
    except FileNotFoundError:
        raise PatchError("PATCH_NOT_FOUND", "补丁文件不存在：%s" % path)
    except ValueError as exc:
        raise PatchError("PATCH_NOT_JSON", "补丁不是合法 JSON：%s（%s）" % (path, exc))
    by_name, warnings = verify(patch, want_names=want_names)
    return patch, by_name, warnings


def _num_close(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= TOL
    return a == b


# 硬字段：物理/身份相关，必须逐条一致，不一致就停。
STRICT_BODY_FIELDS = ("name", "name_stripped", "type", "mmd_type", "parent", "parent_type",
                      "parent_bone", "matrix_world", "mesh", "rigid_body", "mmd_rigid")
# 软字段：由父级与 matrix_world 派生（`location`/四元数/scale/dimensions 都是同一变换的另一种写法），
# 一致更好，不一致要写进报告并人工看，但不因此判补丁没装上——判定物理等价的是 matrix_world + mesh。
SOFT_BODY_FIELDS = ("matrix_parent_inverse", "location", "rotation_mode",
                    "rotation_quaternion", "scale", "dimensions")


def _quat_close(a, b):
    """q 与 -q 表示同一个旋转，两种写法都算一致。"""
    if not (isinstance(a, list) and isinstance(b, list) and len(a) == len(b) == 4):
        return None
    direct = all(_num_close(x, y) for x, y in zip(a, b))
    flipped = all(_num_close(x, -y) for x, y in zip(a, b))
    return direct or flipped


def diff_value(expected, actual, label, out):
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            out.append("%s：期望对象，实际 %r" % (label, type(actual).__name__))
            return
        for key in expected:
            if key not in actual:
                out.append("%s.%s：实际没有这个键" % (label, key))
                continue
            diff_value(expected[key], actual[key], "%s.%s" % (label, key), out)
        return
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            out.append("%s：期望 %d 项列表，实际 %r"
                       % (label, len(expected), actual if not isinstance(actual, list)
                          else len(actual)))
            return
        for i, (e, a) in enumerate(zip(expected, actual)):
            diff_value(e, a, "%s[%d]" % (label, i), out)
        return
    if not _num_close(expected, actual):
        out.append("%s：期望 %r，实际 %r" % (label, expected, actual))


def diff_body(expected, actual, keys=None):
    """把「补丁里写的」与「场景里读回来的」逐字段比，返回不一致项（空列表 = 一致）。"""
    out = []
    for key in (keys or BODY_FIELDS):
        if key not in expected:
            continue
        if key not in actual:
            out.append("%s：读回来没有这个键" % key)
            continue
        exp, act = expected[key], actual[key]
        if key == "mmd_rigid" and exp is None:
            if act is not None:
                out.append("mmd_rigid：补丁说没有，读回来有 %r" % (act,))
            continue
        if key == "rotation_quaternion":
            same = _quat_close(exp, act)
            if same is not None:
                if not same:
                    out.append("rotation_quaternion：期望 %r，实际 %r" % (exp, act))
                continue
        diff_value(exp, act, key, out)
    return out


def split_diff(expected, actual):
    """返回 `(strict, soft)` 两份不一致清单：strict 非空 = 补丁没真装上。"""
    return (diff_body(expected, actual, STRICT_BODY_FIELDS),
            diff_body(expected, actual, SOFT_BODY_FIELDS))


def _mini_patch():
    bodies = []
    for i, name in enumerate(WANT_NAMES):
        is_ground = name == "地面_物理"
        bodies.append({
            "name": "%03d_%s" % (i, name), "name_stripped": name, "type": "MESH",
            "mmd_type": "NONE" if is_ground else "RIGID_BODY",
            "parent": None if is_ground else "星穹铁道—飞霄（无外套）_arm",
            "parent_type": None if is_ground else "ARMATURE",
            "parent_bone": None if is_ground else "下擺_11_%d" % (7 + i),
            "matrix_world": [1.0] * 16, "matrix_parent_inverse": [0.0] * 16,
            "location": [0.0, 0.0, -0.01] if is_ground else [0.1 * i, 0.2, 0.3],
            "rotation_mode": "QUATERNION", "rotation_quaternion": [1.0, 0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0], "dimensions": [0.1, 0.1, 0.1],
            "mesh": {"vertices": [[-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
                                  [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]],
                     "faces": [[0, 1, 2, 3], [4, 5, 6, 7], [0, 1, 5, 4],
                               [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]},
            "rigid_body": {"mass": 1.0, "friction": 0.5, "restitution": 0.0,
                           "kinematic": not is_ground, "collision_shape": "CONVEX_HULL"
                           if is_ground else "BOX",
                           "collision_collections": [1] + [0] * 19,
                           "collision_margin": 0.04, "linear_damping": 0.04,
                           "angular_damping": 0.1, "use_margin": False, "enabled": True},
            "mmd_rigid": None,
        })
    patch = {"patch_version": PATCH_VERSION, "bodies": bodies,
             "source": {"blend": r"E:\x\B_from_blend1.blend", "blend_sha256": "c" * 64,
                        "rigids_total": 324, "count_found": 12, "blender": "5.2.2",
                        "extractor": {"path": r"E:\x\m02_dump_extra_bodies.py",
                                      "sha256": "d" * 64},
                        "extractor_sha256": "d" * 64}}
    return seal(patch)


def selftest():
    """11 条：2 正控 + 5 篡改负控 + 3 一致性。"""
    cases = []
    good = _mini_patch()
    by_name, warn = verify(good)
    cases.append(("正控：合法补丁通过", True, True))
    cases.append(("正控：12 条都在", len([k for k in by_name if k in WANT_NAMES]), 12))

    def run(mutate, reseal=True, post=None):
        """深拷一份、按要求改、按需重盖 sha（`post` 在重盖**之后**再动，模拟手改落盘文件），
        返回 reason_code 或 'NO_ERROR'。"""
        p = json.loads(json.dumps(good))
        mutate(p)
        if reseal:
            p.update(seal(p))                           # 就地重盖，别丢了改动
        if post is not None:
            post(p)
        try:
            verify(p)
        except PatchError as exc:
            return exc.reason_code
        return "NO_ERROR"

    cases.append(("负控：改一个质量（**不**重盖 sha）",
                  run(lambda p: p["bodies"][0]["rigid_body"].__setitem__("mass", 2.0),
                      reseal=False), "PATCH_SHA_MISMATCH"))
    cases.append(("负控：删一条 body（重盖 sha）",
                  run(lambda p: p["bodies"].pop()), "PATCH_INVALID"))
    cases.append(("负控：删 mesh（重盖 sha）",
                  run(lambda p: p["bodies"][3].pop("mesh")), "PATCH_INVALID"))
    cases.append(("负控：删 source（重盖 sha）",
                  run(lambda p: p.pop("source")), "PATCH_SOURCE_MISSING"))
    cases.append(("负控：换版本串（重盖**之后**改，像手改文件那样）",
                  run(lambda p: None, post=lambda p: p.__setitem__("patch_version", "v0")),
                  "PATCH_VERSION_MISMATCH"))
    cases.append(("负控：mmd_rigid 键整个删掉（重盖 sha）",
                  run(lambda p: p["bodies"][0].pop("mmd_rigid")), "PATCH_INVALID"))
    cases.append(("负控：抽掉 extractor（重盖 sha）",
                  run(lambda p: p["source"].pop("extractor")), "PATCH_SOURCE_INCOMPLETE"))

    # 一致性：改一条物理字段并重盖 sha（补丁仍合法），但 diff_body 必须报出来
    p = json.loads(json.dumps(good))
    p["bodies"][2]["rigid_body"]["kinematic"] = not p["bodies"][2]["rigid_body"]["kinematic"]
    p.update(seal(p))
    b2, _ = verify(p)
    d = diff_body(good["bodies"][2], b2[good["bodies"][2]["name"]])
    cases.append(("一致性：kinematic 翻一位 ⇒ diff 非空", len(d) > 0, True))
    cases.append(("一致性：同一份 ⇒ diff 空", len(diff_body(good["bodies"][2],
                                                          good["bodies"][2])), 0))
    cases.append(("一致性：改过内容 ⇒ 盖出来的 sha 与原补丁不同",
                  p["patch_sha256"] != good["patch_sha256"], True))

    # 硬/软字段分开：派生的变换写法不一致不算「没装上」，物理字段不一致必须算
    body = good["bodies"][5]
    same = json.loads(json.dumps(body))
    same["location"] = [v + 0.5 for v in same["location"]]          # 派生量变了
    strict_d, soft_d = split_diff(body, same)
    cases.append(("分层：只改 location ⇒ strict 空、soft 非空",
                  (len(strict_d), len(soft_d) > 0), (0, True)))
    phys = json.loads(json.dumps(body))
    phys["rigid_body"]["mass"] = body["rigid_body"]["mass"] + 1.0
    strict_d2, _ = split_diff(body, phys)
    cases.append(("分层：改质量 ⇒ strict 非空", len(strict_d2) > 0, True))
    q = json.loads(json.dumps(body))
    q["rotation_quaternion"] = [-v for v in body["rotation_quaternion"]]
    cases.append(("四元数 q 与 -q 视为同一个旋转",
                  len(diff_body(body, q, ("rotation_quaternion",))), 0))

    bad = 0
    for label, got, want in cases:
        ok = got == want
        print("  [%s] %-44s 期望 %r，实际 %r" % ("ok" if ok else "NO", label, want, got))
        bad += 0 if ok else 1
    print("patch 格式自检 %d 条，失败 %d 条" % (len(cases), bad))
    return 0 if bad == 0 else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="m08_extra_bodies_patch_v1 格式层")
    ap.add_argument("--selftest", action="store_true", help="跑格式/篡改自检")
    ap.add_argument("--verify", metavar="PATCH", help="校验一份补丁文件")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.verify:
        ap.error("要么 --selftest，要么 --verify <patch>")
    try:
        patch, by_name, warnings = load(args.verify)
    except PatchError as exc:
        print("拒绝：%s" % exc)
        return 2
    print("OK %s" % args.verify)
    print("  patch_sha256 = %s" % patch["patch_sha256"])
    print("  source.blend = %s" % patch["source"]["blend"])
    print("  source.blend_sha256 = %s" % patch["source"]["blend_sha256"])
    print("  extractor = %s (%s)" % (patch["source"]["extractor"]["path"],
                                     patch["source"]["extractor"]["sha256"]))
    print("  bodies = %d" % len([b for b in patch["bodies"]]))
    for w in warnings:
        print("  ! %s" % w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
