"""执行流水线的 modal operator。

用**子进程 + timer 轮询**，不用后台线程：
  bpy.data 只能在主线程访问，线程方案是死路；而流水线本身已经是 CLI，
  子进程跑它最稳，UI 不卡、进度可见、ESC 可取消。
"""
import json
import os
import subprocess
import sys

import bpy

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
        d = os.path.join(self._out, "frames")
        if not os.path.isdir(d):
            return 0
        try:
            n = sum(1 for f in os.listdir(d) if f.endswith(".png"))
        except OSError:
            return 0
        return max(0, min(99, int(n * 100 / max(1, self._frames))))

    def modal(self, context, event):
        wm = context.window_manager
        if event.type == "ESC":
            return self._cancel(context, "用户取消")
        if event.type == "TIMER":
            if self._proc.poll() is not None:
                return self._finish(context)
            wm.progress_update(self._pct())
            wm.status_text = "MMD Pipeline %d%%" % self._pct()
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
        state = {}
        try:
            with open(os.path.join(self._out, "pipeline_state.json"), encoding="utf-8") as fh:
                state = json.load(fh)
        except (OSError, ValueError):
            pass

        if rc == 0 and state.get("ok"):
            self.report({"INFO"}, "完成：%s" % self._out)
            return {"FINISHED"}

        blocked = ", ".join(state.get("blocked_by") or []) or "见 run.log"
        # 错误信息要可操作：不只说"失败了"，还说要去看哪儿
        self.report({"ERROR"}, "未通过（退出码 %d）：%s。日志 %s"
                              % (rc, blocked, os.path.join(self._out, "run.log")))
        return {"CANCELLED"}


CLASSES = (MMDP_OT_run,)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
