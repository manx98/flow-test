"""图片库面板：当前工程 images/ 的模板缩略图。"""
from __future__ import annotations

import os

from ..qt import Qt, QtCore, QtGui, QtWidgets, pyqtSignal


class ImageLibraryPanel(QtWidgets.QWidget):
    insertCode = pyqtSignal(str)      # 插入 dev.click("name.png")
    useInTest = pyqtSignal(str)       # 在测试面板使用该模板
    openPattern = pyqtSignal(str)     # 打开 Pattern 编辑器

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dir = None
        layout = QtWidgets.QVBoxLayout(self)
        self.list = QtWidgets.QListWidget()
        self.list.setViewMode(QtWidgets.QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QtCore.QSize(96, 72))
        self.list.setResizeMode(QtWidgets.QListWidget.ResizeMode.Adjust)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu
                                       if hasattr(Qt, "ContextMenuPolicy") else 3)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.itemDoubleClicked.connect(
            lambda it: self.insertCode.emit(it.text()))
        layout.addWidget(self.list)

    def set_dir(self, path: str) -> None:
        self._dir = path
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        if not self._dir or not os.path.isdir(self._dir):
            return
        for name in sorted(os.listdir(self._dir)):
            if name.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
                self._add_item(name)

    def _add_item(self, name: str) -> None:
        path = os.path.join(self._dir, name)
        icon = QtGui.QIcon(QtGui.QPixmap(path))
        item = QtWidgets.QListWidgetItem(icon, name)
        self.list.addItem(item)

    def add_image(self, name: str) -> None:
        self.refresh()

    def _menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        name = item.text()
        menu = QtWidgets.QMenu(self)
        menu.addAction("插入到代码", lambda: self.insertCode.emit(name))
        menu.addAction("在测试面板使用", lambda: self.useInTest.emit(name))
        menu.addAction("打开 Pattern 编辑器", lambda: self.openPattern.emit(name))
        menu.exec(self.list.mapToGlobal(pos)) if hasattr(menu, "exec") \
            else menu.exec_(self.list.mapToGlobal(pos))
