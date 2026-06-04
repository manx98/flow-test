"""Qt 绑定兼容层：优先 PyQt6，回退 PyQt5；统一导出供其余模块使用。

抹平两版差异：
- 枚举：PyQt6 用嵌套枚举（Qt.AlignmentFlag.AlignLeft），PyQt5 是扁平（Qt.AlignLeft）。
  这里对常用枚举做命名空间补丁，使代码统一用嵌套写法。
- exec()/exec_()：统一用 exec()。
其余模块只 `from .qt import QtWidgets, QtGui, QtCore, Qsci, QT_BINDING`。
"""
from __future__ import annotations

QT_BINDING = None

try:  # 优先 PyQt6
    from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: F401
    QT_BINDING = "PyQt6"
    try:
        from PyQt6 import Qsci  # noqa: F401
    except ImportError:
        Qsci = None
    pyqtSignal = QtCore.pyqtSignal
    pyqtSlot = QtCore.pyqtSlot
except ImportError:  # 回退 PyQt5
    from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: F401
    QT_BINDING = "PyQt5"
    try:
        from PyQt5 import Qsci  # noqa: F401
    except ImportError:
        Qsci = None
    pyqtSignal = QtCore.pyqtSignal
    pyqtSlot = QtCore.pyqtSlot

    # —— 把 PyQt5 的扁平枚举补成 PyQt6 风格的嵌套枚举，统一调用方写法 ——
    def _patch_enum(owner, nested_name, names):
        if hasattr(owner, nested_name):
            return
        ns = type(nested_name, (), {})
        for n in names:
            if hasattr(owner, n):
                setattr(ns, n, getattr(owner, n))
        setattr(owner, nested_name, ns)

    Qt = QtCore.Qt
    _patch_enum(Qt, "AlignmentFlag", [
        "AlignLeft", "AlignRight", "AlignHCenter", "AlignTop", "AlignBottom",
        "AlignVCenter", "AlignCenter"])
    _patch_enum(Qt, "Orientation", ["Horizontal", "Vertical"])
    _patch_enum(Qt, "MouseButton", ["LeftButton", "RightButton", "MiddleButton", "NoButton"])
    _patch_enum(Qt, "Key", [k for k in dir(Qt) if k.startswith("Key_")])
    _patch_enum(Qt, "KeyboardModifier", [
        "ShiftModifier", "ControlModifier", "AltModifier", "MetaModifier", "NoModifier"])
    _patch_enum(Qt, "PenStyle", ["SolidLine", "DashLine", "NoPen"])
    _patch_enum(Qt, "GlobalColor", ["red", "green", "blue", "white", "black", "yellow"])
    _patch_enum(Qt, "AspectRatioMode", ["KeepAspectRatio", "IgnoreAspectRatio"])
    _patch_enum(Qt, "TransformationMode", ["SmoothTransformation", "FastTransformation"])
    _patch_enum(Qt, "CursorShape", ["CrossCursor", "ArrowCursor"])
    _patch_enum(Qt, "DockWidgetArea", [
        "LeftDockWidgetArea", "RightDockWidgetArea", "TopDockWidgetArea",
        "BottomDockWidgetArea"])
    _patch_enum(Qt, "ItemDataRole", ["DisplayRole", "UserRole", "DecorationRole"])
    _patch_enum(QtGui.QImage, "Format", ["Format_RGB888", "Format_RGBA8888"])
    _patch_enum(QtWidgets.QListView, "ViewMode", ["IconMode", "ListMode"])
    _patch_enum(QtWidgets.QFrame, "Shape", ["Box", "StyledPanel", "NoFrame"])
    _patch_enum(QtWidgets.QSizePolicy, "Policy", ["Expanding", "Preferred", "Fixed"])
    _patch_enum(QtWidgets.QMessageBox, "StandardButton", ["Yes", "No", "Ok", "Cancel"])


Qt = QtCore.Qt


def exec_dialog(dialog):
    """统一调用对话框/应用的事件循环（PyQt6 exec / PyQt5 exec_）。"""
    if hasattr(dialog, "exec"):
        return dialog.exec()
    return dialog.exec_()
