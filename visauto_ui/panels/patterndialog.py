"""Pattern 编辑器对话框：相似度滑块 + 点击偏移（对应 SikuliX PatternWindow）。"""
from __future__ import annotations

import os

from ..qt import Qt, QtCore, QtGui, QtWidgets


class PatternDialog(QtWidgets.QDialog):
    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pattern 编辑器")
        self._name = os.path.basename(image_path)
        self._pixmap = QtGui.QPixmap(image_path)
        self._offset = (0, 0)

        layout = QtWidgets.QVBoxLayout(self)
        self.preview = _PreviewLabel(self._pixmap)
        self.preview.offsetChanged.connect(self._on_offset)
        layout.addWidget(self.preview)

        form = QtWidgets.QFormLayout()
        self.similarity = QtWidgets.QDoubleSpinBox()
        self.similarity.setRange(0.1, 1.0)
        self.similarity.setSingleStep(0.05)
        self.similarity.setValue(0.7)
        self.gray = QtWidgets.QCheckBox("灰度匹配")
        self.offset_label = QtWidgets.QLabel("(0, 0)")
        form.addRow("相似度", self.similarity)
        form.addRow("点击偏移", self.offset_label)
        form.addRow("", self.gray)
        layout.addLayout(form)

        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def _on_offset(self, dx, dy) -> None:
        self._offset = (dx, dy)
        self.offset_label.setText(f"({dx}, {dy})")

    def code_snippet(self) -> str:
        parts = [f'"{self._name}"']
        if abs(self.similarity.value() - 0.7) > 1e-6:
            parts.append(f"similarity={self.similarity.value()}")
        if self._offset != (0, 0):
            parts.append(f"offset={self._offset}")
        if self.gray.isChecked():
            parts.append("gray=True")
        return f"Pattern({', '.join(parts)})"


class _PreviewLabel(QtWidgets.QLabel):
    offsetChanged = QtCore.pyqtSignal(int, int)

    def __init__(self, pixmap: QtGui.QPixmap, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self.setPixmap(pixmap)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cross = QtCore.QPoint(pixmap.width() // 2, pixmap.height() // 2)

    def mousePressEvent(self, ev) -> None:
        pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
        self._cross = pos
        dx = pos.x() - self._pixmap.width() // 2
        dy = pos.y() - self._pixmap.height() // 2
        self.offsetChanged.emit(dx, dy)
        self.update()

    def paintEvent(self, ev) -> None:
        super().paintEvent(ev)
        p = QtGui.QPainter(self)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 60, 60), 2))
        p.drawLine(self._cross.x() - 6, self._cross.y(),
                   self._cross.x() + 6, self._cross.y())
        p.drawLine(self._cross.x(), self._cross.y() - 6,
                   self._cross.x(), self._cross.y() + 6)
