"""把 M03 的附录 A 追加到共享工作区的 M03 任务书末尾（幂等）。

第一次运行：截掉旧的「## 8. 执行回写」临时块，换成统一格式的「附录 A」。
再次运行：若已存在「附录 A · 执行记录」，只替换附录 A 之后的内容，不重复堆叠。
"""
import io
import os
import sys

BOOK = r"C:\Users\zzc\Desktop\ai用\dsh use\gongtonggzq\M03_归因判据自动化与坏样本标签.md"
APPENDIX = r"E:\dsh pr\woker2\reports\subai\M03\appendix_for_book.md"

MARKERS = ("\n---\n\n## 8. 执行回写", "\n---\n\n# 附录 A · 执行记录")


def main() -> int:
    with io.open(BOOK, encoding="utf-8") as fh:
        text = fh.read()
    with io.open(APPENDIX, encoding="utf-8") as fh:
        appendix = fh.read().rstrip("\n")

    cut = None
    for marker in MARKERS:
        idx = text.find(marker)
        if idx != -1:
            cut = idx
            break
    if cut is None:
        base = text.rstrip("\n")
    else:
        base = text[:cut].rstrip("\n")

    result = base + "\n\n---\n\n" + appendix + "\n"
    with io.open(BOOK, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(result)
    print("book bytes:", len(result.encode("utf-8")))
    print("headings:")
    for line in result.splitlines():
        if line.startswith("# ") or line.startswith("## "):
            print("  ", line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
