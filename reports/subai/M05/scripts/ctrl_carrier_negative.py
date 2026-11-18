"""负控：豁免条目把**载体**指到一个仓里没有的路径，`verify_report_numbers.py` 必须红。

`4号` 20:23 的观点：理由里写 `plan_324.json` 四个字就能过，等于把「豁免理由」变成新一版散文，
而散文不能拿来断言。载体于是被收成 `{"kind": "git"|"out"|"input", "path": …}` 的 schema，
`kind: git` 必须过 `git ls-files --error-unmatch`。这条负控证明那个判定真的会咬人。

**第一版写错过一次，错的地方比结论值钱**：当时把改过的校验器落到系统临时目录里跑，
而校验器是从 `__file__` 往上找 `coordination/` + `mmdpipe/` 定 `ROOT` 的 —— 临时目录往上走到顶
也没有那两个目录，于是它**在读到任何断言之前**就 `SystemExit` 了：退出码 1，但没有 `carrier … MISMATCH` 那一行。
判定式当时只要求「退出码 == 1」，于是会把这个「早期崩溃」读成「拦截成功」。两条教训：

1. 负控必须与被测件跑在**同一命名空间**里 —— 副本落回本目录（能自解析 `ROOT` 的位置），`finally` 里删；
2. **「退出码 1」不是证据，「哪一行红了」才是** —— 判据里带上具体行，且要求被改的那一条**恰好**红。

    python reports/subai/M05/scripts/ctrl_carrier_negative.py
    退出码：0 负控成立（假载体被判红）/ 1 负控不成立
"""
import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "verify_report_numbers.py")
DST = os.path.join(HERE, "_neg_carrier_tmp.py")  # 同目录 ⇒ ROOT 解析与正身完全一致


def find_repo_root(start):
    cur = os.path.abspath(start)
    while True:
        if (os.path.isdir(os.path.join(cur, "coordination"))
                and os.path.isdir(os.path.join(cur, "mmdpipe"))):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            raise SystemExit("从 %s 往上走到顶也没找到 coordination/ 与 mmdpipe/" % start)
        cur = parent


ROOT = find_repo_root(HERE)

OLD = '"path": "reports/subai/M05/arms_audit_324.json"'
NEW = '"path": "reports/subai/M05/no_such_carrier_aux.json"'  # 仓里没有，git 也不认


def main():
    text = io.open(SRC, encoding="utf-8").read()
    if OLD not in text:
        raise SystemExit("找不到要改的 carrier.path：%s" % OLD)
    patched = text.replace(OLD, NEW, 1)
    if patched == text:
        raise SystemExit("替换没生效")
    ok = False
    try:
        io.open(DST, "w", encoding="utf-8", newline="\n").write(patched)
        p = subprocess.run([sys.executable, DST], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        out = (p.stdout or "") + (p.stderr or "")
        # 判据要具体：不是「退出码非 0」，而是这一行、这个路径、got=False
        hit = [ln for ln in out.splitlines() if "carrier" in ln and "MISMATCH" in ln]
        print("exit=%d" % p.returncode)
        for ln in hit:
            print("  " + ln.strip())
        if not hit:
            print("（没有 carrier MISMATCH 行，原样打出尾部——早期崩溃也会是退出码 1，别把它读成通过）")
            for ln in out.splitlines()[-6:]:
                print("  " + ln.strip())
        ok = p.returncode == 1 and len(hit) == 1 and "manifest.json" in hit[0]
    finally:
        if os.path.exists(DST):
            os.remove(DST)  # 中途红了也不留垃圾
    print("CONTROL %s" % ("OK（假载体被判红，且只红这一条）" if ok
                          else "FAILED（假载体没被判红，或者红成了别的样子）"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
