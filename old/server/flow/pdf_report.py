"""把运行报告渲染成 PDF（含失败证据截图）。reportlab，内置 CJK 字体支持中文。"""
from __future__ import annotations

import os

from ..i18n import tr

_FONT = "STSong-Light"   # reportlab 内置 Adobe CJK 字体（中文）
_font_ready = False


def _ensure_font():
    global _font_ready
    if _font_ready:
        return
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    pdfmetrics.registerFont(UnicodeCIDFont(_FONT))
    _font_ready = True


def build_pdf(report: dict, out_path: str, title: str, run_dir: str, lang: str = "zh") -> None:
    """report: Report.to_dict()；run_dir: 证据 PNG 所在目录。"""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)

    _ensure_font()
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontName=_FONT, fontSize=18)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName=_FONT, fontSize=13)
    body = ParagraphStyle("body", parent=styles["Normal"], fontName=_FONT, fontSize=10, leading=14)

    passed = report.get("passed")
    story = []
    story.append(Paragraph(title, h1))
    status = tr(lang, "report.passed", "通过") if passed else tr(lang, "report.failed", "失败")
    summary = (f'{tr(lang, "report.result", "结果")}：<b>{"✅" if passed else "❌"} {status}</b>　'
               f'{tr(lang, "report.assertions", "断言")} '
               f'{report.get("total", 0) - report.get("failed", 0)}/{report.get("total", 0)} '
               f'{tr(lang, "report.passed", "通过")}　'
               f'{tr(lang, "report.duration", "耗时")} {report.get("duration", 0)}s')
    if report.get("error"):
        summary += f'　{tr(lang, "report.error", "错误")}：{report["error"]}'
    story.append(Paragraph(summary, body))
    story.append(Spacer(1, 0.4 * cm))

    # 断言表
    asserts = report.get("asserts", [])
    if asserts:
        story.append(Paragraph(tr(lang, "report.assertions", "断言"), h2))
        data = [["#", tr(lang, "report.result", "结果"),
                 tr(lang, "report.message", "消息"), tr(lang, "report.node", "节点")]]
        for idx, a in enumerate(asserts, 1):
            data.append([str(idx), tr(lang, "report.passed", "通过") if a["ok"] else tr(lang, "report.failed", "失败"),
                         a.get("message") or "", str(a.get("node"))])
        t = Table(data, colWidths=[1 * cm, 2 * cm, 10 * cm, 2 * cm])
        ts = TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), _FONT), ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ])
        for i, a in enumerate(asserts, 1):
            ts.add("TEXTCOLOR", (1, i), (1, i),
                   colors.green if a["ok"] else colors.red)
        t.setStyle(ts)
        story.append(t)
        story.append(Spacer(1, 0.4 * cm))

    # 失败证据（截图）
    evid = [(i + 1, a) for i, a in enumerate(asserts) if not a["ok"] and a.get("evidence")]
    evid += [(None, e) for e in report.get("errors", []) if e.get("evidence")]
    if evid:
        story.append(Paragraph(tr(lang, "report.failure_evidence", "失败证据"), h2))
        for idx, item in evid:
            cap = item.get("message") or item.get("evidence") or tr(lang, "report.evidence", "证据")
            story.append(Paragraph(f'· {cap}', body))
            img = _evidence_image(run_dir, item.get("evidence"), ImageReader, Image, cm)
            if img is not None:
                story.append(img)
            story.append(Spacer(1, 0.3 * cm))

    # 错误
    if report.get("errors"):
        story.append(Paragraph(tr(lang, "report.node_errors", "节点错误"), h2))
        for e in report["errors"]:
            story.append(Paragraph(
                f'· {tr(lang, "report.node_error_line", "节点 {node}: {message}", node=e.get("node"), message=e.get("message"))}',
                body))
        story.append(Spacer(1, 0.3 * cm))

    # 日志
    if report.get("logs"):
        story.append(Paragraph(tr(lang, "report.logs", "日志"), h2))
        for line in report["logs"]:
            story.append(Paragraph(_esc(line), body))

    SimpleDocTemplate(out_path, pagesize=A4,
                      topMargin=1.5 * cm, bottomMargin=1.5 * cm).build(story)


def _evidence_image(run_dir, evidence_url, ImageReader, Image, cm):
    if not evidence_url:
        return None
    path = os.path.join(run_dir, os.path.basename(evidence_url))
    if not os.path.exists(path):
        return None
    try:
        iw, ih = ImageReader(path).getSize()
        max_w = 14 * cm
        w = min(max_w, iw)
        h = w * ih / iw
        return Image(path, width=w, height=h)
    except Exception:
        return None


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
