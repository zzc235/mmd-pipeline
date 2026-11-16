"""把 mmdpipe 库和预设一起打进 Blender 扩展包。

    python build_addon.py            # 暂存 + 校验 + 打包

产物：dist/mmd_pipeline-<version>.zip，只认**本次版本号的那个** zip。

原则：单一来源。库只有一份（工作区的 mmdpipe/），这里只做复制与打包。

为什么改成"校验失败就不打包"：原来的行为是校验失败也继续 build，
再把 dist 里**所有** zip 一起打印出来——包括上一次版本留下的旧包。
于是"打包成功"这句话可能指着一个旧 zip，而真正的问题（清单不合法）
被埋在日志里。现在：校验不过直接返 2，只认 <version> 对应的那个文件名。
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "addon", "mmd_pipeline")
STAGE = os.path.join(ROOT, "build", "mmd_pipeline")
DIST = os.path.join(ROOT, "dist")
BLENDER = os.environ.get("BLENDER_BIN") or r"E:/code/Blender/blender-5.2.2-windows-x64/blender.exe"

# 包里只该有代码与预设：模型、动作、序列帧、历史工程都不许混进来（10 §6）。
BANNED_SUFFIX = (".pmx", ".vmd", ".blend", ".blend1", ".mp4", ".avi", ".png",
                 ".jpg", ".jpeg", ".npz", ".bvh")
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")


def read_version() -> str:
    """从 blender_manifest.toml 取 version，并与 __init__.py 的 bl_info 对齐。"""
    manifest = os.path.join(SRC, "blender_manifest.toml")
    text = open(manifest, "r", encoding="utf-8").read()
    m = re.search(r'^\s*version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        raise SystemExit("!! 清单里找不到 version：%s" % manifest)
    version = m.group(1)

    init = open(os.path.join(SRC, "__init__.py"), "r", encoding="utf-8").read()
    bm = re.search(r'"version"\s*:\s*\((\d+),\s*(\d+),\s*(\d+)\)', init)
    if not bm:
        raise SystemExit("!! __init__.py 里找不到 bl_info version")
    bl_info = ".".join(bm.groups())
    if bl_info != version:
        raise SystemExit("!! 版本不一致：清单 %s，bl_info %s（先统一再打包）"
                         % (version, bl_info))
    return version


def stage() -> None:
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    os.makedirs(os.path.dirname(STAGE), exist_ok=True)
    shutil.copytree(SRC, STAGE, ignore=IGNORE)
    # 库：单一来源，复制而非复制品维护
    shutil.copytree(os.path.join(ROOT, "mmdpipe"), os.path.join(STAGE, "mmdpipe"), ignore=IGNORE)
    presets = os.path.join(ROOT, "presets")
    if os.path.isdir(presets):
        shutil.copytree(presets, os.path.join(STAGE, "presets"), ignore=IGNORE)
    # run_pipeline.py 也带上：习惯命令行的可以直接跑
    shutil.copy2(os.path.join(ROOT, "run_pipeline.py"), os.path.join(STAGE, "run_pipeline.py"))
    stray = [p for p in _walk(STAGE) if p.lower().endswith(BANNED_SUFFIX)]
    if stray:
        raise SystemExit("!! 暂存目录里混进了不该打包的资产：%s" % ", ".join(stray[:5]))
    print("暂存: %s（%d 个文件）" % (STAGE, len(_walk(STAGE))))


def _walk(base: str) -> list:
    out = []
    for dirpath, _dirs, files in os.walk(base):
        for name in files:
            out.append(os.path.relpath(os.path.join(dirpath, name), base))
    return out


def validate() -> bool:
    r = subprocess.run([BLENDER, "-b", "--command", "extension", "validate", STAGE],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    print(out.strip()[-1200:])
    return r.returncode == 0


def build() -> int:
    os.makedirs(DIST, exist_ok=True)
    r = subprocess.run([BLENDER, "-b", "--command", "extension", "build",
                        "--source-dir", STAGE, "--output-dir", DIST],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    print(out.strip()[-1200:])
    return r.returncode


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    version = read_version()
    print("版本: %s" % version)
    stage()
    if not validate():
        print("!! 扩展校验未通过，已停止打包（不产生候选包）")
        return 2
    if build() != 0:
        print("!! 打包失败")
        return 3
    zip_path = os.path.join(DIST, "mmd_pipeline-%s.zip" % version)
    if not os.path.isfile(zip_path):
        print("!! 没找到预期产物 %s（dist 里可能有旧版本残留，别拿它们当本次结果）"
              % zip_path)
        return 4
    print("PACKAGE %s  %.1f MB" % (zip_path, os.path.getsize(zip_path) / 1e6))
    print("SHA256 %s" % sha256(zip_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
