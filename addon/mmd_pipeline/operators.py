"""执行流水线的 modal operator。

用**子进程 + timer 轮询**，不用后台线程：
  bpy.data 只能在主线程访问，线程方案是死路；而流水线本身已经是 CLI，
  子进程跑它最稳，UI 不卡、进度可见、ESC 可取消。
"""
import os
import subprocess
import sys

import bpy

from . import status as status_mod
from .mmdpipe import params as params_mod

PIPELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_pipeline.py")


def _argv_from(settings):
    argv = []
    for p in params_mod.PARAMS:
        val = getattr(settings, p.name, None)
        if p.kind == "bool":
            if val:
                argv.append(p.flag)
            continue
        if p.kind == "list":
            items = [s.strip() for s in (val or "").replace(";", "\n").splitlines() if s.strip()]
            for it in items:
                argv += [p.flag, it]
            continue
        if val in (None, ""):
            continue
        # 可选数值参数（schema 里 default=None）在面板上会显示 0，
        # 不能因为 0 就把预设里的值覆盖掉。
        if p.default is None and p.kind in ("int", "float") and val == 0:
            continue
        if p.kind in ("path",):
            val = bpy.path.abspath(val)
        argv += [p.flag, str(val)]
    return argv


class MMDP_OT_run(bpy.types.Operator):
    bl_idname = "mmd_pipeline.run"
    bl_label = "渲染成片"
    bl_description = "在后台跑完整流水线：导入 → 物理 → 动作 → 外观 → 相机 → 渲染 → 门禁"
    bl_options = {"REGISTER"}

    _timer = None
    _proc = None
    _log = None
    _out = ""
    _frames = 0

    def execute(self, context):
        s = context.scene.mmdp
        if not s.pmx:
            self.report({"ERROR"}, "先选模型 PMX")
            return {"CANCELLED"}
        if not s.vmd and not s.motions:
            self.report({"ERROR"}, "至少给一个 VMD 或多段动作")
            return {"CANCELLED"}

        argv = _argv_from(s)
        self._out = bpy.path.abspath(s.out) if s.out else ""
        self._frames = max(1, int(s.frames))
        os.makedirs(self._out, exist_ok=True)
        self._log = open(os.path.join(self._out, "run.log"), "w", encoding="utf-8")

        cmd = [bpy.app.binary_path, "-b", "-P", PIPELINE, "--"] + argv
        self._log.write("CMD " + " ".join(cmd) + "\n\n")
        self._log.flush()
        try:
            self._proc = subprocess.Popen(cmd, stdout=self._log, stderr=subprocess.STDOUT)
        except OSError as exc:
            self._log.close()
            self.report({"ERROR"}, "起不来子进程：%s" % exc)
            return {"CANCELLED"}

        wm = context.window_manager
        wm.progress_begin(0, 100)
        self._timer = wm.event_timer_add(0.5, window=context.window)
        wm.modal_handler_add(self)
        self.report({"INFO"}, "已启动，进度见状态栏；ESC 可取消")
        return {"RUNNING_MODAL"}

    def _pct(self):
        """进度只看 state 记的产物路径，不假定 `<out>/frames`。

        isolated 布局把帧序列放在 `<out>/work/<run_id>/frames`，
        旧写法数 `<out>/frames` 永远得 0——面板一路 0% 直到结束。
        """
        info = status_mod.summary(self._out)
        return status_mod.progress_pct(info["frames"], self._frames)

    def modal(self, context, event):
        wm = context.window_manager
        if event.type == "ESC":
            return self._cancel(context, "用户取消")
        if event.type == "TIMER":
            if self._proc.poll() is not None:
                return self._finish(context)
            pct = self._pct()
            wm.progress_update(pct)
            wm.status_text = "MMD Pipeline %d%%" % pct
        return {"PASS_THROUGH"}

    def _cleanup(self, context):
        wm = context.window_manager
        if self._timer:
            wm.event_timer_remove(self._timer)
            self._timer = None
        wm.progress_end()
        wm.status_text = ""
        if self._log:
            self._log.close()
            self._log = None

    def _cancel(self, context, why):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        self._cleanup(context)
        self.report({"WARNING"}, why)
        return {"CANCELLED"}

    def _finish(self, context):
        rc = self._proc.returncode
        self._cleanup(context)
        info = status_mod.summary(self._out)

        if rc == 0 and info["ok"]:
            where = info["final"] or info["work"]
            self.report({"INFO"}, "完成：%d 帧已落地 %s（布局 %s）"
                                  % (info["frames"], where, info["layout"]))
            return {"FINISHED"}

        # 错误信息要可操作：不只说"失败了"，还说要去看哪儿、卡在哪一阶段
        reason = info["reason"] or ", ".join(info["blocked_by"]) or "见 run.log"
        stage = ("（%s）" % info["stage"]) if info["stage"] else ""
        self.report({"ERROR"}, "未通过（退出码 %d）%s：%s。日志 %s"
                              % (rc, stage, reason, info["log"]))
        return {"CANCELLED"}


RUN_TOOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_tool.py")


def _tool_cmd(tool, tool_args):
    """用 Blender 自己的解释器跑包内 CLI；工具名是白名单（见 run_tool.py）。"""
    return [bpy.app.binary_path, "-b", "-P", RUN_TOOL, "--", tool] + list(tool_args)


def _run_tool(tool, tool_args, timeout=900):
    return subprocess.run(_tool_cmd(tool, tool_args), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def _tail(text, lines=3):
    body = [ln for ln in (text or "").strip().splitlines() if ln.strip()]
    return " | ".join(body[-lines:])


class MMDP_OT_diagnose(bpy.types.Operator):
    bl_idname = "mmd_pipeline.diagnose"
    bl_label = "诊断归因"
    bl_description = "对当前 PMX 跑归因判据（diagnose/1 JSON），结果写进 <输出>/diagnose/"
    bl_options = {"REGISTER"}

    def execute(self, context):
        s = context.scene.mmdp
        if not s.pmx:
            self.report({"ERROR"}, "先选模型 PMX")
            return {"CANCELLED"}
        if not s.out:
            self.report({"ERROR"}, "先选输出目录")
            return {"CANCELLED"}
        out_dir = bpy.path.abspath(s.out)
        dst = os.path.join(out_dir, "diagnose", "diagnosis.json")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            proc = _run_tool("diagnose", ["--pmx", bpy.path.abspath(s.pmx), "--out", dst])
        except OSError as exc:
            self.report({"ERROR"}, "起不来子进程：%s" % exc)
            return {"CANCELLED"}
        # diagnose 的退出码：0=无 confirmed 归因，1=有 confirmed（同样是有效结果），2=用法错，3=输入不可读
        if proc.returncode in (0, 1):
            tag = "有 confirmed 归因" if proc.returncode == 1 else "无 confirmed 归因"
            self.report({"INFO"}, "诊断完成（%s）→ %s" % (tag, dst))
            return {"FINISHED"}
        self.report({"ERROR"}, "诊断失败（退出码 %d）：%s"
                              % (proc.returncode, _tail(proc.stdout or proc.stderr)))
        return {"CANCELLED"}


class MMDP_OT_gate(bpy.types.Operator):
    bl_idname = "mmd_pipeline.gate"
    bl_label = "跑物理门禁"
    bl_description = "对 <输出>/measurement.json 跑 physics_gate/1，结果写进 <输出>/gate/"
    bl_options = {"REGISTER"}

    def execute(self, context):
        s = context.scene.mmdp
        if not s.out:
            self.report({"ERROR"}, "先选输出目录")
            return {"CANCELLED"}
        out_dir = bpy.path.abspath(s.out)
        measurement = os.path.join(out_dir, "measurement.json")
        if not os.path.isfile(measurement):
            self.report({"ERROR"}, "没有 %s：先用 mmdpipe.measure 生成测量文件" % measurement)
            return {"CANCELLED"}
        profile = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "presets", "physics_gate", "exploratory_v0.json")
        if not os.path.isfile(profile):
            self.report({"ERROR"}, "包内缺门禁配置 %s" % profile)
            return {"CANCELLED"}
        dst = os.path.join(out_dir, "gate", "gate.json")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            proc = _run_tool("physics_gate", ["--measurement", measurement,
                                              "--profile", profile, "--out", dst])
        except OSError as exc:
            self.report({"ERROR"}, "起不来子进程：%s" % exc)
            return {"CANCELLED"}
        # 0=PASS 1=FAIL 3=UNKNOWN 都会产出 JSON；2=配置/输入错误，**不产出 JSON**（见 M04 接口 §4.1）
        if proc.returncode in (0, 1, 3):
            label = {0: "PASS", 1: "FAIL", 3: "UNKNOWN"}[proc.returncode]
            self.report({"INFO"}, "门禁 %s → %s" % (label, dst))
            return {"FINISHED"}
        self.report({"ERROR"}, "门禁未产出结果（退出码 2，配置或输入不可用）：%s"
                              % _tail(proc.stdout or proc.stderr))
        return {"CANCELLED"}


class MMDP_OT_open_dir(bpy.types.Operator):
    bl_idname = "mmd_pipeline.open_dir"
    bl_label = "打开输出目录"
    bl_description = "在文件管理器里打开输出目录（只读，不改任何文件）"
    bl_options = {"REGISTER"}

    def execute(self, context):
        s = context.scene.mmdp
        if not s.out:
            self.report({"ERROR"}, "先选输出目录")
            return {"CANCELLED"}
        path = bpy.path.abspath(s.out)
        if not os.path.isdir(path):
            self.report({"ERROR"}, "目录不存在：%s" % path)
            return {"CANCELLED"}
        bpy.ops.wm.path_open(filepath=path)
        return {"FINISHED"}


CLASSES = (MMDP_OT_run, MMDP_OT_diagnose, MMDP_OT_gate, MMDP_OT_open_dir)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
