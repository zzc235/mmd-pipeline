"""给 324 批次补一份**冻结 manifest**（`D-198`/`D-203` 的双向枚举那一层）。

为什么要补：`总控` 19:50 用 `coordination.artifact_audit` 盘四棵树，`M05` 这批报「量不了」——
14 个文件里 5 份 `.blend` 是 `0o444`，9 个 `.json` 是可写记录，但**整批没有 manifest**，
所以「盘上每个在账上、账上每个在盘上」这一层没有账可对。补一份枚举即可，**不必重跑批次**。

形状照 `reports/subai/M02/frozen_manifest_324.json`：`items[].{name,role,sha256,bytes,readonly}`。
条目写**裸文件名**（不写绝对路径）：manifest 与产物同目录，`artifact_audit` 的双向枚举才成立
（它只在「条目都落在 manifest 自己这一层」时才做 `only_on_disk` 检查）。

    python out/subai/M05/make_arms_manifest.py [--dir ...] [--json ...]
"""
import argparse
import datetime
import hashlib
import io
import json
import os
import stat

def find_repo_root(start):
    """往上走到有 `coordination/` 与 `mmdpipe/` 的那一层；走不到就把起点打出来再死。

    不写死 `dirname` 次数：同一份脚本既可能在 `out/subai/M05/`（产物树）也可能在
    `reports/subai/M05/scripts/`（仓库），深度不同，写死次数必然有一边算错 ——
    而算错的形状是 `ImportError`，看起来像「这个模块不存在」（`D-228` 规则十二条）。
    """
    cur = os.path.abspath(start)
    while True:
        if (os.path.isdir(os.path.join(cur, "coordination"))
                and os.path.isdir(os.path.join(cur, "mmdpipe"))):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            raise SystemExit("从 %s 往上走到顶也没找到 coordination/ 与 mmdpipe/"
                             % os.path.abspath(start))
        cur = parent
ROOT = find_repo_root(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_DIR = os.path.join(ROOT, "out", "subai", "M05", "arms", "20261116_324")
MANIFEST_NAME = "manifest.json"
TEXT_SUFFIXES = (".json",)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_lf_file(path):
    with open(path, "rb") as fh:
        data = fh.read()
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def is_readonly(path):
    return not bool(os.stat(path).st_mode & stat.S_IWRITE)


def build(batch_dir, manifest_path):
    # 排除规则与 `coordination.artifact_audit` 对齐：任何 `*manifest*.json` 都不入账。
    # 否则换个 `--json` 目标名时，上一份 manifest 会被当成产物记进去（实测 items 从 14 变 15）。
    def _is_manifest(name):
        low = name.lower()
        return "manifest" in low and low.endswith(".json")

    names = sorted(n for n in os.listdir(batch_dir)
                   if os.path.isfile(os.path.join(batch_dir, n))
                   and not _is_manifest(n)
                   and n != os.path.basename(manifest_path))
    items = []
    for name in names:
        full = os.path.join(batch_dir, name)
        item = {"name": name, "role": name, "bytes": os.path.getsize(full),
                "sha256": sha256_file(full), "readonly": is_readonly(full)}
        if name.lower().endswith(TEXT_SUFFIXES):
            item["sha256_lf_normalized"] = sha256_lf_file(full)
        items.append(item)
    readonly_n = sum(1 for i in items if i["readonly"])
    blends = [i for i in items if i["name"].lower().endswith(".blend")]
    records = [i for i in items if not i["name"].lower().endswith(".blend")]
    return {
        "manifest_name": os.path.basename(manifest_path),
        "purpose": "M05 324 批次：五臂 .blend（0o444 物证）+ 七份跑批记录 + 回读读数的双向枚举账本",
        "generated_by": "out/subai/M05/make_arms_manifest.py",
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "assertions": {
            "batch_id": "20261116_324",
            "files_total": len(items),
            "blend_frozen_readonly": len(blends),
            "records_writable": len(records),
            "readonly_files": readonly_n,
            "two_way_expected": True,
            "input_sha256": "ffaa6780a2f7e765512201403a21e34848837b5f1c7486e91a70442762857761",
            "note": ("`0o444` 只覆盖 5 份 .blend（臂件是物证，`D-189`）；9 份 .json 是跑批与回读记录，"
                     "写一次但不冻结 —— 本文件如实记 `readonly` 现状，不为了好看去 chmod。"
                     "条目用裸文件名，manifest 与产物同目录，`artifact_audit` 的双向枚举才成立。"),
        },
        "items": items,
    }


def main():
    ap = argparse.ArgumentParser(prog="make_arms_manifest")
    ap.add_argument("--dir", default=DEFAULT_DIR)
    ap.add_argument("--json", default=None, help="默认写到批次目录下的 manifest.json")
    args = ap.parse_args()
    batch_dir = os.path.abspath(args.dir)
    manifest_path = os.path.abspath(args.json or os.path.join(batch_dir, MANIFEST_NAME))
    if not os.path.isdir(batch_dir):
        raise SystemExit("批次目录不存在：%s" % batch_dir)
    if os.path.exists(manifest_path):
        raise SystemExit("拒绝覆盖已有 manifest：%s（先人工确认）" % manifest_path)
    data = build(batch_dir, manifest_path)
    with io.open(manifest_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    print("MANIFEST %s items=%d readonly=%d"
          % (manifest_path, len(data["items"]), data["assertions"]["readonly_files"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
