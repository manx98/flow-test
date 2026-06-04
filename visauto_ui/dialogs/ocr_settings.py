"""OCR 设置对话框：选引擎/语言 → 惰性创建 → 设为 visauto 会话默认。"""
from __future__ import annotations

from ..qt import QtWidgets


class OcrSettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, initial=None):
        super().__init__(parent)
        self.setWindowTitle("OCR 设置")
        self.engine = None
        self._initial = initial or {}

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.kind = QtWidgets.QComboBox()
        self.kind.addItems(["PaddleEngine", "TesseractEngine"])
        self.lang = QtWidgets.QLineEdit("ch")
        self.use_gpu = QtWidgets.QCheckBox("use_gpu (Paddle)")
        form.addRow("引擎", self.kind)
        form.addRow("语言", self.lang)
        form.addRow("", self.use_gpu)
        layout.addLayout(form)

        self.hint = QtWidgets.QLabel(
            "Paddle 默认 lang=ch；Tesseract 用 chi_sim/eng（需系统 tesseract）。\n"
            "应用后脚本里 dev.find(text=..) 可省略 ocr=。")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._apply)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        self.kind.currentIndexChanged.connect(self._sync)
        # 回填上次配置
        if self._initial:
            self.kind.setCurrentText(self._initial.get("kind", "PaddleEngine"))
            self.lang.setText(self._initial.get("lang", "ch"))
            self.use_gpu.setChecked(bool(self._initial.get("use_gpu", False)))
        self._sync()

    def config(self) -> dict:
        return {
            "kind": self.kind.currentText(),
            "lang": self.lang.text().strip(),
            "use_gpu": self.use_gpu.isChecked(),
        }

    def _sync(self) -> None:
        is_paddle = self.kind.currentText() == "PaddleEngine"
        self.use_gpu.setEnabled(is_paddle)
        if is_paddle and self.lang.text() in ("", "eng", "chi_sim"):
            self.lang.setText("ch")
        if not is_paddle and self.lang.text() in ("", "ch"):
            self.lang.setText("chi_sim")

    def _apply(self) -> None:
        from visauto import set_default_ocr
        from visauto.ocr import PaddleEngine, TesseractEngine
        try:
            if self.kind.currentText() == "PaddleEngine":
                self.engine = PaddleEngine(lang=self.lang.text().strip() or "ch",
                                           use_gpu=self.use_gpu.isChecked())
            else:
                self.engine = TesseractEngine(lang=self.lang.text().strip() or "eng")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "OCR 引擎创建失败", str(e))
            return
        set_default_ocr(self.engine)
        self.accept()
