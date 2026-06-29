"""RDPBackend：通过 RDP 控制 xrdp/Windows 远端，包装 aardwolf，实现 Backend 接口。

异步↔同步桥：后台线程独占一个 asyncio 事件循环跑 aardwolf 连接；aardwolf 内部
维护整桌面缓冲，`capture()` 经 get_desktop_buffer 取快照；输入对象经
`ext_in_queue`（call_soon_threadsafe 投递）下发。与 NoVNCBackend 同构，上层透明复用。
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING, Optional
from urllib.parse import quote

import numpy as np

from ..exceptions import BackendError
from ..geometry import Rect
from ..settings import Debug
from .base import Backend, Button
from .rdp_keymap import CHAR_TO_SCANCODE, NAME_TO_VK

if TYPE_CHECKING:
    pass

_AUTH_SCHEME = {"tls": "plain-password", "nla": "ntlm-password"}


def auth_candidates(auth: str, domain: "Optional[str]") -> list:
    """返回要依次尝试的 asyauth 方案。

    auto 且无域名时先 plain(TLS) 后 ntlm(NLA)，以便服务器要求 HYBRID/NLA 时自动改用 NLA。
    """
    if auth == "tls":
        return ["plain-password"]
    if auth == "nla":
        return ["ntlm-password"]
    if auth == "auto":
        return ["ntlm-password"] if domain else ["plain-password", "ntlm-password"]
    raise BackendError(f"未知 auth 取值：{auth}（可选 auto/tls/nla）")


def build_rdp_url(target: str, password: "Optional[str]", username: "Optional[str]",
                  domain: "Optional[str]", port: int, scheme: str) -> str:
    """用指定 asyauth scheme 拼 aardwolf 连接 URL；target 含 :// 则原样返回。"""
    if "://" in target:
        return target
    host = target
    if host.count(":") == 1 and not host.startswith("["):
        host, p = host.split(":")
        port = int(p)
    user = username or ""
    userpart = f"{domain}\\{user}" if domain else user
    return (f"rdp+{scheme}://{quote(userpart, safe='')}:"
            f"{quote(password or '', safe='')}@{host}:{port}")


class RDPBackend(Backend):
    def __init__(self, target: str, password: "Optional[str]" = None, *,
                 username: "Optional[str]" = None, domain: "Optional[str]" = None,
                 auth: str = "auto", port: int = 3389,
                 width: int = 1280, height: int = 800,
                 first_update_timeout: float = 10.0,
                 connect_timeout: float = 20.0, **kwargs):
        self._target = target
        self._password = password
        self._username = username
        self._domain = domain
        self._auth = auth
        self._port = port
        self._width = width
        self._height = height
        self._first_update_timeout = first_update_timeout
        self._connect_timeout = connect_timeout
        self._kwargs = kwargs

        self._loop: "Optional[asyncio.AbstractEventLoop]" = None
        self._conn = None
        self._thread: "Optional[threading.Thread]" = None
        self._ready = threading.Event()
        self._connect_error: "Optional[BaseException]" = None
        self._lost = False
        self.server_clipboard = ""
        # 输入状态
        self._mask_buttons: set = set()
        self._x = 0
        self._y = 0

    # ================= 生命周期 =================
    def connect(self) -> None:
        self._thread = threading.Thread(target=self._thread_main, daemon=True,
                                        name="visauto-rdp")
        self._thread.start()
        # 外层等待要覆盖「所有候选方案各自的尝试超时」之和，留余量。
        n = 1 if "://" in self._target else len(auth_candidates(self._auth, self._domain))
        overall = n * self._connect_timeout + 15
        if not self._ready.wait(overall):
            raise BackendError(
                "RDP 连接超时：后台未在预期时间内返回（多为网络不可达/端口不通/服务器无响应）")
        if self._connect_error is not None:
            raise BackendError(f"RDP 连接失败：{self._connect_error}")
        # 等首帧桌面数据
        deadline = time.monotonic() + self._first_update_timeout
        while not getattr(self._conn, "desktop_buffer_has_data", False):
            if time.monotonic() >= deadline:
                self.close()
                raise BackendError("等待首帧 RDP 桌面超时")
            time.sleep(0.05)

    def _thread_main(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_main())
        except Exception as e:  # pragma: no cover
            self._connect_error = e
            self._ready.set()
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    async def _async_main(self) -> None:
        try:
            from aardwolf.commons.factory import RDPConnectionFactory
            from aardwolf.commons.iosettings import RDPIOSettings
            from aardwolf.commons.queuedata.constants import VIDEO_FORMAT
        except ImportError as e:
            self._connect_error = BackendError(
                "RDP 后端需要 aardwolf：pip install aardwolf")
            self._ready.set()
            return

        io = RDPIOSettings()
        io.video_width = self._width
        io.video_height = self._height
        io.video_bpp_min = 15
        io.video_bpp_max = 32
        io.video_out_format = VIDEO_FORMAT.RAW   # 外部队列用最廉价格式；取屏走桌面缓冲
        io.clipboard_use_pyperclip = False        # 不污染本机剪贴板

        candidates = auth_candidates(self._auth, self._domain)
        last_err = None
        for scheme in candidates:
            url = build_rdp_url(self._target, self._password, self._username,
                                self._domain, self._port, scheme)
            try:
                factory = RDPConnectionFactory.from_url(url, io)
                conn = factory.get_connection(io)
                _, err = await asyncio.wait_for(conn.connect(), self._connect_timeout)
            except asyncio.TimeoutError:
                last_err = BackendError(
                    f"连接超时（{self._connect_timeout}s，方案 {scheme}）")
                break  # 超时多为网络层问题，换认证方案也无济于事
            except Exception as e:
                last_err = e
                break
            if err is None:
                self._conn = conn
                last_err = None
                break
            last_err = err
            # 服务器要求 NLA/HYBRID 而本次用的是 TLS → 还有候选则改用 NLA 重试。
            if "HYBRID" in str(err).upper() and scheme != candidates[-1]:
                Debug.info("服务器要求 NLA(HYBRID)，自动改用 ntlm-password 重试")
                continue
            break

        if self._conn is None:
            self._connect_error = last_err or BackendError("RDP 连接失败")
            self._ready.set()
            return

        self._ready.set()
        await self._drain_out_queue()

    async def _drain_out_queue(self) -> None:
        """消费输出队列：保持内存有界，并记录服务器剪贴板文本；None 表示终止。"""
        from aardwolf.commons.queuedata import RDPDATATYPE
        while True:
            item = await self._conn.ext_out_queue.get()
            if item is None:
                self._lost = True   # aardwolf 终止/断开时投递 None
                break
            try:
                if getattr(item, "type", None) == RDPDATATYPE.CLIPBOARD_DATA_TXT:
                    self.server_clipboard = item.data
            except Exception:
                pass

    def close(self) -> None:
        if self._loop is not None and self._conn is not None:
            # 投递 None 触发 aardwolf terminate，drain 循环随之退出。
            self._loop.call_soon_threadsafe(self._conn.ext_in_queue.put_nowait, None)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._conn = None
        self._thread = None

    def _ensure(self):
        if self._conn is None:
            raise BackendError("RDPBackend 尚未连接")
        return self._conn

    def is_alive(self) -> bool:
        """连接是否仍然存活（供 GUI 检测服务器断开/重置）。"""
        if self._conn is None or self._lost:
            return False
        ev = getattr(self._conn, "disconnected_evt", None)
        if ev is not None and ev.is_set():
            return False
        return True

    def _submit(self, obj) -> None:
        """线程安全地把输入对象投递到 aardwolf 的 ext_in_queue。"""
        conn = self._ensure()
        self._loop.call_soon_threadsafe(conn.ext_in_queue.put_nowait, obj)

    # ================= 截屏 =================
    @property
    def screen_size(self) -> tuple[int, int]:
        return (self._width, self._height)

    def capture(self, rect: "Rect | None" = None) -> np.ndarray:
        from aardwolf.commons.queuedata.constants import VIDEO_FORMAT
        conn = self._ensure()
        if not self.is_alive():
            raise BackendError("RDP 连接已被服务器断开（reset）")
        img = conn.get_desktop_buffer(VIDEO_FORMAT.PIL)
        if img is None or isinstance(img, tuple):
            # 尚无数据或出错：返回黑屏，保持调用不崩。
            full = np.zeros((self._height, self._width, 3), dtype=np.uint8)
        else:
            full = np.asarray(img.convert("RGB"))[:, :, ::-1]  # RGB→BGR
            full = np.ascontiguousarray(full)
        if rect is None:
            return full
        return np.ascontiguousarray(full[rect.y:rect.bottom, rect.x:rect.right].copy())

    # ================= 鼠标 =================
    def _mouse_event(self, button, x: int, y: int, pressed: bool) -> None:
        from aardwolf.commons.queuedata.constants import MOUSEBUTTON
        from aardwolf.commons.queuedata.mouse import RDP_MOUSE
        m = RDP_MOUSE()
        m.xPos = int(x)
        m.yPos = int(y)
        m.button = button if button is not None else MOUSEBUTTON.MOUSEBUTTON_HOVER
        m.is_pressed = pressed
        self._submit(m)

    def _btn(self, button: Button):
        from aardwolf.commons.queuedata.constants import MOUSEBUTTON
        return {
            Button.LEFT: MOUSEBUTTON.MOUSEBUTTON_LEFT,
            Button.RIGHT: MOUSEBUTTON.MOUSEBUTTON_RIGHT,
            Button.MIDDLE: MOUSEBUTTON.MOUSEBUTTON_MIDDLE,
        }[button]

    def mouse_move(self, x: int, y: int) -> None:
        self._x, self._y = int(x), int(y)
        self._mouse_event(None, self._x, self._y, False)  # hover

    def mouse_press(self, button: Button = Button.LEFT) -> None:
        self._mouse_event(self._btn(button), self._x, self._y, True)

    def mouse_release(self, button: Button = Button.LEFT) -> None:
        self._mouse_event(self._btn(button), self._x, self._y, False)

    def mouse_scroll(self, dx: int, dy: int) -> None:
        from aardwolf.commons.queuedata.constants import MOUSEBUTTON
        conn = self._ensure()
        # 关键：始终用 WHEEL_UP（确保设置 PTRFLAGS.WHEEL 标志位），方向编码进“有符号 steps”。
        # 原因：aardwolf 的 WHEEL_DOWN 分支只设 WHEEL_NEGATIVE 却漏了 WHEEL 位 → 向下滚 PDU 非法、
        # 服务器会 reset。用 WHEEL_UP + steps=-120 时，WheelRotationMask & -120 自带负向位与旋转量，
        # 服务器按规范 sign-extend 为向下滚。另外 is_pressed=False 以免叠加非法的 PTRFLAGS.DOWN。
        up = MOUSEBUTTON.MOUSEBUTTON_WHEEL_UP
        step = 120 if dy > 0 else -120
        for _ in range(abs(dy)):
            asyncio.run_coroutine_threadsafe(
                conn.send_mouse(up, self._x, self._y, False, step), self._loop)
        # 水平滚动 RDP 少见，缺省忽略 dx。

    # ================= 键盘 =================
    def _scancode_event(self, *, vk_code=None, key_code=None, pressed: bool) -> None:
        from aardwolf.commons.queuedata.keyboard import RDP_KEYBOARD_SCANCODE
        ev = RDP_KEYBOARD_SCANCODE()
        ev.vk_code = vk_code
        ev.keyCode = key_code
        ev.is_pressed = pressed
        ev.is_extended = False
        self._submit(ev)

    def _unicode_event(self, ch: str, pressed: bool) -> None:
        from aardwolf.commons.queuedata.keyboard import RDP_KEYBOARD_UNICODE
        ev = RDP_KEYBOARD_UNICODE()
        ev.char = ch
        ev.is_pressed = pressed
        self._submit(ev)

    def _key_action(self, key: str, pressed: bool) -> None:
        vk = NAME_TO_VK.get(key.lower())
        if vk is not None:
            self._scancode_event(vk_code=vk, pressed=pressed)
            return
        if len(key) == 1:
            sc = CHAR_TO_SCANCODE.get(key.lower())
            if sc is not None:
                # 单字符走扫描码，便于与修饰键组合（如 Ctrl+V）。
                self._scancode_event(key_code=sc, pressed=pressed)
            else:
                self._unicode_event(key, pressed)
            return
        raise BackendError(f"无法映射键：{key!r}")

    def key_press(self, key: str) -> None:
        self._key_action(key, True)

    def key_release(self, key: str) -> None:
        self._key_action(key, False)

    def type_text(self, text: str) -> None:
        # 任意文本（含中文）走 Unicode 键事件，免 IME。
        for ch in text:
            self._unicode_event(ch, True)
            self._unicode_event(ch, False)

    # ================= 剪贴板 =================
    def set_clipboard(self, text: str) -> None:
        """优先经 RDP cliprdr 设置远端剪贴板；失败则由上层 paste 退化为逐字输入。"""
        conn = self._ensure()
        try:
            fut = asyncio.run_coroutine_threadsafe(
                conn.set_current_clipboard_text(text), self._loop)
            fut.result(timeout=3.0)
        except Exception as e:
            raise BackendError(f"RDP 剪贴板设置失败（可改用逐字输入）：{e}") from e
