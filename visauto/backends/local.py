"""本地后端：mss 截屏 + pynput 输入 + pyperclip 剪贴板。"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from ..exceptions import BackendError
from ..geometry import Rect
from .base import Backend, Button

if TYPE_CHECKING:
    pass

# pynput 特殊键名 → pynput.keyboard.Key 属性名 的映射。
# 上层（input.Key）使用这些规范名；普通单字符直接按字符处理。
_PYNPUT_KEYNAMES = {
    "enter": "enter",
    "return": "enter",
    "tab": "tab",
    "space": "space",
    "backspace": "backspace",
    "delete": "delete",
    "esc": "esc",
    "escape": "esc",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "home": "home",
    "end": "end",
    "pageup": "page_up",
    "pagedown": "page_down",
    "insert": "insert",
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "cmd": "cmd",
    "meta": "cmd",
    "win": "cmd",
    "super": "cmd",
    "caps_lock": "caps_lock",
    "f1": "f1", "f2": "f2", "f3": "f3", "f4": "f4", "f5": "f5", "f6": "f6",
    "f7": "f7", "f8": "f8", "f9": "f9", "f10": "f10", "f11": "f11", "f12": "f12",
}

_BUTTON_MAP = {
    Button.LEFT: "left",
    Button.MIDDLE: "middle",
    Button.RIGHT: "right",
}


class LocalBackend(Backend):
    """控制本机屏幕与输入。"""

    def __init__(self, monitor: int = 1):
        # mss monitor 索引：0=全部拼接，1=主屏。默认主屏。
        self._monitor_index = monitor
        self._sct = None
        self._mouse = None
        self._keyboard = None
        self._pynput_button = None
        self._pynput_key = None
        self._size: tuple[int, int] = (0, 0)
        self._region: Rect = Rect(0, 0, 0, 0)

    # ---- 生命周期 ----
    def connect(self) -> None:
        try:
            import mss
            from pynput import keyboard, mouse
        except ImportError as e:  # pragma: no cover - 依赖缺失路径
            raise BackendError(
                "本地后端需要 mss 和 pynput：pip install mss pynput"
            ) from e

        self._sct = mss.mss()
        try:
            mon = self._sct.monitors[self._monitor_index]
        except IndexError:
            mon = self._sct.monitors[0]
        self._region = Rect(mon["left"], mon["top"], mon["width"], mon["height"])
        self._size = (mon["width"], mon["height"])

        self._mouse = mouse.Controller()
        self._keyboard = keyboard.Controller()
        self._pynput_button = mouse.Button
        self._pynput_key = keyboard.Key

    def close(self) -> None:
        if self._sct is not None:
            self._sct.close()
            self._sct = None

    def _ensure(self) -> None:
        if self._sct is None:
            self.connect()

    # ---- 截屏 ----
    @property
    def screen_size(self) -> tuple[int, int]:
        self._ensure()
        return self._size

    def capture(self, rect: "Rect | None" = None) -> np.ndarray:
        self._ensure()
        if rect is None:
            rect = self._region
        box = {"left": rect.x, "top": rect.y, "width": rect.w, "height": rect.h}
        shot = self._sct.grab(box)
        # mss 的 .bgra 是原始 BGRA 字节；取前三通道得到 OpenCV 需要的 BGR。
        bgra = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(shot.height, shot.width, 4)
        return np.ascontiguousarray(bgra[:, :, :3])

    # ---- 鼠标 ----
    def mouse_move(self, x: int, y: int) -> None:
        self._ensure()
        self._mouse.position = (x, y)

    def mouse_press(self, button: Button = Button.LEFT) -> None:
        self._ensure()
        self._mouse.press(getattr(self._pynput_button, _BUTTON_MAP[button]))

    def mouse_release(self, button: Button = Button.LEFT) -> None:
        self._ensure()
        self._mouse.release(getattr(self._pynput_button, _BUTTON_MAP[button]))

    def mouse_scroll(self, dx: int, dy: int) -> None:
        self._ensure()
        self._mouse.scroll(dx, dy)

    # ---- 键盘 ----
    def _resolve_key(self, key: str):
        """规范键名/字符 → pynput 可接受的键对象。"""
        if len(key) == 1:
            return key
        name = _PYNPUT_KEYNAMES.get(key.lower())
        if name is None:
            # 未知多字符键名，回退为原样（可能抛错，交由上层捕获）
            return key
        return getattr(self._pynput_key, name)

    def key_press(self, key: str) -> None:
        self._ensure()
        self._keyboard.press(self._resolve_key(key))

    def key_release(self, key: str) -> None:
        self._ensure()
        self._keyboard.release(self._resolve_key(key))

    def type_text(self, text: str) -> None:
        self._ensure()
        self._keyboard.type(text)

    # ---- 剪贴板 ----
    def set_clipboard(self, text: str) -> None:
        try:
            import pyperclip
        except ImportError as e:  # pragma: no cover
            raise BackendError("paste 需要 pyperclip：pip install pyperclip") from e
        pyperclip.copy(text)
