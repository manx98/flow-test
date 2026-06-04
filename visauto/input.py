"""输入语义层（对应 design 第 5 节 Mouse/Key）。

把高层动作（click/double_click/drag_drop/hover/type/paste）用后端原语组合，
不在每个后端里重复实现，保证本地/noVNC 行为一致。
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .backends.base import Button
from .settings import Settings

if TYPE_CHECKING:
    from .backends.base import Backend


class Key:
    """规范化的特殊键名常量（后端各自映射到原生键）。"""

    ENTER = "enter"
    TAB = "tab"
    SPACE = "space"
    BACKSPACE = "backspace"
    DELETE = "delete"
    ESC = "esc"
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    HOME = "home"
    END = "end"
    PAGE_UP = "pageup"
    PAGE_DOWN = "pagedown"
    INSERT = "insert"
    F1, F2, F3, F4 = "f1", "f2", "f3", "f4"
    F5, F6, F7, F8 = "f5", "f6", "f7", "f8"
    F9, F10, F11, F12 = "f9", "f10", "f11", "f12"


# 修饰键规范名
_MODIFIER_ALIASES = {
    "ctrl": "ctrl", "control": "ctrl",
    "alt": "alt", "option": "alt",
    "shift": "shift",
    "cmd": "cmd", "meta": "cmd", "win": "cmd", "super": "cmd",
}


def _norm_modifiers(modifiers) -> list[str]:
    if not modifiers:
        return []
    if isinstance(modifiers, str):
        modifiers = [modifiers]
    out = []
    for m in modifiers:
        key = _MODIFIER_ALIASES.get(m.lower(), m.lower())
        out.append(key)
    return out


class Mouse:
    """鼠标语义动作。坐标为目标屏幕绝对坐标。"""

    def __init__(self, backend: "Backend"):
        self._b = backend

    def move(self, x: int, y: int) -> None:
        self._b.mouse_move(x, y)
        if Settings.move_delay:
            time.sleep(Settings.move_delay)

    def _click_at(self, x: int, y: int, button: Button) -> None:
        self.move(x, y)
        self._b.mouse_press(button)
        if Settings.click_delay:
            time.sleep(Settings.click_delay)
        self._b.mouse_release(button)

    def click(self, x: int, y: int, button: Button = Button.LEFT) -> None:
        self._click_at(x, y, button)

    def double_click(self, x: int, y: int, button: Button = Button.LEFT) -> None:
        self._click_at(x, y, button)
        time.sleep(Settings.double_click_interval)
        self._click_at(x, y, button)

    def right_click(self, x: int, y: int) -> None:
        self._click_at(x, y, Button.RIGHT)

    def hover(self, x: int, y: int) -> None:
        self.move(x, y)

    def scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        self.move(x, y)
        self._b.mouse_scroll(dx, dy)

    def drag_drop(self, x1: int, y1: int, x2: int, y2: int,
                  button: Button = Button.LEFT) -> None:
        self.move(x1, y1)
        self._b.mouse_press(button)
        if Settings.move_delay:
            time.sleep(max(0.05, Settings.move_delay))
        else:
            time.sleep(0.05)
        self.move(x2, y2)
        time.sleep(0.05)
        self._b.mouse_release(button)


class Keyboard:
    """键盘语义动作。"""

    def __init__(self, backend: "Backend"):
        self._b = backend

    def type(self, text: str, modifiers=None) -> None:
        mods = _norm_modifiers(modifiers)
        for m in mods:
            self._b.key_press(m)
        try:
            if mods and len(text) <= 1:
                # 组合键如 Ctrl+A：按字符键
                self._b.key_press(text)
                self._b.key_release(text)
            else:
                if Settings.type_delay:
                    for ch in text:
                        self._b.type_text(ch)
                        time.sleep(Settings.type_delay)
                else:
                    self._b.type_text(text)
        finally:
            for m in reversed(mods):
                self._b.key_release(m)

    def press_key(self, key: str, modifiers=None) -> None:
        """按下并释放一个具名键（可带修饰键）。"""
        mods = _norm_modifiers(modifiers)
        for m in mods:
            self._b.key_press(m)
        try:
            self._b.key_press(key)
            self._b.key_release(key)
        finally:
            for m in reversed(mods):
                self._b.key_release(m)

    def paste(self, text: str) -> None:
        """经剪贴板粘贴（适合长文本/中文）。

        剪贴板不可用时（如 RDP 未协商 cliprdr、本地缺 pyperclip）自动退化为逐字输入。
        """
        try:
            self._b.set_clipboard(text)
        except Exception:
            self._b.type_text(text)
            return
        time.sleep(0.05)  # 给远端剪贴板同步留点时间
        # Ctrl+V（macOS 习惯用 Cmd+V，这里统一 ctrl，跨平台细节后续按需扩展）
        self.type("v", modifiers=["ctrl"])
