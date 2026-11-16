"""隔离诊断：`use_disk_cache=True` 到底在哪一步炸（`EXCEPTION_ACCESS_VIOLATION`，无 traceback）。

三段各自 flush 打印，崩在哪段看最后一行。
    blender -b --python diag_diskcache.py -- <in_blend> <out_blend>
"""

import os
import sys

import bpy

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
in_blend, out_blend = argv[0], argv[1]


def say(msg):
    print("DIAG " + msg)
    sys.stdout.flush()


say("open")
bpy.ops.wm.open_mainfile(filepath=in_blend)
scene = bpy.context.scene
rbw = scene.rigidbody_world
pc = rbw.point_cache
say("PointCache props: " + ", ".join(p.identifier for p in pc.bl_rna.properties))
say("RigidBodyWorld props: " + ", ".join(p.identifier for p in rbw.bl_rna.properties))
say("cache before use_disk_cache=%r baked=%r outdated=%r"
    % (pc.use_disk_cache, pc.is_baked, pc.is_outdated))

say("set use_disk_cache")
pc.use_disk_cache = True
say("after: use_disk_cache=%r" % (pc.use_disk_cache,))
say("done")
os._exit(0)
