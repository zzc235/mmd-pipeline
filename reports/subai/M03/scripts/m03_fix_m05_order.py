"""修一次 M05 任务书里的追加顺序冲突（幂等）。

背景：M03 追加 A.8 的同时，M05 会话又往 A.7 表格末尾补了一行，于是那一行
落到了 A.8 后面，把表格和补充段切开了。本脚本把它移回 A.7 表格里。

只动这一行，不碰任何正文。已经修过就什么都不做。
"""
import io
import sys

BOOK = r"C:\Users\zzc\Desktop\ai用\dsh use\gongtonggzq\M05_三段拼接丢帧与NLA坏姿态.md"
ROW_PREFIX = "| `out/subai/M05/chain_baseline_overlap.vmd`"
A8_MARK = "## A.8 补充 · 锁状态更新"
ANCHOR_PREFIX = "| `out/subai/M05/make_fixtures.py`"


def main() -> int:
    with io.open(BOOK, encoding="utf-8") as fh:
        lines = fh.read().split("\n")

    a8 = next((i for i, ln in enumerate(lines) if ln.startswith(A8_MARK)), None)
    row_at = [i for i, ln in enumerate(lines) if ln.startswith(ROW_PREFIX)]
    if a8 is None or not row_at:
        print("nothing to do (a8=%r rows=%r)" % (a8, row_at))
        return 0
    stray = [i for i in row_at if i > a8]
    if not stray:
        print("already ordered; rows at", row_at)
        return 0
    row = lines.pop(stray[0])
    anchor = next(i for i, ln in enumerate(lines) if ln.startswith(ANCHOR_PREFIX))
    lines.insert(anchor + 1, row)
    with io.open(BOOK, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    print("moved row from", stray[0], "to", anchor + 1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
