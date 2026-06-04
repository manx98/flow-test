"""脚本编辑器：QScintilla + Jedi 语义补全。

补全优先用 Jedi（真正的类型感知：给 Jedi 喂一段类型头，使 `dev.` 精确补出 Device
方法、带签名/文档）。Jedi 不可用时退回 QsciAPIs 静态词库；无 QScintilla 时退回
QPlainTextEdit + 简易 QCompleter。
"""
from __future__ import annotations

from ..qt import Qsci, Qt, QtCore, QtGui, QtWidgets

_DEFAULT_SCRIPT = '''\
# visauto 脚本：dev 已绑定到当前连接，ocr 为会话默认引擎（在 OCR 设置里配置）
# 图片用裸文件名即可（工程 images/ 已加入 ImagePath）

dev.wait("home.png", timeout=10)
dev.click("login.png")
# dev.click(text="提交")          # 配置了默认 OCR 后可省略 ocr=
print("done")
'''

# 喂给 Jedi 的隐藏类型头：声明注入到脚本命名空间里的全局及其类型，
# 这样 `dev.` 能补出 Device(继承 Region) 的方法。分析时拼到用户代码前，行号相应偏移。
_HEADER = (
    "import visauto\n"
    "from visauto import Pattern, Region, Match, Location, Key, Settings, FindFailed\n"
    "dev: visauto.Device\n"
)
_HEADER_LINES = _HEADER.count("\n")  # 3

# Jedi 不可用时的静态补全词库
_API_ENTRIES = [
    "dev", "ocr", "visauto", "Pattern", "Region", "Match", "Location", "Key",
    "Settings", "FindFailed", "print",
    "find(target=None, text=None, regex=False, ocr=None, timeout=None)",
    "find_all(target=None, text=None, regex=False, ocr=None, timeout=None)",
    "exists(target=None, text=None, regex=False, ocr=None, timeout=None)",
    "wait(target=None, text=None, ocr=None, timeout=None)",
    "wait_vanish(target=None, timeout=None)",
    "click(target=None, text=None, ocr=None, timeout=None)",
    "double_click(target=None)", "right_click(target=None)", "hover(target=None)",
    "drag_drop(src, dst)", "scroll(dx, dy, target=None)",
    "type(text, modifiers=None)", "paste(text)", "press_key(key, modifiers=None)",
    "read_text(ocr=None)", "region(x, y, w, h)",
    "on_appear(target, callback)", "on_vanish(target, callback)",
    "on_change(callback)", "observe(timeout=None, background=False)",
    "timeout=", "ocr=", "text=", "regex=", "similarity=", "modifiers=",
]


def _enum(cls, nested, name):
    """取枚举值，兼容 PyQt6 嵌套(cls.Nested.Name)与 PyQt5 扁平(cls.Name)。"""
    ns = getattr(cls, nested, None)
    if ns is not None and hasattr(ns, name):
        return getattr(ns, name)
    return getattr(cls, name)


if Qsci is not None:

    class _CodeEdit(Qsci.QsciScintilla):
        """带 Jedi 补全的 QScintilla 编辑器。"""

        USERLIST_ID = 7

        def __init__(self, parent=None):
            super().__init__(parent)
            lexer = Qsci.QsciLexerPython(self)
            self.setLexer(lexer)
            self.setUtf8(True)
            self.setAutoIndent(True)
            self.setIndentationsUseTabs(False)
            self.setTabWidth(4)
            self.setMarginType(0, _enum(Qsci.QsciScintilla, "MarginType", "NumberMargin"))
            self.setMarginWidth(0, "0000")

            self._comp_prefix_len = 0
            self.userListActivated.connect(self._insert_user_selection)

            # 尝试启用 Jedi
            self._jedi = None
            try:
                import jedi
                self._jedi = jedi
            except Exception:
                self._jedi = None

            if self._jedi is not None:
                # 自己驱动补全：关掉内置自动弹出，靠 keyPressEvent 触发 Jedi
                self.setAutoCompletionThreshold(0)
                self._debounce = QtCore.QTimer(self)
                self._debounce.setSingleShot(True)
                self._debounce.timeout.connect(self._run_jedi)
            else:
                # 退回静态词库
                apis = Qsci.QsciAPIs(lexer)
                for e in _API_ENTRIES:
                    apis.add(e)
                apis.prepare()
                self._apis = apis
                self.setAutoCompletionSource(
                    _enum(Qsci.QsciScintilla, "AutoCompletionSource", "AcsAll"))
                self.setAutoCompletionThreshold(1)
            self.setAutoCompletionCaseSensitivity(False)
            self.setAutoCompletionReplaceWord(False)

        # ---- 触发 ----
        def keyPressEvent(self, e) -> None:
            super().keyPressEvent(e)
            if self._jedi is None:
                return
            t = e.text()
            if t == "." or (t and (t.isalnum() or t == "_")):
                self._debounce.start(120)   # 合并连续按键，120ms 后跑一次 Jedi
            elif not t:
                self._debounce.stop()

        def trigger_complete(self) -> None:
            """Ctrl+Space 手动触发。"""
            if self._jedi is not None:
                self._run_jedi()
            else:
                self.autoCompleteFromAll()

        # ---- Jedi 计算 ----
        def _run_jedi(self) -> None:
            try:
                names, prefix_len = self._jedi_complete()
            except Exception:
                return
            if names:
                self._comp_prefix_len = prefix_len
                self.showUserList(self.USERLIST_ID, names)

        def _jedi_complete(self):
            code = self.text()
            line, col = self.getCursorPosition()        # 0-based
            source = _HEADER + code
            script = self._jedi.Script(source)
            comps = script.complete(line + _HEADER_LINES + 1, col)  # jedi 行 1-based
            names, prefix_len, seen = [], 0, set()
            for c in comps[:80]:
                if c.name in seen or c.name.startswith("__"):
                    continue
                seen.add(c.name)
                names.append(c.name)
                prefix_len = len(c.name) - len(c.complete)
            return names, max(0, prefix_len)

        # ---- 插入选中项（替换已输入前缀）----
        def _insert_user_selection(self, list_id: int, value: str) -> None:
            if list_id != self.USERLIST_ID:
                return
            line, col = self.getCursorPosition()
            start = max(0, col - self._comp_prefix_len)
            self.setSelection(line, start, line, col)
            self.removeSelectedText()
            self.insert(value)
            self.setCursorPosition(line, start + len(value))

else:
    _CodeEdit = None


class ScriptEditor(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if _CodeEdit is not None:
            self._sci = _CodeEdit()
            self._sci.setText(_DEFAULT_SCRIPT)
            Shortcut = getattr(QtGui, "QShortcut", None) or QtWidgets.QShortcut
            sc = Shortcut(QtGui.QKeySequence("Ctrl+Space"), self._sci)
            sc.activated.connect(self._sci.trigger_complete)
            self._editor = self._sci
            self._plain = None
        else:
            self._build_plain()
            self._editor = self._plain
            self._sci = None
        layout.addWidget(self._editor)

    # ---- QPlainTextEdit 退化版 ----
    def _build_plain(self) -> None:
        self._plain = QtWidgets.QPlainTextEdit()
        self._plain.setPlainText(_DEFAULT_SCRIPT)
        font = QtGui.QFont("Monospace")
        if hasattr(QtGui.QFont, "StyleHint"):
            font.setStyleHint(QtGui.QFont.StyleHint.Monospace)
        self._plain.setFont(font)
        words = sorted({e.split("(")[0].split("=")[0] for e in _API_ENTRIES})
        self._completer = QtWidgets.QCompleter(words, self._plain)
        self._completer.setWidget(self._plain)
        self._completer.setCaseSensitivity(_enum(Qt, "CaseSensitivity", "CaseInsensitive"))
        self._completer.activated.connect(self._plain_insert_completion)
        self._plain.keyPressEvent = self._plain_key_press

    def _plain_key_press(self, event) -> None:
        QtWidgets.QPlainTextEdit.keyPressEvent(self._plain, event)
        cursor = self._plain.textCursor()
        sel = (cursor.SelectionType.WordUnderCursor
               if hasattr(cursor, "SelectionType") else cursor.WordUnderCursor)
        cursor.select(sel)
        prefix = cursor.selectedText()
        if len(prefix) >= 1:
            self._completer.setCompletionPrefix(prefix)
            if self._completer.completionCount():
                rect = self._plain.cursorRect()
                rect.setWidth(220)
                self._completer.complete(rect)
                return
        self._completer.popup().hide()

    def _plain_insert_completion(self, text: str) -> None:
        cursor = self._plain.textCursor()
        sel = (cursor.SelectionType.WordUnderCursor
               if hasattr(cursor, "SelectionType") else cursor.WordUnderCursor)
        cursor.select(sel)
        cursor.insertText(text)
        self._plain.setTextCursor(cursor)

    # ---- 公共 ----
    def text(self) -> str:
        return self._sci.text() if self._sci else self._plain.toPlainText()

    def set_text(self, text: str) -> None:
        if self._sci:
            self._sci.setText(text)
        else:
            self._plain.setPlainText(text)

    def insert_at_cursor(self, snippet: str) -> None:
        if self._sci:
            line, idx = self._sci.getCursorPosition()
            self._sci.insert(snippet)
            self._sci.setCursorPosition(line, idx + len(snippet))
        else:
            self._plain.insertPlainText(snippet)
