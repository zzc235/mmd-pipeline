"""按**指定的代码树**重建交付场景：`m02_rebuild_scene_v3.py` 的包装器。

    MMDPIPE_TREE=<树> blender -b -P m02_build_delivery.py -- <preset> <pmx> <out_dir> [--build]

为什么要有这个包装器（2026-11-16 15:03 的实证）：
`m02_rebuild_scene_v3.py` 里写死了 `A1 = E:\\code\\mmdpipe-ai\\A1` 并 `sys.path.insert(0, A1)`，
所以在 main 工作树里跑它，**导入的仍是我自己分支的 `mmdpipe`**。那次重建出来的
`delivery_v1.blend` 因此没有掩码通道，探头 `--expect wired` 判 **FAIL（patterns=1，分开 0）**——
探头的判据是对的，错的是「我以为我在跑 main 的代码」。

`m02_rebuild_scene_v3.py` 已被 `evidence/1:d2950f36…` 的 artifacts 哈希过，**不能改**；
所以这里用「先按指定树导入并占住 `sys.modules`，再 runpy 那个脚本」的方式换树：
脚本里那句 `from mmdpipe import stage` 会命中缓存，拿到的就是我指定树里的模块。

三道自证，缺一条这次重建就不该被引用：
1. 打印 `mmdpipe.stage.__file__` 与 `mmdpipe.mask.__file__`（若存在）；
2. 断言 `stage.__file__` 在 `MMDPIPE_TREE` 之下——**不是的话直接退出，不出 .blend**；
3. 打印 `stage.py` / `mask.py` 的 sha256，报告里引这个 sha，而不是引「main」这个词。

**这三道同时写进产物**（不只是 stdout，`D-20261116-147`）：`<out_dir>\\build_identity_<时间>.json`。
理由：三个月后有人只读产物时，也得能看出那一次跑的是哪棵树、哪个 sha。文件在**开跑之前**就写一次
（崩了也留得下），跑完再补一个 `outcome`。

`M02_BUILD_DRYRUN=1` 只写身份记录、不跑重建（用来验这一层本身）。
"""
import hashlib
import json
import os
import runpy
import sys
import time

# GBK 控制台下中文/符号会让脚本崩在打印上（总控 18:18）：入口统一 UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

TREE = os.environ.get("MMDPIPE_TREE") or r"E:\dsh pr\woker2"
# v3 从**本树**解析：跨树引用会让 identity 记录指向别的树，进闸门时 provenance 判 PROVENANCE_INVALID
# （那是闸门在正常工作）。真要跨树必须显式 `MMDPIPE_V3=<绝对路径>`，并被记成「跨树」可见于记录。
V3_DEFAULT = os.path.join(TREE, "reports", "subai", "M02", "scripts", "m02_rebuild_scene_v3.py")
V3 = os.environ.get("MMDPIPE_V3") or V3_DEFAULT


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def norm(path):
    return os.path.normcase(os.path.abspath(path))


def write_json(path, rec):
    """原子写：先写 .tmp 再 replace，避免半截 JSON 被后来者当成一份记录。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def _guarded_os_exit(code=0):
    """把 v3 的 `os._exit()` 变成本进程可捕获的 SystemExit。

    不拦的话（2026-11-16 实测）：v3 结尾 `os._exit(0)` 直接掐死进程，wrapper 来不及把
    identity 写成 `completed`，记录永远停在 `started` —— 那份身份**分不出「跑完」与
    「跑到一半死了」**。拦下来之后由 wrapper 自己写终态、自己给退出码。
    """
    raise SystemExit("v3_os_exit:%r" % (code,))


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out_dir = argv[2] if len(argv) > 2 else "."
    stamp = time.strftime("%Y%m%d_%H%M%S")
    # 输出目录不存在就建：以前这里抛 FileNotFoundError 而 Blender 照样返回 0（fail-open）。
    try:
        if out_dir and not os.path.isdir(out_dir):
            os.makedirs(out_dir)
    except OSError as exc:
        print("ABORT 无法创建输出目录 %r：%s" % (out_dir, exc))
        return 2
    ident_path = os.path.join(out_dir, "build_identity_%s.json" % stamp)
    rec = {
        "tool": "m02_build_delivery",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mmdpipe_tree_env": os.environ.get("MMDPIPE_TREE"),
        "tree": TREE,
        "argv": argv,
        "python": sys.version.split()[0],
        "wrapper": os.path.abspath(__file__),
        "wrapper_sha256": sha256_file(os.path.abspath(__file__)),
        "v3_script": V3,
        "v3_sha256": sha256_file(V3) if os.path.exists(V3) else None,
    }
    # `--patch <path>`：重建时是一个具名步骤（v3 的 apply_input_patch），身份记录里必须留补丁 sha
    if "--patch" in argv:
        i = argv.index("--patch")
        patch_path = argv[i + 1] if i + 1 < len(argv) else None
        info = {"path": os.path.abspath(patch_path) if patch_path else None}
        if patch_path and os.path.isfile(patch_path):
            info["file_sha256"] = sha256_file(patch_path)
            try:
                with open(patch_path, encoding="utf-8-sig") as fh:
                    info["patch_sha256"] = json.load(fh).get("patch_sha256")
            except (OSError, ValueError):
                info["patch_sha256"] = None
        rec["input_patch"] = info
    try:
        import bpy  # noqa: F401  —— 只为了把 Blender 版本也记进去
        rec["blender"] = ".".join(str(v) for v in bpy.app.version)
    except Exception:                                   # noqa: BLE001 — 不在 Blender 里也能写记录
        rec["blender"] = None

    sys.path.insert(0, TREE)
    from mmdpipe import stage  # noqa: E402   —— 先按指定树导入并占住 sys.modules

    stage_path = stage.__file__
    inside = norm(stage_path).startswith(norm(TREE) + os.sep)
    rec["stage_file"] = stage_path
    rec["stage_sha256"] = sha256_file(stage_path)
    rec["stage_inside_tree"] = inside
    print("MMDPIPE_TREE = %s" % TREE)
    print("stage.py     = %s" % stage_path)
    print("stage.py sha = %s" % rec["stage_sha256"])
    try:
        from mmdpipe import mask as mask_mod  # noqa: E402
        rec["mask_file"] = mask_mod.__file__
        rec["mask_sha256"] = sha256_file(mask_mod.__file__)
        print("mask.py      = %s" % rec["mask_file"])
        print("mask.py  sha = %s" % rec["mask_sha256"])
    except ImportError:
        rec["mask_file"] = None
        rec["mask_sha256"] = None
        print("mask.py      = 不存在（这棵树没有掩码通道）")

    write_json(ident_path, rec)          # 开跑之前先落一份：崩了也留得下
    print("IDENTITY 记录 = %s" % ident_path)

    if not inside:
        rec["outcome"] = "aborted:stage_outside_tree"
        write_json(ident_path, rec)
        print("ABORT 导入的 stage.py 不在 MMDPIPE_TREE 之下——拒绝出 .blend")
        return 2

    if os.environ.get("M02_BUILD_DRYRUN") == "1":
        rec["outcome"] = "dryrun:身份记录已写，未跑重建"
        write_json(ident_path, rec)
        print("DRYRUN 只写了身份记录，没有跑重建")
        return 0

    rec["outcome"] = "started"
    write_json(ident_path, rec)
    # v3 结尾是 `os._exit(0)`：不拦就掐死进程，identity 永远停在 `started`。
    # 拦成 SystemExit 之后，终态由这里写，退出码也由这里给（Blender 的 0 不可信）。
    real_os_exit = os._exit
    os._exit = _guarded_os_exit
    try:
        sys.argv = [V3] + ["--"] + argv
        runpy.run_path(V3, run_name="__main__")
        rec["outcome"] = "completed"
        rec["exit_code"] = 0
    except SystemExit as exc:
        # v3 自己调 `sys.exit(0)` 是正常收工；非 0 才是它判了「不能出」。
        # `v3_os_exit:0` 是 v3 的 `os._exit(0)`——正常收工，但**必须**在记录里可区分。
        code = exc.code
        rec["outcome"] = "os_exit:%r" % (code,) if isinstance(code, str) and code.startswith("v3_os_exit") \
            else "sys_exit:%r" % (code,)
        normal = code in (0, None)
        if isinstance(code, str) and code.startswith("v3_os_exit:"):
            normal = code.split(":")[-1] in ("0", "None")
        rec["exit_code"] = 0 if normal else 1
        rec["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        write_json(ident_path, rec)
        if not normal:
            raise
    except BaseException as exc:                    # noqa: BLE001 — 任何异常都要进记录再抛
        rec["outcome"] = "raised:%s" % type(exc).__name__
        rec["exit_code"] = 1
        rec["error"] = str(exc)[:2000]
        rec["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        write_json(ident_path, rec)
        raise
    finally:
        os._exit = real_os_exit
    rec["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    write_json(ident_path, rec)
    return 0


if __name__ == "__main__":
    sys.exit(main())
