"""NoVNCBackend：通过 noVNC（RFB over WebSocket）控制远端，实现 Backend 接口。

同步层（capture/输入）与传输层（后台 RFB 线程）解耦：
  [同步 API 线程] ──写: 指针/键盘/请求──▶ [WSStream] ◀──读: framebuffer──[RFB 线程]
  capture() 直接返回当前 framebuffer 快照（加锁拷贝）。
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Optional

import numpy as np

from ..exceptions import BackendError
from ..geometry import Rect
from .base import Backend, Button
from .rfb.keysym import keysym_for_char, keysym_for_key
from .rfb.protocol import RFBClient
from .rfb.transport import WSStream

if TYPE_CHECKING:
    pass

_BUTTON_BIT = {
    Button.LEFT: 0x01,
    Button.MIDDLE: 0x02,
    Button.RIGHT: 0x04,
}
_WHEEL_UP = 0x08
_WHEEL_DOWN = 0x10
_WHEEL_LEFT = 0x20
_WHEEL_RIGHT = 0x40


class NoVNCBackend(Backend):
    def __init__(self, url: str, password: "Optional[str]" = None, *,
                 shared: bool = True, first_update_timeout: float = 5.0,
                 subprotocols=("binary",), **ws_kwargs):
        self._url = url
        self._password = password
        self._shared = shared
        self._first_update_timeout = first_update_timeout
        self._subprotocols = subprotocols
        self._ws_kwargs = ws_kwargs

        self._stream: "Optional[WSStream]" = None
        self._client: "Optional[RFBClient]" = None
        self._thread: "Optional[threading.Thread]" = None
        # 输入状态
        self._mask = 0
        self._x = 0
        self._y = 0

    # ---- 生命周期 ----
    def connect(self) -> None:
        self._stream = WSStream(
            self._url, subprotocols=self._subprotocols, **self._ws_kwargs)
        self._client = RFBClient(self._stream, password=self._password,
                                 shared=self._shared)
        self._client.handshake()
        self._thread = threading.Thread(
            target=self._client.run, daemon=True, name="visauto-rfb")
        self._thread.start()
        # 等首帧，确保 capture 不返回全黑。
        if not self._client.first_update.wait(self._first_update_timeout):
            raise BackendError("等待首帧 framebuffer 超时")

    def close(self) -> None:
        if self._client is not None:
            self._client.stop()
        if self._stream is not None:
            self._stream.close()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._client = None
        self._stream = None
        self._thread = None

    def _ensure(self) -> RFBClient:
        if self._client is None:
            raise BackendError("NoVNCBackend 尚未连接")
        return self._client

    # ---- 截屏 ----
    @property
    def screen_size(self) -> tuple[int, int]:
        c = self._ensure()
        return (c.width, c.height)

    def capture(self, rect: "Rect | None" = None) -> np.ndarray:
        c = self._ensure()
        if rect is None:
            return c.snapshot()
        return c.snapshot((rect.x, rect.y, rect.w, rect.h))

    # ---- 鼠标 ----
    def _send_pointer(self) -> None:
        self._ensure().send_pointer(self._mask, self._x, self._y)

    def mouse_move(self, x: int, y: int) -> None:
        self._x, self._y = x, y
        self._send_pointer()

    def mouse_press(self, button: Button = Button.LEFT) -> None:
        self._mask |= _BUTTON_BIT[button]
        self._send_pointer()

    def mouse_release(self, button: Button = Button.LEFT) -> None:
        self._mask &= ~_BUTTON_BIT[button]
        self._send_pointer()

    def mouse_scroll(self, dx: int, dy: int) -> None:
        c = self._ensure()

        def notch(bit):
            c.send_pointer(self._mask | bit, self._x, self._y)
            c.send_pointer(self._mask, self._x, self._y)

        for _ in range(abs(dy)):
            notch(_WHEEL_UP if dy > 0 else _WHEEL_DOWN)
        for _ in range(abs(dx)):
            notch(_WHEEL_RIGHT if dx > 0 else _WHEEL_LEFT)

    # ---- 键盘 ----
    def key_press(self, key: str) -> None:
        self._ensure().send_key(keysym_for_key(key), down=True)

    def key_release(self, key: str) -> None:
        self._ensure().send_key(keysym_for_key(key), down=False)

    def type_text(self, text: str) -> None:
        c = self._ensure()
        for ch in text:
            sym = keysym_for_char(ch)
            c.send_key(sym, down=True)
            c.send_key(sym, down=False)

    # ---- 剪贴板 ----
    def set_clipboard(self, text: str) -> None:
        self._ensure().send_cut_text(text)
