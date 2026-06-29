"""测试运行报告：断言结果 + 节点错误 + 失败证据(截图) + 日志；可导出 JSON/JUnit。"""
from __future__ import annotations

import time
from xml.sax.saxutils import escape, quoteattr

from ..i18n import tr


class Report:
    def __init__(self):
        self.started = time.time()
        self.finished = None
        self.asserts: list[dict] = []
        self.errors: list[dict] = []
        self.logs: list[str] = []
        self.error: str | None = None

    def add_assert(self, ok: bool, message: str, node_id, evidence: str | None = None) -> None:
        self.asserts.append({
            "ok": bool(ok), "message": message or "", "node": node_id,
            "evidence": evidence,
        })

    def add_error(self, node_id, message: str, evidence: str | None = None) -> None:
        self.errors.append({"node": node_id, "message": message, "evidence": evidence})

    def log(self, text: str) -> None:
        self.logs.append(str(text))

    def finalize(self, error: str | None = None) -> None:
        self.finished = time.time()
        self.error = error

    @property
    def duration(self) -> float:
        return round((self.finished or time.time()) - self.started, 3)

    @property
    def passed(self) -> bool:
        return self.error is None and not self.errors and all(a["ok"] for a in self.asserts)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "error": self.error,
            "duration": self.duration,
            "asserts": self.asserts,
            "errors": self.errors,
            "total": len(self.asserts),
            "failed": sum(1 for a in self.asserts if not a["ok"]),
            "logs": self.logs,
        }

    def to_junit(self, suite_name: str = "flow", lang: str = "zh") -> str:
        n = len(self.asserts)
        failures = sum(1 for a in self.asserts if not a["ok"])
        errors = len(self.errors)
        out = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<testsuite name={quoteattr(suite_name)} tests="{n}" '
            f'failures="{failures}" errors="{errors}" time="{self.duration}">',
        ]
        for a in self.asserts:
            name = a["message"] or f'assert@node{a["node"]}'
            out.append(f'  <testcase classname="node{a["node"]}" name={quoteattr(name)}>')
            if not a["ok"]:
                detail = tr(lang, "report.assert_failed", "断言失败")
                if a.get("evidence"):
                    detail += f"\n{tr(lang, 'report.evidence', '证据')}: {a['evidence']}"
                out.append(f'    <failure message={quoteattr(name)}>{escape(detail)}</failure>')
            out.append("  </testcase>")
        for e in self.errors:
            out.append(f'  <testcase classname="node{e["node"]}" name="error">')
            detail = e["message"] + (
                f"\n{tr(lang, 'report.evidence', '证据')}: {e['evidence']}" if e.get("evidence") else "")
            out.append(f'    <error message={quoteattr(e["message"][:120])}>{escape(detail)}</error>')
            out.append("  </testcase>")
        if self.error and not self.errors:
            out.append('  <testcase classname="run" name="run">')
            out.append(f'    <error message={quoteattr(self.error)}>{escape(self.error)}</error>')
            out.append("  </testcase>")
        out.append("</testsuite>")
        return "\n".join(out)
