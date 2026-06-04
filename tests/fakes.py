"""FakeBackend：内存图像驱动的后端，使全链路无需真实屏幕/VNC 即可单测。"""
from __future__ import annotations

import threading

import numpy as np

from visauto.backends.base import Backend, Button
from visauto.geometry import Rect


class FakeBackend(Backend):
    """可编程画布 + 记录所有输入调用。"""

    def __init__(self, width: int = 400, height: int = 300, bg=(0, 0, 0)):
        self._canvas = np.zeros((height, width, 3), dtype=np.uint8)
        self._canvas[:] = bg
        self._lock = threading.Lock()
        self.connected = False
        # 记录的输入事件： (kind, *args)
        self.events: list[tuple] = []
        self.clipboard: str = ""

    # ---- 画布编辑（模拟界面变化）----
    def paste_patch(self, patch: np.ndarray, x: int, y: int) -> None:
        with self._lock:
            h, w = patch.shape[:2]
            self._canvas[y:y + h, x:x + w] = patch

    def fill_rect(self, rect: Rect, color=(0, 0, 0)) -> None:
        with self._lock:
            self._canvas[rect.y:rect.bottom, rect.x:rect.right] = color

    def set_canvas(self, canvas: np.ndarray) -> None:
        with self._lock:
            self._canvas = np.ascontiguousarray(canvas)

    # ---- Backend 接口 ----
    def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.connected = False

    @property
    def screen_size(self) -> tuple[int, int]:
        return (self._canvas.shape[1], self._canvas.shape[0])

    def capture(self, rect: "Rect | None" = None) -> np.ndarray:
        with self._lock:
            if rect is None:
                return self._canvas.copy()
            return np.ascontiguousarray(
                self._canvas[rect.y:rect.bottom, rect.x:rect.right].copy())

    def mouse_move(self, x: int, y: int) -> None:
        self.events.append(("move", x, y))

    def mouse_press(self, button: Button = Button.LEFT) -> None:
        self.events.append(("press", button))

    def mouse_release(self, button: Button = Button.LEFT) -> None:
        self.events.append(("release", button))

    def mouse_scroll(self, dx: int, dy: int) -> None:
        self.events.append(("scroll", dx, dy))

    def key_press(self, key: str) -> None:
        self.events.append(("key_press", key))

    def key_release(self, key: str) -> None:
        self.events.append(("key_release", key))

    def type_text(self, text: str) -> None:
        self.events.append(("type", text))

    def set_clipboard(self, text: str) -> None:
        self.clipboard = text
        self.events.append(("clipboard", text))

    # ---- 测试辅助 ----
    def clicks(self) -> list[tuple]:
        return [e for e in self.events if e[0] in ("move", "press", "release")]

    def last_move(self) -> "tuple[int, int] | None":
        for e in reversed(self.events):
            if e[0] == "move":
                return (e[1], e[2])
        return None


def make_patch(w: int, h: int, color=(0, 200, 0)) -> np.ndarray:
    """生成一个带细节的纯色块（带白边，避免纯色匹配歧义）。"""
    patch = np.zeros((h, w, 3), dtype=np.uint8)
    patch[:] = color
    patch[0, :] = (255, 255, 255)
    patch[-1, :] = (255, 255, 255)
    patch[:, 0] = (255, 255, 255)
    patch[:, -1] = (255, 255, 255)
    return patch
