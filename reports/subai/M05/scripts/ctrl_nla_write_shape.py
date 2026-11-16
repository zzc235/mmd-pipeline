"""反向控制：把 `chain_nla._shift_b_action` 退回「直接写 `action.fcurves`」的旧写法，
新测试必须**红**；还原后必须**绿**。

为什么要这层：`tests/test_chain_nla_fcurves.py` 里那几条「分层动作也能写」如果没有这个控制，
就只能证明「新代码能跑」，证明不了「新代码是必要的」。跑完自动还原（`finally` 里写回原字节），
工作树回到干净状态 —— 不留半改的文件。
"""
import subprocess
import sys

import os
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
REPO = ROOT          # 本脚本早期版本用这个名字，保留别名，别让两条路径各说各的
TARGET = REPO + r"\mmdpipe\chain_nla.py"

NEW_CALL = """            fc, how = apply_mod.ensure_fcurve(action, arm, path, index=i, group=bone_name)"""
OLD_CALL = """            fc = action.fcurves.find(path, index=i)
            if fc is None:
                fc = action.fcurves.new(path, index=i, action_group=bone_name)
            how = "action.fcurves\""""


def run_tests():
    p = subprocess.run([sys.executable, "-m", "unittest", "tests.test_chain_nla_fcurves"],
                       cwd=REPO, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    tail = [ln for ln in (p.stdout + p.stderr).splitlines()
            if ln.startswith(("Ran ", "OK", "FAILED", "ERROR:", "FAIL:"))]
    return p.returncode, tail


def main():
    with open(TARGET, "rb") as fh:
        original = fh.read()
    text = original.decode("utf-8")
    # 自检一：调用点必须**恰好一处**（两处 ⇒ 换掉一处会让另一半悄悄留着，红条数说不清）
    hits = text.count(NEW_CALL)
    if hits != 1:
        print("控制脚本找到 %d 处新版调用点（预期 1），放弃（不猜）" % hits)
        return 2
    # 自检二：替换前后只许差这一处调用，别顺手改到别的行
    patched = text.replace(NEW_CALL, OLD_CALL, 1)
    if patched.count(OLD_CALL) != 1 or len(patched) == len(text):
        print("替换没有产生预期差异，放弃（不猜）")
        return 2

    print("== 旧写法（分层动作）==")
    try:
        with open(TARGET, "w", encoding="utf-8", newline="") as fh:
            fh.write(patched)
        code, tail = run_tests()
        print("exit=%d" % code)
        for ln in tail:
            print("  " + ln)
        red = code != 0
    finally:
        with open(TARGET, "wb") as fh:
            fh.write(original)
    # 自检三：还原必须是**逐字节**还原，否则下一次跑控制就是基于被改过的文件
    with open(TARGET, "rb") as fh:
        if fh.read() != original:
            print("还原失败：工作树文件与原始字节不同")
            return 2

    print("== 还原后 ==")
    code2, tail2 = run_tests()
    print("exit=%d" % code2)
    for ln in tail2:
        print("  " + ln)

    ok = red and code2 == 0
    print("CONTROL %s" % ("OK（旧写法红、新写法绿）" if ok else "FAILED（没分辨力）"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
