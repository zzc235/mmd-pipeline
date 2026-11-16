"""12 帧 E2E 的入口脚手架（**只是测试脚手架，不是产品路径**）：

    blender -b -P tests_bpy/run_e2e.py -- --pmx X.pmx --vmd Y.vmd --out OUT --frames 12 --layout isolated

为什么需要它：这台机器上 `bl_ext.user_default.mmd_tools` 扩展已安装但**未启用**，
且它的 `wheels/opencc*.whl` 只在启用时才解包，直接 import 会
`ModuleNotFoundError: No module named 'opencc'`，于是 `bpy.ops.mmd_tools.import_model`
不存在、`S2_import` 阶段直接失败。`addon_utils.enable(...)` 之后同一个进程里导入与
operator 都正常——所以 E2E 用这份脚手架先启用，再交给 `mmdpipe.runner.main()`。

两条纪律：
  * `default_set=False, persistent=False` —— **不写用户偏好**，不改变这台机器的全局配置；
  * 脚手架不参与产品逻辑：面板/CLI 走的是 `run_pipeline.py`，这一份只给 E2E 用。

退出码与 `run_pipeline.py` 一致（透传 `main()` 的返回值），受控失败路径才能用退出码断言。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MMD_TOOLS = "bl_ext.user_default.mmd_tools"


def enable_mmd_tools() -> bool:
    """尽力启用 mmd_tools；启用不了就明确说出来，让 S2_import 的失败原因可读。"""
    try:
        import addon_utils
        addon_utils.enable(MMD_TOOLS, default_set=False, persistent=False)
    except Exception as exc:                        # noqa: BLE001
        print("E2E_SCAFFOLD mmd_tools 启用失败：%s: %s" % (type(exc).__name__, exc), flush=True)
        return False
    import bpy
    ok = hasattr(bpy.ops.mmd_tools, "import_model")
    print("E2E_SCAFFOLD mmd_tools 已在本会话启用（不写偏好），import_model=%r" % ok, flush=True)
    return ok


if __name__ == "__main__":
    enable_mmd_tools()
    from mmdpipe.runner import main
    code = main()
    print("PIPELINE_EXIT=%d" % code, flush=True)
    raise SystemExit(code)
