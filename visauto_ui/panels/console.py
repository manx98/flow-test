"""控制台/日志面板。"""
from __future__ import annotations

import time

from ..qt import QtGui, QtWidgets


class ConsolePanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        bar = QtWidgets.QHBoxLayout()
        self.autoscroll = QtWidgets.QCheckBox("自动滚动")
        self.autoscroll.setChecked(True)
        clear = QtWidgets.QPushButton("清空")
        clear.clicked.connect(lambda: self.text.clear())
        bar.addWidget(self.autoscroll)
        bar.addStretch(1)
        bar.addWidget(clear)
        layout.addLayout(bar)

        self.text = QtWidgets.QPlainTextEdit()
        self.text.setReadOnly(True)
        font = QtGui.QFont("Monospace")
        self.text.setFont(font)
        layout.addWidget(self.text)

    def append(self, msg: str, level: str = "") -> None:
        msg = msg.rstrip("\n")
        if not msg:
            return
        prefix = f"[{time.strftime('%H:%M:%S')}]" + (f" {level}" if level else "")
        self.text.appendPlainText(f"{prefix} {msg}")
        if self.autoscroll.isChecked():
            sb = self.text.verticalScrollBar()
            sb.setValue(sb.maximum())

    def append_raw(self, text: str) -> None:
        """脚本 stdout 原样追加（已含换行）。"""
        self.text.moveCursor(QtGui.QTextCursor.MoveOperation.End
                             if hasattr(QtGui.QTextCursor, "MoveOperation")
                             else QtGui.QTextCursor.End)
        self.text.insertPlainText(text)
        if self.autoscroll.isChecked():
            sb = self.text.verticalScrollBar()
            sb.setValue(sb.maximum())
