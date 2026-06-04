"""工程文件树：以树形展示工程目录（script.py / images/ / project.json …）。

基于 QFileSystemModel，实时反映磁盘变化（如 Capture 新存的图片会自动出现）。
"""
from __future__ import annotations

import os

from ..qt import Qt, QtGui, QtWidgets, pyqtSignal

# QFileSystemModel：PyQt6 在 QtGui，PyQt5 在 QtWidgets
_FSModel = getattr(QtGui, "QFileSystemModel", None) or QtWidgets.QFileSystemModel

_IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp")


class ProjectTreePanel(QtWidgets.QWidget):
    openScript = pyqtSignal(str)     # 双击 .py → 路径
    insertImage = pyqtSignal(str)    # 双击/右键图片 → 文件名（裸名，靠 ImagePath 解析）
    openPattern = pyqtSignal(str)    # 右键图片 → 文件名
    useInTest = pyqtSignal(str)      # 右键图片 → 文件名

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.model = _FSModel(self)
        self.tree = QtWidgets.QTreeView()
        self.tree.setModel(self.model)
        # 只显示名称列，隐藏大小/类型/日期
        for col in (1, 2, 3):
            self.tree.setColumnHidden(col, True)
        self.tree.setHeaderHidden(True)
        self.tree.doubleClicked.connect(self._on_double_click)
        self.tree.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu if hasattr(Qt, "ContextMenuPolicy")
            else 3)
        self.tree.customContextMenuRequested.connect(self._menu)
        layout.addWidget(self.tree)

    def set_root(self, path: str) -> None:
        if not path or not os.path.isdir(path):
            return
        self.model.setRootPath(path)
        self.tree.setRootIndex(self.model.index(path))
        self.tree.expandToDepth(0)

    # ---- 交互 ----
    def _path_of(self, index) -> str:
        return self.model.filePath(index)

    def _on_double_click(self, index) -> None:
        path = self._path_of(index)
        if os.path.isdir(path):
            return
        ext = os.path.splitext(path)[1].lower()
        if ext == ".py":
            self.openScript.emit(path)
        elif ext in _IMG_EXT:
            self.insertImage.emit(os.path.basename(path))

    def _menu(self, pos) -> None:
        index = self.tree.indexAt(pos)
        if not index.isValid():
            return
        path = self._path_of(index)
        name = os.path.basename(path)
        ext = os.path.splitext(path)[1].lower()
        menu = QtWidgets.QMenu(self)
        if ext == ".py":
            menu.addAction("在编辑器打开", lambda: self.openScript.emit(path))
        elif ext in _IMG_EXT:
            menu.addAction("插入到代码", lambda: self.insertImage.emit(name))
            menu.addAction("在测试面板使用", lambda: self.useInTest.emit(name))
            menu.addAction("打开 Pattern 编辑器", lambda: self.openPattern.emit(name))
        else:
            return
        gp = self.tree.viewport().mapToGlobal(pos)
        menu.exec(gp) if hasattr(menu, "exec") else menu.exec_(gp)
