"""命中区域高亮（调试可视化，对应 design util.Highlight）。

本地后端用一个无边框置顶窗口画矩形边框；环境不支持 GUI 时退化为日志，
绝不因高亮失败影响自动化主流程。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .settings import Debug

if TYPE_CHECKING:
    from .geometry import Rect


def highlight_rect(rect: "Rect", duration: float = 1.0, color: str = "red") -> None:
    """在屏幕上短暂高亮一个矩形。"""
    try:
        _tk_highlight(rect, duration, color)
    except Exception as e:  # GUI 不可用等
        Debug.info(f"highlight 退化为日志（{e}）：{rect}")


def _tk_highlight(rect: "Rect", duration: float, color: str) -> None:
    import tkinter as tk

    root = tk.Tk()
    root.overrideredirect(True)            # 无边框
    root.attributes("-topmost", True)
    try:
        root.attributes("-alpha", 0.4)     # 半透明
    except tk.TclError:
        pass
    root.geometry(f"{rect.w}x{rect.h}+{rect.x}+{rect.y}")
    canvas = tk.Canvas(root, width=rect.w, height=rect.h, highlightthickness=0, bg="white")
    canvas.pack()
    canvas.create_rectangle(2, 2, rect.w - 2, rect.h - 2, outline=color, width=4)
    root.after(int(duration * 1000), root.destroy)
    root.mainloop()
