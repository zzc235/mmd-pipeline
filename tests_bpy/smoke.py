"""bpy 层冒烟测试（需在 Blender 内跑）：

    blender -b -P tests_bpy/smoke.py

断言三件本轮真实撞过的事：
  1. 扩展包内导入（绝对 `from mmdpipe import ...` 在 bl_ext 包内会失效）
  2. 参数层与面板同源
  3. stage_camera 在"没有 --camera 预设"时也必须返回对象（抽函数带走返回路径的事故）
"""
import sys
import traceback

import bpy
import addon_utils

FAIL = []


def check(name, fn):
    try:
        fn()
        print("  PASS %s" % name)
    except Exception as exc:                        # noqa: BLE001
        FAIL.append(name)
        print("  FAIL %s: %s" % (name, exc))
        traceback.print_exc()


FULL = "bl_ext.user_default.mmd_pipeline"


def t_import():
    """扩展包内所有模块都能导入（相对导入没写错）。"""
    pkg = __import__(FULL, fromlist=["mmdpipe", "operators", "panels", "properties"])
    for sub in ("pmx", "vmd", "params", "physics", "stage", "runner", "chain_nla"):
        __import__(FULL + ".mmdpipe." + sub)


def t_parity():
    pkg = __import__(FULL, fromlist=["mmdpipe"])
    P = pkg.mmdpipe.params                            # 扩展包内只能走包内路径
    s = bpy.context.scene.mmdp
    pub = {p.identifier for p in s.bl_rna.properties
           if not p.is_readonly and p.identifier not in ("rna_type", "name")}
    expect = {p.name for p in P.PARAMS}
    assert pub == expect, "面板与参数声明不一致：缺 %s 多 %s" % (expect - pub, pub - expect)


def t_camera_no_preset():
    """没有冻结机位时必须走包围盒取景，不能返回 None。"""
    pkg = __import__(FULL, fromlist=["mmdpipe"])
    stage, P = pkg.mmdpipe.stage, pkg.mmdpipe.preset
    p = P.load(None)
    p["camera"]["loc"] = None
    p["camera"]["rot"] = None
    # 最小场景：一个网格 + 刚体世界（_fit_camera 需要刚体）
    bpy.ops.mesh.primitive_cube_add()
    bpy.context.scene.frame_start, bpy.context.scene.frame_end = 1, 2
    out = stage.stage_camera(p, 1, 2)
    assert isinstance(out, tuple) and len(out) == 2, "stage_camera 必须返回 (StageResult, cam)"
    st, cam = out
    assert st is not None, "stage 返回 None"
    # 没取到相机时必须给出可读的 BLOCK，而不是静默 None
    assert cam is not None or st.blocked, "既没有相机也没有报错，等于静默失败"


def t_argv():
    """面板字段 → CLI argv，路径带空格必须保留。"""
    pkg = __import__(FULL, fromlist=["operators"])
    s = bpy.context.scene.mmdp
    s.pmx = "E:/a b/模型.pmx"
    s.frames = 12
    s.align = "match"
    s.force_static = "xk_; zxk"
    argv = pkg.operators._argv_from(s)
    assert "E:/a b/模型.pmx" in argv, "空格路径被吞了"
    assert argv.count("--force-static") == 2, "列表没拆开"


def t_zones():
    """四区面板：分区元数据与参数声明同源，且每区非空。"""
    pkg = __import__(FULL, fromlist=["mmdpipe"])
    P = pkg.mmdpipe.params
    assert tuple(P.ZONES) == ("asset", "physics", "render"), P.ZONES
    covered = [p.name for z in P.ZONES for p in P.by_zone(z)]
    assert sorted(covered) == sorted(p.name for p in P.PARAMS), "有参数没归区或归了两次"
    for zone in P.ZONES:
        assert P.by_zone(zone), "区 %s 是空的" % zone


def t_panel_and_ops():
    """面板与四个工具按钮都注册上了。

    注意：Blender **不会**把 operator 类挂到 `bpy.types` 上（实测：`dir(bpy.types)`
    里只有 `MMDP_PT_main`，没有 `MMDP_OT_*`），但 `bpy.ops.mmd_pipeline.<op>`
    存在、且类上 `is_registered=True`。按 `bpy.types` 判会把"注册成功"误判成失败——
    这条是 2026-11-16 用坏断言撞出来的。
    """
    pkg = __import__(FULL, fromlist=["panels", "operators"])
    assert hasattr(bpy.types, "MMDP_PT_main"), "面板类不存在"
    namespace = bpy.ops.mmd_pipeline
    for op in ("run", "diagnose", "gate", "open_dir"):
        assert hasattr(namespace, op), "operator %s 没注册" % op
    for cls in pkg.operators.CLASSES:
        assert getattr(cls, "is_registered", False), "%s 未注册" % cls.__name__


def t_status_layer():
    """报告区读 state 的那一层：空目录不抛异常，空串给可读提示。"""
    pkg = __import__(FULL, fromlist=["status"])
    st = pkg.status
    assert st.report_lines("") == ["还没选输出目录"]
    info = st.summary("")
    assert isinstance(info, dict) and info["ok"] is False


def t_tool_entry():
    """run_tool 的白名单只有三个 CLI，不外扩。"""
    pkg = __import__(FULL, fromlist=["run_tool"])
    assert tuple(pkg.run_tool.TOOLS) == ("diagnose", "physics_gate", "gate_report")


print("SMOKE START")
addon_utils.enable(FULL, default_set=True, persistent=True)
check("包内导入", t_import)
check("参数同源", t_parity)
check("argv 生成", t_argv)
check("四区分区", t_zones)
check("面板与按钮注册", t_panel_and_ops)
check("报告区状态层", t_status_layer)
check("工具入口白名单", t_tool_entry)
check("无预设取景", t_camera_no_preset)

print("SMOKE RESULT %s (%d failed)" % ("OK" if not FAIL else "FAIL", len(FAIL)))
sys.exit(1 if FAIL else 0)
