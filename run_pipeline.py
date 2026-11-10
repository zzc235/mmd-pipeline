"""Blender 入口：把工作目录放进 sys.path，然后交给 mmdpipe.runner。

    blender -b -P run_pipeline.py -- --pmx X.pmx --vmd Y.vmd --out OUT [--frames 360]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mmdpipe.runner import main

code = main()
print("PIPELINE_EXIT=%d" % code, flush=True)
