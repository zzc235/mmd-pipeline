"""反向控制：把 `fcurves_of` 退回旧写法（无兼容层），新增的 5 条必须红。

临时改文件 → 跑测试 → **无论结果都还原**。还原后再跑一遍证明是绿的。
"""
import io
import os
import subprocess
import sys

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
TARGET = os.path.join(ROOT, "mmdpipe", "apply_action.py")

ORIG = io.open(TARGET, encoding="utf-8").read()

LEGACY = '''def fcurves_of(action):
    """BREAKED ON PURPOSE（反向控制用）。"""
    return list(action.fcurves), "action.fcurves"
'''

START = "def fcurves_of(action):"
END = "class FcurveShapeError(RuntimeError):"
STUB_MARK = "BREAKED ON PURPOSE"
# 反向控制是**替换** `fcurves_of` 的实现，不是删函数 ⇒ 顶层符号集合必须一个不少。
EXPECT_REMOVED = set()


def top_level_symbols(text):
    """模块顶层 `def`/`class` 名字 —— 用来核对「切片到底删掉了什么」。"""
    names = set()
    for line in text.splitlines():
        for kw in ("def ", "class "):
            if line.startswith(kw):
                names.add(line[len(kw):].split("(")[0].split(":")[0].strip())
    return names


# 自检一：起止标记各只出现一次（标记重复 = 切片范围不是你以为是的那段）
assert ORIG.count(START) == 1, "起点标记出现 %d 次" % ORIG.count(START)
assert ORIG.count(END) == 1, "终点标记出现 %d 次" % ORIG.count(END)
assert ORIG.index(START) < ORIG.index(END), "起点在终点之后"
# 自检二：切片只许少一个符号，且必须正是 `fcurves_of`
#（2026-11-16 真栽过：终点停在 `def _trim_action(` 时，插进去的写侧三个函数会被一起删掉，
#  而脚本报出来的仍是「控制生效了（红了很多条）」—— 控制脚本按文本切片改代码，
#  插函数就会悄悄扩大它的作用域。）
start = ORIG.index(START)
end = ORIG.index(END)
patched = ORIG[:start] + LEGACY + "\n\n" + ORIG[end:]

removed = top_level_symbols(ORIG) - top_level_symbols(patched)
assert removed == EXPECT_REMOVED, "切片删掉的符号是 %r，预期只有 %r" % (
    sorted(removed), sorted(EXPECT_REMOVED))
# 自检三：写侧那四件必须还在（否则「退回旧写法」变成「把新实现也删了」）
for keep in ("_channelbags_of", "fcurve_container", "ensure_fcurve", "FcurveShapeError"):
    assert "def %s(" % keep in patched or "class %s(" % keep in patched, "被误删：%s" % keep
assert patched != ORIG, "反向控制没改到东西"
try:
    io.open(TARGET, "w", encoding="utf-8", newline="\n").write(patched)
    red = subprocess.run([sys.executable, "-m", "unittest", "tests.test_apply_action"],
                         cwd=ROOT, capture_output=True)
finally:
    io.open(TARGET, "w", encoding="utf-8", newline="\n").write(ORIG)

green = subprocess.run([sys.executable, "-m", "unittest", "tests.test_apply_action"],
                       cwd=ROOT, capture_output=True)

red_tail = red.stderr.decode("utf-8", "replace").strip().splitlines()
green_tail = green.stderr.decode("utf-8", "replace").strip().splitlines()
fails = [ln for ln in red_tail if ln.startswith("FAIL:") or ln.startswith("ERROR:")]

print("旧写法 rc=%d 失败条数=%d" % (red.returncode, len(fails)))
for ln in fails:
    print("  RED", ln)
print("还原后 rc=%d %s" % (green.returncode, green_tail[-1] if green_tail else ""))
print("RESULT", "OK：旧写法红、新写法绿" if red.returncode != 0 and green.returncode == 0
      else "BAD：控制没有区分度")
sys.exit(0 if (red.returncode != 0 and green.returncode == 0) else 1)
