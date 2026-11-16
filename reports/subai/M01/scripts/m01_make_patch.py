"""M01 阶段 C-1：生成飞霄 S3 副本（唯一变量 = 刚体 24–29 的 mode 2→0）并写 manifest。

    python m01_make_patch.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

sys.path.insert(0, r"E:\dsh pr\woker2")

from mmdpipe import pmx  # noqa: E402

SRC = r"E:\blender模型\没有外套本家模型\星穹铁道—飞霄（无外套）.pmx"
OUT_DIR = r"E:\dsh pr\woker2\out\subai\M01"
DST = os.path.join(OUT_DIR, "飞霄_s3_mode0.pmx")
TARGETS = list(range(24, 30))
NEW_MODE = 0


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    before_src = sha256(SRC)
    model = pmx.load(SRC)
    assert model.tail_error is None, model.tail_error
    old = {i: model.rigids[i].mode for i in TARGETS}
    assert set(old.values()) == {2}, "目标不是全 mode2，先停：%s" % old

    patch = {i: NEW_MODE for i in TARGETS}
    pmx.patch_save(model, DST, rigid_mode=patch)
    after_src = sha256(SRC)
    dst_model = pmx.load(DST)

    diffs = [i for i in range(len(model.raw)) if model.raw[i] != dst_model.raw[i]]
    expected = sorted(model.rigid_mode_offsets[i] for i in TARGETS)
    assert diffs == expected, "diff 位置与预期不符：%s" % diffs
    assert len(dst_model.raw) == len(model.raw)
    assert all(dst_model.rigids[i].mode == NEW_MODE for i in TARGETS)
    assert all(dst_model.rigids[i].mode == model.rigids[i].mode
               for i in range(len(model.rigids)) if i not in TARGETS)

    manifest = {
        "source": SRC, "source_sha256_before": before_src,
        "source_sha256_after": after_src, "source_unchanged": before_src == after_src,
        "output": DST, "output_sha256": sha256(DST),
        "bytes_source": len(model.raw), "bytes_output": len(dst_model.raw),
        "patch_kind": "rigid_mode",
        "targets": [{"index": i, "name": model.rigids[i].name,
                     "bone": model.bones[model.rigids[i].bone].name,
                     "old_mode": old[i], "new_mode": NEW_MODE,
                     "byte_offset": model.rigid_mode_offsets[i]}
                    for i in TARGETS],
        "diff_byte_count": len(diffs),
        "diff_offsets": diffs,
        "parse_tail_error": dst_model.tail_error,
        "reparse_ok": dst_model.tail_error is None,
        "non_target_modes_unchanged": True,
        # 给 M02 的接口提示：关节 6 限位/6 弹簧的字节位置由此推出，可直接照抄扩展 patch_save
        "joint_limit_layout": {
            "move_min": "joint_pos_offsets[i] + 24  (3f)",
            "move_max": "joint_pos_offsets[i] + 36  (3f)",
            "rot_min": "joint_pos_offsets[i] + 48  (3f, rad)",
            "rot_max": "joint_pos_offsets[i] + 60  (3f, rad)",
            "spring_move": "joint_pos_offsets[i] + 72  (3f)",
            "spring_rot": "joint_pos_offsets[i] + 78  (3f)",
            "note": "实测布局（飞霄 PMX 逐字节核对过 joint 0/1/2）：限位共 12 个 float 从 +24 起，"
                    "弹簧共 6 个 float 从 +72 起。扩展 patch_save 时沿用 rigid_mode 的做法："
                    "写前回读旧值校验，不一致就拒绝。",
        },
    }
    with open(os.path.join(OUT_DIR, "patch_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)

    print("PATCH ok")
    print("  src  sha256 unchanged:", before_src == after_src)
    print("  dst  sha256:", manifest["output_sha256"])
    print("  bytes:", len(model.raw), "->", len(dst_model.raw), " diff bytes:", len(diffs))
    for t in manifest["targets"]:
        print("  #%d %s %s mode %d->%d @%d"
              % (t["index"], t["name"], t["bone"], t["old_mode"], t["new_mode"], t["byte_offset"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
