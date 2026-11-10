"""把 mmdpipe 库和预设一起打进 Blender 扩展包。

    python build_addon.py            # 暂存 + 校验 + 打包
产物：dist/mmd_pipeline-<version>.zip

原则：单一来源。库只有一份（工作区的 mmdpipe/），这里只做复制与打包。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "addon", "mmd_pipeline")
STAGE = os.path.join(ROOT, "build", "mmd_pipeline")
DIST = os.path.join(ROOT, "dist")
BLENDER = os.environ.get("BLENDER_BIN") or r"E:/code/Blender/blender-5.2.2-windows-x64/blender.exe"


def stage():
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    os.makedirs(os.path.dirname(STAGE), exist_ok=True)
    shutil.copytree(SRC, STAGE)
    # 库：单一来源，复制而非复制品维护
    shutil.copytree(os.path.join(ROOT, "mmdpipe"), os.path.join(STAGE, "mmdpipe"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    presets = os.path.join(ROOT, "presets")
    if os.path.isdir(presets):
        shutil.copytree(presets, os.path.join(STAGE, "presets"),
                        ignore=shutil.ignore_patterns("__pycache__"))
    # run_pipeline.py 也带上：习惯命令行的可以直接跑
    shutil.copy2(os.path.join(ROOT, "run_pipeline.py"), os.path.join(STAGE, "run_pipeline.py"))
    print("暂存: %s" % STAGE)


def validate():
    r = subprocess.run([BLENDER, "-b", "--command", "extension", "validate", STAGE],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    print(out.strip()[-1200:])
    return r.returncode == 0


def build():
    os.makedirs(DIST, exist_ok=True)
    r = subprocess.run([BLENDER, "-b", "--command", "extension", "build",
                        "--source-dir", STAGE, "--output-dir", DIST],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    print(out.strip()[-1200:])
    zips = [f for f in os.listdir(DIST) if f.endswith(".zip")]
    return zips


if __name__ == "__main__":
    stage()
    ok = validate()
    if not ok:
        print("!! 校验未通过，仍尝试打包（方便看具体报错）")
    zips = build()
    for z in zips:
        p = os.path.join(DIST, z)
        print("PACKAGE %s  %.1f MB" % (p, os.path.getsize(p) / 1e6))
