"""协调层（M00）：任务板、调度器、分流器、证据哈希。

不 import bpy、不 import mmdpipe：这一层只处理状态与证据，不碰渲染与模型，
因此可以在任何 Python 环境里跑测试（13 §10 的 12 条 + evidence_hash 的 H1–H6）。
"""
