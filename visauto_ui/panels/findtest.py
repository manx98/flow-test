"""Find/OCR 测试面板：对当前画面跑 find/find_all/exists/read_text 并高亮结果。"""
from __future__ import annotations

from ..qt import QtWidgets, pyqtSignal


class FindTestPanel(QtWidgets.QWidget):
    # 发出测试请求：(spec_dict)；MainWindow 在后台线程执行并回填结果/高亮。
    runRequested = pyqtSignal(dict)
    insertCode = pyqtSignal(str)
    clearRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)

        form = QtWidgets.QFormLayout()
        self.kind = QtWidgets.QComboBox()
        self.kind.addItems(["图片", "文字(OCR)"])
        self.kind.currentIndexChanged.connect(self._sync)
        self.target = QtWidgets.QLineEdit()
        self.target.setPlaceholderText("图片文件名 或 待识别文字")
        self.regex = QtWidgets.QCheckBox("正则")
        self.similarity = QtWidgets.QDoubleSpinBox()
        self.similarity.setRange(0.1, 1.0)
        self.similarity.setSingleStep(0.05)
        self.similarity.setValue(0.7)
        form.addRow("类型", self.kind)
        form.addRow("目标", self.target)
        form.addRow("相似度", self.similarity)
        form.addRow("", self.regex)
        layout.addLayout(form)

        btns = QtWidgets.QHBoxLayout()
        for label in ("find", "find_all", "exists", "read_text"):
            b = QtWidgets.QPushButton(label)
            b.clicked.connect(lambda _=False, op=label: self._run(op))
            btns.addWidget(b)
        layout.addLayout(btns)

        self.results = QtWidgets.QListWidget()
        layout.addWidget(self.results)

        row = QtWidgets.QHBoxLayout()
        ins = QtWidgets.QPushButton("插入为代码")
        ins.clicked.connect(self._insert_code)
        clr = QtWidgets.QPushButton("清除标记")
        clr.clicked.connect(self.clearRequested)
        row.addWidget(ins)
        row.addWidget(clr)
        layout.addLayout(row)
        self._sync()

    def _sync(self) -> None:
        is_img = self.kind.currentText() == "图片"
        self.similarity.setEnabled(is_img)
        self.regex.setEnabled(not is_img)

    def set_target(self, name: str) -> None:
        self.kind.setCurrentIndex(0)
        self.target.setText(name)

    def _spec(self, op: str) -> dict:
        return {
            "op": op,
            "is_image": self.kind.currentText() == "图片",
            "target": self.target.text().strip(),
            "regex": self.regex.isChecked(),
            "similarity": self.similarity.value(),
        }

    def _run(self, op: str) -> None:
        if not self.target.text().strip():
            return
        self.runRequested.emit(self._spec(op))

    def set_results(self, lines) -> None:
        self.results.clear()
        for line in lines:
            self.results.addItem(line)

    def _insert_code(self) -> None:
        s = self._spec("find")
        if s["is_image"]:
            if abs(s["similarity"] - 0.7) < 1e-6:
                code = f'dev.find("{s["target"]}")'
            else:
                code = f'dev.find(Pattern("{s["target"]}", similarity={s["similarity"]}))'
        else:
            extra = ", regex=True" if s["regex"] else ""
            code = f'dev.find(text="{s["target"]}"{extra})'
        self.insertCode.emit(code + "\n")
