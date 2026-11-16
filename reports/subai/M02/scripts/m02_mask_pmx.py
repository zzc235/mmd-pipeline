"""掩码对照：PMX 的 `group`/`mask` 与 Blender 里 `mmd_rigid.collision_group_number` /
`rigid_body.collision_collections` 到底对不对得上。

    python m02_mask_pmx.py <model.pmx> <out.json>          # 纯 Python，不用 Blender
    blender -b -P m02_mask_compare.py -- <blend> <out.json> # 读 Blender 侧
    python m02_mask_pmx.py --join <pmx.json> <blend.json> <out.json>

PMX 语义：`group` = 该刚体所属组（0–15），`mask` = 与哪些组碰撞的位掩码（bit i = 与组 i 碰）。
Blender 语义：`rigid_body.collision_collections` 是**同样语义**的 16 位掩码，`mmd_rigid.collision_group_number`
是所属组。所以两者可以逐位对账。
"""
import json
import os
import re
import sys

PREFIX = re.compile(r"^\d{3}_")


def load_pmx_table(model_path):
    sys.path.insert(0, r"E:\code\mmdpipe-ai\A1")
    from mmdpipe import pmx

    model = pmx.load(model_path)
    rows = {}
    for rigid in model.rigids:
        name = rigid.name
        mask = int(rigid.mask)
        rows[name] = {"pmx_index": int(rigid.index),
                      "bone": rigid.bone,
                      "group": int(rigid.group),
                      "mask_int": mask,
                      "mask_bits": [i for i in range(16) if mask >> i & 1],
                      "shape": rigid.shape, "mode": rigid.mode}
    return {"model": model_path, "count": len(rows), "rows": rows}


def join(pmx_table, blend_table, out_path):
    pmx_rows = pmx_table["rows"]
    blend_rows = blend_table["rows"]
    matched, missing_in_blend, missing_in_pmx = [], [], []
    for name, pr in pmx_rows.items():
        br = None
        for bname, row in blend_rows.items():
            if PREFIX.sub("", bname) == name:
                br = row
                break
        if br is None:
            missing_in_blend.append(name)
            continue
        group_ok = pr["group"] == br["mmd_group"]
        bits_ok = sorted(pr["mask_bits"]) == sorted(br["bits"])
        matched.append({"name": name, "bone": pr["bone"],
                        "pmx_group": pr["group"], "blend_group": br["mmd_group"],
                        "group_ok": group_ok,
                        "pmx_mask_bits": pr["mask_bits"], "blend_bits": br["bits"],
                        "bits_ok": bits_ok,
                        "pmx_mask_int": pr["mask_int"],
                        "blend_mask_int": sum(1 << i for i in br["bits"])})
    for bname in blend_rows:
        if not any(PREFIX.sub("", bname) == n for n in pmx_rows):
            missing_in_pmx.append(bname)
    group_mismatch = [m for m in matched if not m["group_ok"]]
    bits_mismatch = [m for m in matched if not m["bits_ok"]]
    out = {"pmx": pmx_table["model"], "blend": blend_table["blend"],
           "pmx_count": len(pmx_rows), "blend_count": len(blend_rows),
           "matched": len(matched),
           "missing_in_blend": missing_in_blend,
           "missing_in_pmx": missing_in_pmx,
           "group_mismatch": len(group_mismatch),
           "bits_mismatch": len(bits_mismatch),
           "mask_wired": len(bits_mismatch) == 0 and len(group_mismatch) == 0,
           "samples": (group_mismatch + bits_mismatch)[:12],
           "pmx_group_histogram": {},
           "blend_group_histogram": {},
           "blend_bits_histogram": {}}
    for pr in pmx_rows.values():
        key = str(pr["group"])
        out["pmx_group_histogram"][key] = out["pmx_group_histogram"].get(key, 0) + 1
    for br in blend_rows.values():
        key = str(br["mmd_group"])
        out["blend_group_histogram"][key] = out["blend_group_histogram"].get(key, 0) + 1
        key = "|".join(map(str, br["bits"])) or "none"
        out["blend_bits_histogram"][key] = out["blend_bits_histogram"].get(key, 0) + 1
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("MASK_JOIN matched=%d group_mismatch=%d bits_mismatch=%d wired=%s"
          % (out["matched"], out["group_mismatch"], out["bits_mismatch"], out["mask_wired"]))
    print("MASK_JOIN pmx_groups=%s" % out["pmx_group_histogram"])
    print("MASK_JOIN blend_groups=%s blend_bits=%s"
          % (out["blend_group_histogram"], out["blend_bits_histogram"]))


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--join":
        with open(argv[1], encoding="utf-8") as fh:
            pmx_table = json.load(fh)
        with open(argv[2], encoding="utf-8") as fh:
            blend_table = json.load(fh)
        join(pmx_table, blend_table, argv[3])
        return 0
    table = load_pmx_table(argv[0])
    with open(argv[1], "w", encoding="utf-8", newline="\n") as fh:
        json.dump(table, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("PMX_MASK count=%d groups=%s"
          % (table["count"], sorted({r["group"] for r in table["rows"].values()})))
    return 0


if __name__ == "__main__":
    sys.exit(main())
