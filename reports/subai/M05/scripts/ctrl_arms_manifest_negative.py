"""负控：这份 manifest 的审计**能不能咬人**。

`D-204/205` 的纪律：校验类代码必须喂一个**应当被拒的输入**、证明它红，再证明它绿。
本脚本在**副本**上做两件该被拒的事，真批次一个字节都不碰：

1. 目录里多一个未登记文件 ⇒ 期望 `only_on_disk`、exit 3；
2. 把一个 `.blend` 改一个字节 ⇒ 期望 `sha_drift`、exit 3。

    python out/subai/M05/ctrl_arms_manifest_negative.py
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

def find_repo_root(start):
    """往上走到有 `coordination/` 与 `mmdpipe/` 的那一层；走不到就把起点打出来再死。

    不写死 `dirname` 次数：同一份脚本既可能在 `out/subai/M05/`（产物树）也可能在
    `reports/subai/M05/scripts/`（仓库），深度不同，写死次数必然有一边算错 ——
    而算错的形状是 `ImportError`，看起来像「这个模块不存在」（`D-228` 规则十二条）。
    """
    cur = os.path.abspath(start)
    while True:
        if (os.path.isdir(os.path.join(cur, "coordination"))
                and os.path.isdir(os.path.join(cur, "mmdpipe"))):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            raise SystemExit("从 %s 往上走到顶也没找到 coordination/ 与 mmdpipe/"
                             % os.path.abspath(start))
        cur = parent
ROOT = find_repo_root(os.path.dirname(os.path.abspath(__file__)))

SRC = os.path.join(ROOT, "out", "subai", "M05", "arms", "20261116_324")
MANIFEST = "manifest.json"
VICTIM = "C@W1-rerun.blend"


def audit(batch_dir):
    p = subprocess.run([sys.executable, "-m", "coordination.artifact_audit",
                        "--manifest", os.path.join(batch_dir, MANIFEST), "--quiet"],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    return p.returncode, (p.stdout + p.stderr).strip()


def fresh_copy(tmp):
    dst = os.path.join(tmp, "batch")
    shutil.copytree(SRC, dst)
    for name in os.listdir(dst):                 # 副本要可写，否则改不动
        full = os.path.join(dst, name)
        os.chmod(full, os.stat(full).st_mode | 0o200)
    return dst


def main():
    if not os.path.exists(os.path.join(SRC, MANIFEST)):
        raise SystemExit("真批次里没有 manifest，先跑 make_arms_manifest.py")
    tmp = tempfile.mkdtemp()
    ok = True
    try:
        code, out = audit(SRC)
        print("[绿] 真批次：exit=%d %s" % (code, out))
        ok &= code == 0

        dst = fresh_copy(tmp)
        with io.open(os.path.join(dst, "STRAY_未登记.txt"), "w", encoding="utf-8") as fh:
            fh.write("没人解释这个文件从哪来\n")
        code, out = audit(dst)
        print("[红-1] 多一个未登记文件：exit=%d %s" % (code, out))
        ok &= code == 3 and "drift=1" in out

        dst2 = fresh_copy(os.path.join(tmp, "two") if os.makedirs(
            os.path.join(tmp, "two"), exist_ok=True) is None else tmp)
        victim = os.path.join(dst2, VICTIM)
        with open(victim, "r+b") as fh:
            fh.seek(1024)
            b = fh.read(1)
            fh.seek(1024)
            fh.write(bytes([b[0] ^ 0xFF]))
        code, out = audit(dst2)
        print("[红-2] 把一个 .blend 改一个字节：exit=%d %s" % (code, out))
        ok &= code == 3 and "drift=1" in out

        # 还原后必须回到绿：证明红的来源是那次改动，不是副本本身
        shutil.copy2(os.path.join(SRC, VICTIM), victim)
        code, out = audit(dst2)
        print("[绿-2] 还原该字节后：exit=%d %s" % (code, out))
        ok &= code == 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("CONTROL %s" % ("OK（绿能绿、红能红、还原回绿）" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
