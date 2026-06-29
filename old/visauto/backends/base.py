"""Backend 协议（对应 design 第 5 节 IScreen/IRobot 接口隔离）。

把“屏幕捕获 + 输入模拟”收敛到一个协议，Device 只依赖该协议。
本地后端与 noVNC 后端各实现一份；高层动作（click/drag/...) 由 input.py
的语义层组合这些原语，保证两后端行为一致。
"""
from __future__ import annotations

import enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import numpy as np

    from ..geometry import Rect


class Button(enum.Enum):
    LEFT = "left"
    MIDDLE = "middle"
    RIGHT = "right"


# Frame = 一帧屏幕图像，约定为 OpenCV 风格的 BGR uint8 ndarray，形状 (h, w, 3)。
if TYPE_CHECKING:
    Frame = "np.ndarray"
else:
    Frame = object


@runtime_checkable
class Backend(Protocol):
    """屏幕捕获 + 输入模拟的统一接口。"""

    # —— 生命周期 ——
    def connect(self) -> None: ...

    def close(self) -> None: ...

    # —— 截屏 ——
    @property
    def screen_size(self) -> tuple[int, int]:
        """返回 (width, height)。"""
        ...

    def capture(self, rect: "Rect | None" = None) -> "np.ndarray":
        """截取整屏或指定矩形，返回 BGR uint8 ndarray。

        rect 为 None 表示整屏；否则按绝对坐标截取该矩形。
        """
        ...

    # —— 鼠标原语 ——
    def mouse_move(self, x: int, y: int) -> None: ...

    def mouse_press(self, button: Button = Button.LEFT) -> None: ...

    def mouse_release(self, button: Button = Button.LEFT) -> None: ...

    def mouse_scroll(self, dx: int, dy: int) -> None: ...

    # —— 键盘原语 ——
    def key_press(self, key: str) -> None:
        """按下一个键。key 为规范化键名（见 input.Key）或单个字符。"""
        ...

    def key_release(self, key: str) -> None: ...

    def type_text(self, text: str) -> None:
        """键入一段文本（后端可批量优化）。"""
        ...

    # —— 剪贴板（paste 用，可选实现）——
    def set_clipboard(self, text: str) -> None: ...
