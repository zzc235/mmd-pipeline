"""阶段产物 / 断言 / 问题的统一数据契约。

插件和命令行共用这一套，别处不再自己拼字典。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict

BLOCK = "block"
WARN = "warn"
INFO = "info"


@dataclass
class Issue:
    code: str
    severity: str
    hint: str
    evidence: str = ""

    def line(self) -> str:
        mark = {"block": "×", "warn": "!", "info": "·"}.get(self.severity, "?")
        tail = ("  [%s]" % self.evidence) if self.evidence else ""
        return "%s %-6s %s%s" % (mark, self.code, self.hint, tail)


@dataclass
class StageResult:
    stage: str
    ok: bool = True
    metrics: dict = field(default_factory=dict)
    artifacts: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    elapsed: float = 0.0

    def add(self, code, severity, hint, evidence=""):
        self.issues.append(Issue(code, severity, hint, evidence))
        if severity == BLOCK:
            self.ok = False
        return self

    @property
    def blocked(self) -> bool:
        return any(i.severity == BLOCK for i in self.issues)

    def as_dict(self) -> dict:
        return {
            "stage": self.stage,
            "ok": self.ok,
            "metrics": self.metrics,
            "artifacts": self.artifacts,
            "issues": [asdict(i) for i in self.issues],
            "elapsed": round(self.elapsed, 2),
        }

    def text(self) -> str:
        head = "[%s] %s  (%.1fs)" % ("PASS" if self.ok else "FAIL", self.stage, self.elapsed)
        rows = [head]
        for k, v in self.metrics.items():
            rows.append("    %-22s %s" % (k, v))
        for i in self.issues:
            rows.append("    " + i.line())
        return "\n".join(rows)


def now() -> float:
    return time.time()


def dump(result: StageResult | dict, path: str) -> str:
    payload = result.as_dict() if isinstance(result, StageResult) else result
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path
