"""应用入口。

可通过 `python -m visauto_ui` 运行；也支持直接运行本文件
（`python visauto_ui/app.py` 或 IDE 点 Run）——下面的引导块会补好包上下文。
"""
from __future__ import annotations

import os
import sys

# 直接以脚本方式运行时没有包上下文，relative import 会失败：
# 把仓库根目录加入 sys.path 并补上 __package__，使 `from .qt` 可解析。
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "visauto_ui"

from .qt import QtWidgets


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QtWidgets.QApplication(argv)
    app.setApplicationName("visauto client")
    from .mainwindow import MainWindow
    win = MainWindow()
    win.show()
    if hasattr(app, "exec"):
        return app.exec()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
