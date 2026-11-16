"""在 Blender 进程里跑扩展包自带的 CLI 工具（diagnose / physics_gate / gate_report）。

为什么需要这个壳：插件里 `mmdpipe` 是**扩展包内的一份副本**，系统 Python 的
`python -m mmdpipe.diagnose` 找不到它。所以统一用 Blender 自己的解释器：
    <blender> -b -P run_tool.py -- diagnose --pmx 模型.pmx --out out/diagnose.json

工具名白名单写死（与 13 §8 的 runner 白名单同一思路）：不接受任意命令。
退出码原样透传，调用方（operator）只看退出码与产物是否存在。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

TOOLS = ("diagnose", "physics_gate", "gate_report")


def _argv():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    return argv


def main() -> int:
    argv = _argv()
    if not argv or argv[0] not in TOOLS:
        sys.stderr.write("用法：-P run_tool.py -- {%s} [参数…]\n" % "|".join(TOOLS))
        return 2
    tool, rest = argv[0], argv[1:]
    if tool == "diagnose":
        from mmdpipe.diagnose import main as entry
    elif tool == "physics_gate":
        from mmdpipe.physics_gate import main as entry
    else:
        from mmdpipe.gate_report import main as entry
    return entry(rest)


if __name__ == "__main__":
    code = main()
    print("TOOL_EXIT=%d" % code, flush=True)
    raise SystemExit(code)
