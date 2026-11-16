"""在 Blender 之外跑 `m02_mask_channel_probe.py --selftest`：用假 bpy 桩把模块导入，
只执行纯逻辑部分（`selftest()` 不碰 bpy.data）。这样不必占 Blender 锁，
也仍然是一次「最小真实路径」——比 `py_compile` 强的地方在于它真的会执行。

    python m02_probe_selftest_outside_blender.py [<被测脚本路径>]

给一个可选路径是为了做**变异测试**：把实现在副本里改坏，自检必须变红——否则这个
自检也是「检查通过 ≠ 行为正确」的又一个例子。

三道保险（第一道抄 2号，后两道是他那条「变异测试要进 artifact」的最小版）：

1. **身份检查**：`sha256(参数给的那个文件) == sha256(实际被 import 的模块文件)`。
   比的是「参数」与「实际加载」，不是「我自己算出来的变量」——我上一版就是算了
   `probe` 却仍用 `PROBE` 加载，于是变异测试一直在测未改动的原文件（假绿）。
2. **变异必须红**：改坏 `bucket_pairs` 的一条分支 ⇒ `selftest()` 必须返回非 0。
3. **等价变异必须仍绿**：只加注释这类不改变语义的改动 ⇒ 必须仍然返回 0，
   否则说明这个自检「对任何改动都红」，那种红没道理。

退出码：0 全部符合预期 / 1 有一道保险没过 / 4 身份检查失败（测错对象）。
"""
import hashlib
import importlib.util
import os
import subprocess
import sys
import types

PROBE = r"E:\dsh pr\woker2\reports\subai\M02\scripts\m02_mask_channel_probe.py"
HERE = os.path.abspath(__file__)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_probe(path):
    """导入被测脚本（假 bpy 桩），返回模块。"""
    bpy = types.ModuleType("bpy")
    bpy.data = types.SimpleNamespace(objects=[])          # 只在 main() 里用，selftest 不需要
    bpy.ops = types.SimpleNamespace()
    bpy.context = types.SimpleNamespace(scene=None)
    sys.modules["bpy"] = bpy

    addon_utils = types.ModuleType("addon_utils")
    addon_utils.modules = lambda: []
    addon_utils.enable = lambda *a, **k: None
    sys.modules["addon_utils"] = addon_utils

    spec = importlib.util.spec_from_file_location("m02_probe_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_once(path):
    """加载 `path` 并跑它的 selftest，返回退出码。"""
    mod = load_probe(path)
    probe_sha, loaded_sha = sha256_file(path), sha256_file(mod.__file__)
    if probe_sha != loaded_sha:
        print("  FAIL 身份检查：参数 %s ≠ 实际加载 %s"
              % (probe_sha[:16], loaded_sha[:16]))
        return 4
    print("  身份检查 arg==loaded=True sha256=%s" % probe_sha[:16])
    return mod.selftest()


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else PROBE
    # 桩自身的 canary：参数给了就必须用参数。我上一版正是「算了 probe 却仍用 PROBE」，
    # 于是变异测试一直在测未改动的原文件 —— 那条路必须有人拦。
    if len(sys.argv) > 1 and target != sys.argv[1]:
        print("FAIL 参数被忽略：argv[1]=%s 但 target=%s" % (sys.argv[1], target))
        return 4
    print("under test: %s" % target)
    print("[1] 正控（未改动的实现）")
    rc = run_once(target)
    print("  rc=%d（期望 0）" % rc)
    if rc != 0:
        return 1
    if "--only-positive" in sys.argv:
        return 0

    src = open(target, encoding="utf-8").read()

    print("[2] 变异（把通道前缀分支短路，必须红）")
    mut = src.replace("elif owner.startswith(ncc_prefix):",
                      "elif False and owner.startswith(ncc_prefix):")
    if mut == src:
        print("  FAIL 变异没打上（要替换的那行不在文件里）")
        return 1
    mpath = os.path.join(os.environ.get("TEMP", "."), "probe_mut_breaks.py")
    open(mpath, "w", encoding="utf-8", newline="\n").write(mut)
    rc = run_once(mpath)
    print("  rc=%d（期望非 0）" % rc)
    broke = rc != 0
    os.remove(mpath)

    print("[3] 等价变异（只加注释，必须仍绿）")
    mut2 = src.replace("    sep_pre = 0\n", "    sep_pre = 0   # 等价替换：只加注释\n", 1)
    if mut2 == src:
        print("  FAIL 等价变异没打上")
        return 1
    epath = os.path.join(os.environ.get("TEMP", "."), "probe_mut_equiv.py")
    open(epath, "w", encoding="utf-8", newline="\n").write(mut2)
    rc = run_once(epath)
    print("  rc=%d（期望 0）" % rc)
    equiv_ok = rc == 0
    os.remove(epath)

    print("[4] 身份检查负控（桩若忽略参数，必须被拦住）")
    hsrc = open(HERE, encoding="utf-8").read()
    hmut = hsrc.replace("    target = sys.argv[1] if len(sys.argv) > 1 else PROBE",
                        "    target = PROBE   # 故意忽略参数，复刻假绿")
    if hmut == hsrc:
        print("  FAIL 负控变异没打上")
        return 1
    hpath = os.path.join(os.environ.get("TEMP", "."), "harness_ignores_arg.py")
    open(hpath, "w", encoding="utf-8", newline="\n").write(hmut)
    proc = subprocess.run([sys.executable, hpath, "--only-positive"],
                          capture_output=True)
    out = proc.stdout.decode("utf-8", "replace")
    guard = ("FAIL 身份检查" in out) or proc.returncode == 4
    print("  rc=%d 拦住=%s" % (proc.returncode, guard))
    os.remove(hpath)

    ok = broke and equiv_ok and guard
    print("总判定 %s  变异红=%s 等价绿=%s 身份负控=%s"
          % ("PASS" if ok else "FAIL", broke, equiv_ok, guard))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
