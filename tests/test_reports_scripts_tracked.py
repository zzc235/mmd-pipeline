# -*- coding: utf-8 -*-
"""`reports/subai/**/scripts/` 的镜像清单必须与仓里的文件逐一对上。

钉的是什么（`claim_shape_rules.md` 第十三条，2026-11-16 立）：

* 那次的形状是「报告引用的脚本/日志只存在于工作树」——**工作树永远有、干净 checkout 永远没有**，
  于是账本看着完整、复现时什么都没有（`2号` 的 `compare.log`、`3号` 的六个控制脚本）；
* 所以脚本镜像进仓、读数留在产物树，两边在报告里成对引用；
* 本测试盯三件事：**目录里每个文件都在清单里**、**清单里每个文件都在仓里**、
  **清单里的 sha256 与文件内容一致**。多一个、少一个、改一个字节都会红。

反控：解析器本身要能抓住「清单里有、盘上没有」和「盘上有、清单里没有」两种漂移 ——
否则这三条断言等于没跑。
"""
import hashlib
import io
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIRRORS = (("reports/subai/M00/scripts", "reports/subai/M00/scripts/README.md"),
           ("reports/subai/M07/scripts", "reports/subai/M00/scripts/README.md"))
ROW = re.compile(r"^\|\s*`(?P<path>M0[07]/scripts/[^`]+)`\s*\|\s*`(?P<sha>[0-9a-f]{16})…`", re.M)


def sha256_lf(path):
    """文本哈希基数 `lf_normalized_v1`：先把 `\\r\\n` 归一成 `\\n` 再算（与全项目一致）。"""
    with io.open(path, "rb") as fh:
        raw = fh.read()
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def parse_manifest(text):
    """从 README 的表格里取出 `{相对路径: sha256 前 16 位}`。"""
    return {m.group("path"): m.group("sha") for m in ROW.finditer(text)}


def drift(manifest, on_disk):
    """两个方向都算：清单里没有的、盘上没有的。"""
    return {"missing_on_disk": sorted(set(manifest) - set(on_disk)),
            "missing_in_manifest": sorted(set(on_disk) - set(manifest))}


class TestScriptMirrorIsTracked(unittest.TestCase):
    def setUp(self):
        with io.open(os.path.join(ROOT, "reports/subai/M00/scripts/README.md"),
                     encoding="utf-8") as fh:
            self.manifest = parse_manifest(fh.read())

    def test_every_mirrored_file_is_listed_and_every_listed_file_exists(self):
        on_disk = []
        for folder, _ in MIRRORS:
            full = os.path.join(ROOT, folder)
            for name in sorted(os.listdir(full)):
                if name.endswith(".py"):
                    on_disk.append("%s/%s" % (folder.split("/subai/")[1], name))
        self.assertEqual(drift(self.manifest, on_disk),
                         {"missing_on_disk": [], "missing_in_manifest": []},
                         "镜像目录与 README 清单对不上：%r" % (drift(self.manifest, on_disk),))

    def test_every_listed_sha256_matches_the_file(self):
        for rel, want in sorted(self.manifest.items()):
            path = os.path.join(ROOT, "reports/subai", rel)
            self.assertTrue(os.path.isfile(path), "清单里的文件不在仓里：%s" % rel)
            got = sha256_lf(path)[:16]
            self.assertEqual(got, want,
                             "%s 的 sha256 与清单不符（改过就要同时更新清单与 out/ 那份）" % rel)

    def test_the_manifest_parser_catches_drift_both_ways(self):
        """反控：解析器抓得住两种漂移，否则上面两条是空断言。"""
        text = ("| `M00/scripts/a.py` | `0123456789abcdef…` | x |\n"
                "| `M00/scripts/b.py` | `fedcba9876543210…` | y |\n")
        manifest = parse_manifest(text)
        self.assertEqual(sorted(manifest), ["M00/scripts/a.py", "M00/scripts/b.py"])
        # 盘上少了 b、多了 c
        found = drift(manifest, ["M00/scripts/a.py", "M00/scripts/c.py"])
        self.assertEqual(found["missing_on_disk"], ["M00/scripts/b.py"])
        self.assertEqual(found["missing_in_manifest"], ["M00/scripts/c.py"])

    def test_readme_is_itself_tracked_by_the_mirror_convention(self):
        """README 不进清单（它不含读数），但必须在仓里 —— 否则清单没地方读。"""
        self.assertTrue(os.path.isfile(
            os.path.join(ROOT, "reports/subai/M00/scripts/README.md")))


if __name__ == "__main__":
    unittest.main()
