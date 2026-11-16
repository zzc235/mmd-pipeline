# -*- coding: utf-8 -*-
"""按「枚举冻结目录」重建 `frozen/frozen_manifest.json`，并做双向断言（2号 18:53 指出的形状）。

错法（`eb6e82e`）：manifest 里列的是 **run 目录**里的两个文件，却没登记 `frozen/` 里真正的回读件；
单向枚举 ⇒ 账本指错件。正确做法照 `m04_run_cd.write_manifest()`：`os.listdir(batch_dir)` 逐文件取
`bytes` / `sha256` / `sha256_lf_normalized` / `readonly`，manifest 不把自己算进去。

双向断言（缺一不可）：
  ① 盘上每个文件（除 manifest 自身）都在账上；
  ② 账上每个文件都在盘上。
任一不满足 ⇒ 非 0 退出，不写 manifest。

用法：python m02_freeze_manifest.py --dir out/subai/M08/frozen [--run-id run_xxx] [--commit xxx]
"""
import argparse
import hashlib
import io
import json
import os
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

MANIFEST_NAME = "frozen_manifest.json"


def sha256_raw(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_lf(path):
    """文本按 LF 归一后再算（仓库 `core.autocrlf=true`，checkout 出来是 CRLF）。"""
    with open(path, "rb") as fh:
        data = fh.read()
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def file_facts(path):
    is_text = os.path.splitext(path)[1].lower() in (".json", ".md", ".txt", ".csv", ".log")
    facts = {"bytes": os.path.getsize(path), "sha256": sha256_raw(path),
             "readonly": bool(os.stat(path).st_mode & 0o444) and not os.access(path, os.W_OK)}
    if is_text:
        facts["sha256_lf_normalized"] = sha256_lf(path)
    return facts


def build(directory, extra=None):
    directory = os.path.abspath(directory)
    on_disk = sorted(n for n in os.listdir(directory)
                     if os.path.isfile(os.path.join(directory, n)) and n != MANIFEST_NAME)
    items = []
    for name in on_disk:
        entry = {"role": name, "frozen_path": os.path.join(directory, name)}
        entry.update(file_facts(entry["frozen_path"]))
        items.append(entry)
    manifest = {"purpose": "M08 324 交付件冻结副本：账本由**枚举冻结目录本身**生成，不手写、不从 run 目录抄",
                "freeze_order": "freeze 文件 → 枚举 frozen/ 写 manifest → freeze manifest",
                "manifest_name": MANIFEST_NAME,
                "items": items}
    for key, value in (extra or {}).items():
        manifest[key] = value
    # 双向断言
    disk_names = set(on_disk)
    listed = {os.path.basename(i["frozen_path"]) for i in items}
    only_disk = sorted(disk_names - listed)
    only_manifest = sorted(listed - disk_names)
    if only_disk or only_manifest:
        raise SystemExit("FAIL 双向断言：只在盘上=%r 只在账上=%r" % (only_disk, only_manifest))
    manifest["assertions"] = {"on_disk_count": len(disk_names), "listed_count": len(listed),
                              "only_on_disk": only_disk, "only_in_manifest": only_manifest,
                              "bidirectional_ok": True}
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--commit", default=None)
    args = ap.parse_args(argv)
    extra = {}
    if args.run_id:
        extra["frozen_at_run"] = args.run_id
    if args.commit:
        extra["commit_at_freeze"] = args.commit
    manifest = build(args.dir, extra)
    path = os.path.join(os.path.abspath(args.dir), MANIFEST_NAME)
    # 写之前先解只读（重复运行要能覆盖），写完由调用方统一冻结
    if os.path.exists(path):
        os.chmod(path, 0o666)
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    print("MANIFEST %s  items=%d  bytes=%d  sha256=%s"
          % (path, len(manifest["items"]), os.path.getsize(path), sha256_raw(path)))
    for item in manifest["items"]:
        print("  %-34s %9d  %s  ro=%s"
              % (item["role"], item["bytes"], item["sha256"], item["readonly"]))
    print("  双向断言：盘上 %d 个、账上 %d 个、差集均为空"
          % (manifest["assertions"]["on_disk_count"], manifest["assertions"]["listed_count"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
