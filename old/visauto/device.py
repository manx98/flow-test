"""Device：整屏 Region + 绑定后端 + 观察线程编排，库的唯一入口。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

from .backends.base import Backend
from .elements import Region
from .input import Keyboard, Mouse
from .settings import Debug

if TYPE_CHECKING:
    from .observer import Observer


class Device(Region):
    """一个被控目标（本地屏或 noVNC 远端）。本身即整屏 Region。"""

    def __init__(self, backend: Backend):
        self._backend = backend
        self._mouse: "Optional[Mouse]" = None
        self._keyboard: "Optional[Keyboard]" = None
        self._observer: "Optional[Observer]" = None
        self._connected = False
        # 先以占位尺寸初始化 Region，connect 后再更新真实屏幕尺寸。
        super().__init__(0, 0, 0, 0, self)

    # ---- 生命周期 ----
    def connect(self) -> "Device":
        if self._connected:
            return self
        self._backend.connect()
        w, h = self._backend.screen_size
        self.x, self.y, self.w, self.h = 0, 0, w, h
        self._mouse = Mouse(self._backend)
        self._keyboard = Keyboard(self._backend)
        self._connected = True
        Debug.info(f"已连接后端 {type(self._backend).__name__} 屏幕 {w}x{h}")
        return self

    def close(self) -> None:
        if self._observer is not None:
            self._observer.stop()
        if self._connected:
            self._backend.close()
            self._connected = False

    def __enter__(self) -> "Device":
        return self.connect()

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- 暴露给 Region/elements 的依赖 ----
    @property
    def backend(self) -> Backend:
        return self._backend

    @property
    def mouse(self) -> Mouse:
        self._ensure()
        return self._mouse

    @property
    def keyboard(self) -> Keyboard:
        self._ensure()
        return self._keyboard

    def _ensure(self) -> None:
        if not self._connected:
            self.connect()

    def _capture(self):  # 覆盖：Device 截整屏
        self._ensure()
        return self._backend.capture(self.rect if self.w else None)

    def capture(self, rect=None):
        """公开截屏：rect=None 截整屏，否则截指定绝对矩形（供 GUI 取帧/抓图）。"""
        self._ensure()
        return self._backend.capture(rect)

    # ---- 观察者（对应 design 第 7 节）----
    def _obs(self) -> "Observer":
        if self._observer is None:
            from .observer import Observer
            self._observer = Observer(self)
        return self._observer

    def on_appear(self, target=None, callback: Callable = None, *,
                  text=None, regex=False, ocr=None):
        return self._obs().on_appear(target, callback, text=text, regex=regex, ocr=ocr)

    def on_vanish(self, target=None, callback: Callable = None, *,
                  text=None, regex=False, ocr=None):
        return self._obs().on_vanish(target, callback, text=text, regex=regex, ocr=ocr)

    def on_change(self, callback: Callable = None, *, min_area: "Optional[int]" = None):
        return self._obs().on_change(callback, min_area=min_area)

    def observe(self, timeout: "Optional[float]" = None, background: bool = False):
        return self._obs().observe(timeout=timeout, background=background)

    def stop_observe(self) -> None:
        if self._observer is not None:
            self._observer.stop()


# =====================================================================
# 工厂入口
# =====================================================================
def connect_local(monitor: int = 1) -> Device:
    """连接本机屏幕（mss 截屏 + pynput 输入）。"""
    from .backends.local import LocalBackend
    return Device(LocalBackend(monitor=monitor)).connect()


def connect_novnc(url: str, password: "Optional[str]" = None, **kwargs) -> Device:
    """连接 noVNC（RFB over WebSocket）远端。

    url 形如 ws://host:6080/websockify 或 wss://...；password 为 VNC 密码（可选）。
    需 pip install websocket-client（VNC 密码另需 cryptography）。
    """
    from .backends.novnc import NoVNCBackend
    return Device(NoVNCBackend(url, password=password, **kwargs)).connect()


def connect_rdp(target: str, password: "Optional[str]" = None, *,
                username: "Optional[str]" = None, domain: "Optional[str]" = None,
                auth: str = "auto", port: int = 3389,
                width: int = 1280, height: int = 800, **kwargs) -> Device:
    """连接 RDP/xrdp 远端（包装 aardwolf）。

    target 为 "host" / "host:port"，或直接传 aardwolf 连接 URL（含 :// 则透传）。
    auth: "auto"(有 domain 走 NLA 否则 TLS) | "tls"(明文密码+TLS) | "nla"(NTLM)。
    需 pip install aardwolf。
    """
    from .backends.rdp import RDPBackend
    return Device(RDPBackend(
        target, password, username=username, domain=domain, auth=auth,
        port=port, width=width, height=height, **kwargs)).connect()
