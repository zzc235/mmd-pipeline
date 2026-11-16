"""Blender 入口：把工作目录放进 sys.path，然后交给 mmdpipe.runner。

    blender -b -P run_pipeline.py -- --pmx X.pmx --vmd Y.vmd --out OUT [--frames 360]

**退出码必须透传**：以前这里只 print `PIPELINE_EXIT=n`，Blender 进程自己仍以 0 退出，
于是任何只看退出码的自动化（CI、runner、批处理）都会把 BLOCK 当成功——2026-11-16
M07 的受控失败测试就是这么暴露的：日志写着 `PIPELINE_EXIT=1`，进程退出码却是 0。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mmdpipe.runner import main

code = main()
print("PIPELINE_EXIT=%d" % code, flush=True)
raise SystemExit(code)
