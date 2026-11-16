"""M02 阶段 C：下摆根部关节的逐帧动态探针（Blender 侧，只读 .blend）。

    blender -b -P m02_dynamics_probe.py -- <scene.blend> <out_dir> --targets <s2_targets.json> \
        [--label baseline|patched] [--frames-from 1] [--frames-to N] [--preroll 0]

输出（都写 <out_dir>）：
  frames.jsonl   每行 {frame, bone, angle_deg, parent_delta_deg}（逐帧原始值，不做聚合）
  meta.json      场景/设置/计数/blend sha256/脚本 sha256

设计要点（照 AGENTS.md 第一条：先找现成的）
- 复用 `E:\\flowhmr-test\\tools\\phys_probe.py` 里已验证的三件事：连续 `frame_set` 步进（不走
  ptcache bake——该 operator 在本机 312 刚体下会段错误）、`os._exit(0)` 绕开退出阶段崩溃、
  **从不 save** 源工程。
- 不复用它的测量口径：phys_probe 测的是骨点世界位移的 speed/accel，本模块要的是
  **相对父骨的旋转角**与**父链逐帧增量**，那是另一种量，塞进去会把两边口径都污染。

判定口径
- `angle_deg`：本帧该骨相对父骨的旋转角（度），`rel = parent.matrix^-1 @ pb.matrix`（armature 空间），
  取 `rel.to_quaternion().angle` 的度数。根骨（无父）相对 armature 本体。
- `parent_delta_deg`：该骨父骨**相对上一帧**的旋转增量（度），第 1 帧为 null。
  判「冻结」用这一列：冻结的物理链表现为父链逐帧增量恒 0。

注意
- 本脚本**尚未在 Blender 里实跑过**（写它时没有租约）。首次运行需确认：目标骨名在工程里存在、
  父链完整、帧区间与 scene.frame_end 的关系。任何一条不符就停下改脚本，别在产物上糊。
- 穿透（evaluated mesh 网格级）不在 v1 里：宁可留空让门禁返回 UNKNOWN，也不凑一个 0.0。
"""
import hashlib
import json
import os
import sys
import time

import bpy


def parse_argv():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) < 2:
        raise SystemExit("usage: m02_dynamics_probe.py -- scene.blend out_dir --targets t.json [opts]")
    opts = {"blend": argv[0], "out_dir": argv[1], "targets": None, "label": "baseline",
            "frames_from": None, "frames_to": None, "preroll": 0}
    i = 2
    while i < len(argv):
        key = argv[i].lstrip("-").replace("-", "_")
        val = argv[i + 1]
        opts[key] = int(val) if key in ("frames_from", "frames_to", "preroll") else val
        i += 2
    if not opts["targets"]:
        raise SystemExit("missing --targets <s2_targets.json>")
    return opts


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def angle_between(a, b):
    """两个四元数之间的旋转角（弧度）。用 rotation_difference 再折到 [0, π]：
    quaternion.angle 在符号翻转时会给出接近 2π 的值（实测出现过 359.6°），
    那是表示法问题不是真转动，必须折回来。"""
    ang = a.rotation_difference(b).angle
    if ang > 3.141592653589793:
        ang = 6.283185307179586 - ang
    return ang


def main():
    opts = parse_argv()
    with open(opts["targets"], encoding="utf-8") as fh:
        targets = json.load(fh)["targets"]

    # 目标骨由离线阶段「结构性筛选」得出（关节旋转限位 ±π/2），这里只消费结果，不做名字匹配
    want_bones = []
    for t in targets:
        rb = t.get("rigid_b") or {}
        bone = rb.get("bone")
        if bone and bone not in want_bones:
            want_bones.append(bone)

    blend_sha = sha256_file(opts["blend"])
    bpy.ops.wm.open_mainfile(filepath=opts["blend"])
    scene = bpy.context.scene
    rbw = scene.rigidbody_world
    if rbw is None:
        raise SystemExit("scene has no rigid body world")
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")

    missing = [b for b in want_bones if arm.pose.bones.get(b) is None]
    if missing:
        raise SystemExit("目标骨在工程里不存在：%r" % (missing,))

    start = opts["frames_from"] or scene.frame_start
    end = opts["frames_to"] or scene.frame_end
    preroll = max(0, int(opts["preroll"]))
    step_start = start - preroll
    scene.frame_start = step_start
    scene.frame_end = end
    pc = rbw.point_cache
    pc.frame_start = step_start
    pc.frame_end = end

    fps = scene.render.fps / scene.render.fps_base
    rows = []
    prev_parent_rot = {}
    prev_world_rot = {}
    t0 = time.time()
    scene.frame_set(step_start)
    for f in range(step_start, end + 1):
        scene.frame_set(f)
        if f < start:
            # 预滚动：只推进模拟，不落盘（避免把暖机帧当成数据）
            for bone_name in want_bones:
                pb = arm.pose.bones[bone_name]
                prev_parent_rot[bone_name] = (pb.parent.matrix.to_quaternion()
                                             if pb.parent else pb.matrix.to_quaternion())
                prev_world_rot[bone_name] = (arm.matrix_world @ pb.matrix).to_quaternion()
            continue
        for bone_name in want_bones:
            pb = arm.pose.bones[bone_name]
            parent_m = pb.parent.matrix if pb.parent else arm.matrix_world
            rel = parent_m.inverted() @ pb.matrix
            angle_deg = rel.to_quaternion().angle * 57.29577951308232
            eul = rel.to_euler('XYZ')
            rot_x_deg = eul.x * 57.29577951308232
            rot_y_deg = eul.y * 57.29577951308232
            rot_z_deg = eul.z * 57.29577951308232
            cur_parent = (pb.parent.matrix.to_quaternion() if pb.parent
                          else pb.matrix.to_quaternion())
            prev = prev_parent_rot.get(bone_name)
            delta = None if prev is None else angle_between(prev, cur_parent) * 57.29577951308232
            # 世界朝向逐帧增量：不依赖父链（父链静止时唯一可用的冻结观测量）
            cur_world = (arm.matrix_world @ pb.matrix).to_quaternion()
            prev_w = prev_world_rot.get(bone_name)
            wdelta = None if prev_w is None else angle_between(prev_w, cur_world) * 57.29577951308232
            rows.append({"frame": f, "bone": bone_name,
                         "angle_deg": round(angle_deg, 6),
                         "rot_x_deg": round(rot_x_deg, 6),
                         "rot_y_deg": round(rot_y_deg, 6),
                         "rot_z_deg": round(rot_z_deg, 6),
                         "parent_delta_deg": None if delta is None else round(delta, 6),
                         "bone_world_delta_deg": None if wdelta is None else round(wdelta, 6)})
            prev_parent_rot[bone_name] = cur_parent
            prev_world_rot[bone_name] = cur_world

    os.makedirs(opts["out_dir"], exist_ok=True)
    frames_path = os.path.join(opts["out_dir"], "frames.jsonl")
    with open(frames_path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    meta = {
        "task": "M02",
        "stage": "C-dynamics",
        "label": opts["label"],
        "blend": {"path": opts["blend"], "sha256": blend_sha},
        "frames": {"from": start, "to": end, "preroll": preroll, "fps": fps},
        "settings": {"substeps": rbw.substeps_per_frame, "iterations": rbw.solver_iterations},
        "targets": want_bones,
        "row_count": len(rows),
        "columns": ["frame", "bone", "angle_deg", "rot_x_deg", "rot_y_deg", "rot_z_deg",
                    "parent_delta_deg", "bone_world_delta_deg"],
        "penetration": {"status": "NOT_MEASURED",
                        "reason": "v1 不做 evaluated-mesh 网格级穿透测量；留 UNKNOWN，不凑 0.0"},
        "elapsed_s": round(time.time() - t0, 1),
        "script_sha256": sha256_file(os.path.abspath(__file__)),
        "never_saved_blend": True,
    }
    with open(os.path.join(opts["out_dir"], "meta.json"), "w", encoding="utf-8",
              newline="\n") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")

    print("RESULT rows=%d bones=%d frames=%d..%d out=%s"
          % (len(rows), len(want_bones), start, end, opts["out_dir"]))
    sys.stdout.flush()
    # 该构建下刚体析构阶段会段错误，绕过它（与 phys_probe.py 同法）
    os._exit(0)


main()
