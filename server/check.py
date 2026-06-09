"""脚本节点的语法检查：用 Python 内置 compile() 校验纯语法。

与补全不同，这里直接编译用户原始代码(不加前导)，所以报告的 line/col 与编辑器
行号一一对应。compile 只在第一个语法错误处停下，故最多返回一条。

col/end_col 均为 1 基；end 为出错片段的结束(开区间)，用于前端精确标注列范围。
"""
from __future__ import annotations

from .i18n import tr


def check_syntax(code: str, lang: str = "zh") -> list[dict]:
    """返回 [{line, col, end_line, end_col, message}]；无语法错误则空列表。"""
    try:
        compile(code or "", "<script-node>", "exec")
        return []
    except SyntaxError as e:   # 含 IndentationError / TabError
        line = e.lineno or 1
        col = e.offset or 1
        return [{
            "line": line,
            "col": col,
            "end_line": e.end_lineno or line,
            "end_col": e.end_offset or (col + 1),   # 缺失时标一个字符宽
            "message": e.msg or tr(lang, "api.syntax_error", "语法错误"),
        }]
    except Exception as e:     # 如源码含空字节(ValueError) 等，无定位信息
        return [{"line": 1, "col": 1, "end_line": 1, "end_col": 2,
                 "message": str(e) or tr(lang, "api.syntax_error", "语法错误")}]
