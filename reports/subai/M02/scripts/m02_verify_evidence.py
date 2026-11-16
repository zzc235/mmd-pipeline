"""核验一笔 evidence 文件：重算 artifacts 与 files 的哈希，报告任何不符。

    python m02_verify_evidence.py <evidence.json> [<repo-worktree>]

文本按 `hash_basis` 归一（`lf_normalized_v1` ⇒ 先 `\\r\\n → \\n`）；二进制原样。
`files[]` 从 `git show <基准>:<path>` 取 blob；**基准默认是证据自己记的 `commit` 字段**，
其次才是分支 HEAD（`--head` 可覆盖）。三点式同样以该基准算 `main...<基准>`。

规范实现 `coordination.evidence` 默认取自 **main 树**（`E:\\dsh pr\\woker2`），
可用 `M02_EVIDENCE_TREE` 覆盖——默认指分支 worktree 会让正确记录被算成不规范（`D-147`）。

退出码（2026-11-16 改，理由见下）：
    0 = 全部相符
    1 = **算出来了但不等**（MISMATCH）
    2 = **算不出来**（git 调不动 / 解码失败 / blob 缺失 / 参数错）

为什么把「算不出」和「不等」分开：3号 指出原来这脚本两种情况的退出码都是 1，
而解码失败时 `proc.stdout` 是 `None`——`None.strip()` 抛异常、被外层看成「不一致」，
于是**「我没算」与「它不对」长得一模一样**。证据核验器在这上面出错，比被核的证据出错更坏：
它会把「验不了」静默记成「验过了，有问题」，再被人当成一条结论引用。
所以两处 `text=True` 全部显式 `encoding="utf-8"`，取 `.stdout` 前先判 `None`，
`git` 的 `returncode` 也一并检查（原来只看 `stdout` 非空——git 报错时那句错误文本会被当成 HEAD）。
"""
import hashlib
import json
import os
import subprocess
import sys

# 规范实现（`coordination.evidence`）必须取**权威那一份**：main 树。
# 原来默认指向 `E:\code\mmdpipe-ai\A1`（我的分支），于是重算用的是我分支那份旧实现，
# 一份已被验收的记录会被算成「不规范」——这正是 `D-147`（把别的 worktree 插到
# `sys.path` 前面，跑的不是你以为的那份代码），而这次犯在我自己的仪器上。
# 仍旧允许 `M02_EVIDENCE_TREE` 覆盖（要复现历史记录时才需要），但会把它印出来。
TREE = os.environ.get("M02_EVIDENCE_TREE") or r"E:\dsh pr\woker2"
sys.path.insert(0, TREE)
from coordination import evidence  # noqa: E402

print("规范实现取自: %s" % TREE)

ROOT = r"E:\dsh pr\woker2"
TEXT_EXT = {".py", ".json", ".md", ".jsonl", ".txt", ".toml", ".cfg"}

EXIT_OK, EXIT_MISMATCH, EXIT_CANNOT = 0, 1, 2


class CannotVerify(Exception):
    """算不出来：不是「不符」，是「没算」。"""


def digest(path, basis):
    data = open(path, "rb").read()
    ext = os.path.splitext(path)[1].lower()
    if basis == "lf_normalized_v1" and ext in TEXT_EXT:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def three_bases(path):
    """`D-136`：同一份文件在三种口径下的 sha256，三个都印出来。

    为什么必须三个一起印：今天有过一次「按 raw 算不等、按声明的 `lf_normalized_v1` 算相等」——
    验收方按 raw 比就会退回一份完全正确的记录。**口径写在数旁边，读的人不必猜。**
    `crlf` 是「如果这份文件全用 CRLF 会得到什么」，所以先归一到 LF 再转 CRLF（不双重转义）。
    """
    data = open(path, "rb").read()
    lf = data.replace(b"\r\n", b"\n")
    return {
        "bytes": len(data),
        "raw": hashlib.sha256(data).hexdigest(),
        "lf_normalized": hashlib.sha256(lf).hexdigest(),
        "crlf": hashlib.sha256(lf.replace(b"\n", b"\r\n")).hexdigest(),
    }


def report_three_bases(label, path, recorded):
    """印三个口径，并指出记录里那一份落在哪个口径上（都不落就是真的不符）。"""
    t = three_bases(path)
    hit = [k for k in ("raw", "lf_normalized", "crlf") if t[k] == recorded]
    print("  三口径 %s（%d B）raw=%s lf=%s crlf=%s 记录命中=%s"
          % (label, t["bytes"], t["raw"][:12], t["lf_normalized"][:12], t["crlf"][:12],
             ",".join(hit) if hit else "无（三种都对不上）"))


def git(worktree, *args):
    """跑一条 git，返回 (returncode, bytes)。不解码——调用方要文本自己解。"""
    proc = subprocess.run(["git", "-C", worktree] + list(args), capture_output=True)
    return proc.returncode, proc.stdout


def git_text(worktree, *args, **kw):
    """跑一条 git 并显式按 UTF-8 解码。`allow_empty=True` 用于「空输出本身合法」的场景
    （例：分支与 main 已完全合并时 `git diff --name-only main...HEAD` 就是空的）。"""
    rc, raw = git(worktree, *args)
    if rc != 0:
        raise CannotVerify("git %s 失败（exit %d）" % (" ".join(args), rc))
    if raw is None:
        raise CannotVerify("git %s 没有输出" % " ".join(args))
    text = raw.decode("utf-8", "replace").strip()   # 显式解码，且不再经过本地编码
    if not text and not kw.get("allow_empty"):
        raise CannotVerify("git %s 输出为空" % " ".join(args))
    return text


def main():
    args = [a for a in sys.argv[1:]]
    expect_digest = None
    expect_bytes = None
    head_override = None
    positional = []
    i = 0
    while i < len(args):
        if args[i] == "--expect-digest" and i + 1 < len(args):
            expect_digest = args[i + 1].strip()
            i += 2
            continue
        if args[i] == "--expect-bytes" and i + 1 < len(args):
            expect_bytes = int(args[i + 1])
            i += 2
            continue
        if args[i] == "--head" and i + 1 < len(args):
            head_override = args[i + 1].strip()
            i += 2
            continue
        positional.append(args[i])
        i += 1
    if not positional:
        print("用法: python m02_verify_evidence.py <evidence.json> [<worktree>] "
              "[--expect-digest evidence/1:…] [--expect-bytes N] [--head <rev>]")
        return EXIT_CANNOT
    ev_path = positional[0]
    worktree = positional[1] if len(positional) > 1 else r"E:\code\mmdpipe-ai\A1"
    try:
        raw = open(ev_path, "rb").read()
        ev = json.loads(raw)
        basis = ev.get("hash_basis") or "raw_bytes_v1"
        # 「磁盘上这份就是规范字节」是比 rederive 更强的一条：字节自己哈希出来必须等于记录的 digest
        file_digest = hashlib.sha256(raw).hexdigest()
        # 证据文自己也是文本件：三口径一并印（`D-136`），别让验收方猜我用的是哪一种
        report_three_bases(os.path.basename(ev_path), ev_path, file_digest)
        try:
            rederive_digest, rederive_err = evidence.digest(ev), None
        except Exception as exc:                      # noqa: BLE001 — 规范实现拒收也是一种结论
            rederive_digest, rederive_err = None, "%s: %s" % (type(exc).__name__, exc)

        bad = []
        for entry in ev.get("artifacts") or []:
            path = os.path.join(ROOT, entry["path"])
            if not os.path.exists(path):
                bad.append((entry["path"], "MISSING", entry["sha256"]))
                continue
            got = digest(path, basis)
            if got != entry["sha256"]:
                bad.append((entry["path"], got, entry["sha256"]))
            if os.path.splitext(path)[1].lower() in TEXT_EXT:
                report_three_bases(os.path.basename(path), path, entry["sha256"])

        # 默认用**证据自己记的 commit**（D-099：默认路径必须是正确路径）。
        # 用分支 HEAD 当默认在这里是错的：记录之后还会有新提交，于是正确记录被退回。
        head = head_override or ev.get("commit") or git_text(worktree, "rev-parse", "--short", "HEAD")
        head_source = ("--head" if head_override else
                       "证据 commit 字段" if ev.get("commit") else "分支 HEAD（证据没记 commit）")
        print("核验基准: %s（来源：%s）" % (head, head_source))
        print("规范实现: %s  sha256=%s"
              % (getattr(evidence, "__file__", "?"),
                 hashlib.sha256(open(evidence.__file__, "rb").read()).hexdigest()[:12]))
        bad_files = []
        for entry in ev.get("files") or []:
            rc, data = git(worktree, "show", "%s:%s" % (head, entry["path"]))
            if rc != 0 or not data:
                bad_files.append((entry["path"], "NO BLOB", entry["sha256"]))
                continue
            got = hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
            if got != entry["sha256"]:
                bad_files.append((entry["path"], got, entry["sha256"]))
        # 三点式同样以**核验基准**为准，而不是分支当前 HEAD
        diff = git_text(worktree, "diff", "--name-only", "main...%s" % head, allow_empty=True).split()
    except CannotVerify as exc:
        print("CANNOT VERIFY:", exc)
        return EXIT_CANNOT
    except (OSError, ValueError, KeyError) as exc:
        print("CANNOT VERIFY:", type(exc).__name__, exc)
        return EXIT_CANNOT

    print("evidence:", os.path.basename(ev_path), "attempt", ev.get("attempt"),
          "basis", basis, "artifacts", len(ev.get("artifacts") or []),
          "files", len(ev.get("files") or []))
    print("worktree HEAD:", head, "| three-dot diff:", diff)
    print("files[] == three-dot:", sorted(e["path"] for e in ev.get("files") or []) == sorted(diff))
    if not diff and (ev.get("files") or []):
        # 合并之后三点式必然是空的，这一行此时不具判别力——别让它读成「files[] 是假的」。
        print("  注：三点式为空而 files[] 非空 ⇒ 该提交已被 main 吸收；"
              "此时判据是下面逐条 blob 哈希，不是这一行。")
    rederived_hex = (rederive_digest or "").split(":", 1)[-1]
    print("磁盘字节即规范字节: %s（文件 %d B，sha %s）"
          % (file_digest == rederived_hex, len(raw), file_digest))
    if rederive_err:
        print("规范实现复现: CANNOT ——", rederive_err)
    else:
        print("规范实现复现: %s（%s）" % (rederived_hex == file_digest, rederive_digest))
    expect_ok = True
    if expect_digest is not None:
        want = expect_digest.split(":", 1)[-1]
        expect_ok = file_digest == want
        print("预期 digest: %s（%s）" % (expect_digest, "对上" if expect_ok else "不等"))
    if expect_bytes is not None:
        size_ok = len(raw) == expect_bytes
        expect_ok = expect_ok and size_ok
        print("预期字节数: %d（实 %d，%s）" % (expect_bytes, len(raw), "对上" if size_ok else "不等"))
    print("artifact mismatches:", len(bad))
    for row in bad:
        print("  MISSING/MISMATCH", row)
    print("files mismatches:", len(bad_files))
    for row in bad_files:
        print("  MISMATCH", row)
    if bad or bad_files or not expect_ok:
        return EXIT_MISMATCH
    if rederive_err:
        return EXIT_CANNOT
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
