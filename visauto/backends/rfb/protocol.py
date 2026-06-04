"""RFB 协议状态机：握手 + FramebufferUpdate 循环。

线程模型：一个后台线程跑 run()，持续请求并解码 framebuffer 增量更新，写入受锁
保护的 fb；输入消息（指针/键盘/剪贴板）由其它线程经 send_* 方法写出。
"""
from __future__ import annotations

import struct
import threading

import numpy as np

from ...exceptions import BackendError
from ...settings import Debug
from . import decoders
from .auth import vnc_auth_response
from .transport import WSStream

# 客户端声明支持的编码，按服务器偏好从前到后；末尾为伪编码。
CLIENT_ENCODINGS = [
    decoders.ENC_TIGHT,
    decoders.ENC_ZRLE,
    decoders.ENC_HEXTILE,
    decoders.ENC_COPYRECT,
    decoders.ENC_RAW,
    decoders.ENC_DESKTOP_SIZE,
]

# 服务器→客户端消息类型
_MSG_FB_UPDATE = 0
_MSG_SET_COLORMAP = 1
_MSG_BELL = 2
_MSG_SERVER_CUT_TEXT = 3

SEC_NONE = 1
SEC_VNC = 2


class RFBClient:
    def __init__(self, stream: WSStream, password=None, shared=True):
        self.stream = stream
        self.password = password
        self.shared = shared
        self.version = (3, 8)
        self.width = 0
        self.height = 0
        self.name = ""

        self.fb: "np.ndarray | None" = None
        self.fb_lock = threading.Lock()
        self.first_update = threading.Event()
        self._state = decoders.DecoderState()
        self._stop = threading.Event()
        self.server_cut_text = ""

    # ================= 握手 =================
    def handshake(self) -> None:
        self._negotiate_version()
        self._negotiate_security()
        self.stream.write(bytes([1 if self.shared else 0]))  # ClientInit
        self._read_server_init()
        self._set_pixel_format()
        self._set_encodings()
        with self.fb_lock:
            self.fb = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        Debug.info(f"RFB 握手完成：{self.width}x{self.height} '{self.name}'")

    def _negotiate_version(self) -> None:
        sv = self.stream.read_exactly(12)  # b"RFB 003.008\n"
        try:
            major = int(sv[4:7])
            minor = int(sv[8:11])
        except ValueError:
            raise BackendError(f"非法 RFB 版本串：{sv!r}")
        if (major, minor) >= (3, 8):
            self.version = (3, 8)
        elif (major, minor) >= (3, 7):
            self.version = (3, 7)
        else:
            self.version = (3, 3)
        self.stream.write(
            f"RFB {self.version[0]:03d}.{self.version[1]:03d}\n".encode("ascii"))

    def _negotiate_security(self) -> None:
        if self.version >= (3, 7):
            n = self.stream.read_exactly(1)[0]
            if n == 0:
                self._raise_with_reason("服务器拒绝连接")
            types = self.stream.read_exactly(n)
            chosen = self._pick_security(types)
            self.stream.write(bytes([chosen]))
        else:
            chosen = struct.unpack(">I", self.stream.read_exactly(4))[0]

        if chosen == SEC_NONE:
            if self.version >= (3, 8):
                self._read_security_result()
        elif chosen == SEC_VNC:
            challenge = self.stream.read_exactly(16)
            if not self.password:
                raise BackendError("服务器要求 VNC 密码，但未提供 password")
            self.stream.write(vnc_auth_response(self.password, challenge))
            self._read_security_result()
        else:
            raise BackendError(f"不支持的安全类型：{chosen}")

    def _pick_security(self, types: bytes) -> int:
        if self.password and SEC_VNC in types:
            return SEC_VNC
        if SEC_NONE in types:
            return SEC_NONE
        if SEC_VNC in types:
            return SEC_VNC
        raise BackendError(f"无可用安全类型，服务器提供：{list(types)}")

    def _read_security_result(self) -> None:
        result = struct.unpack(">I", self.stream.read_exactly(4))[0]
        if result != 0:
            if self.version >= (3, 8):
                self._raise_with_reason("认证失败")
            raise BackendError("认证失败")

    def _raise_with_reason(self, prefix: str) -> None:
        length = struct.unpack(">I", self.stream.read_exactly(4))[0]
        reason = self.stream.read_exactly(length).decode("latin-1", "replace")
        raise BackendError(f"{prefix}：{reason}")

    def _read_server_init(self) -> None:
        head = self.stream.read_exactly(24)
        self.width, self.height = struct.unpack(">HH", head[0:4])
        name_len = struct.unpack(">I", head[20:24])[0]
        if name_len:
            self.name = self.stream.read_exactly(name_len).decode("latin-1", "replace")

    def _set_pixel_format(self) -> None:
        # bpp=32, depth=24, big-endian=0, true-colour=1, max=255, 红移16/绿移8/蓝移0
        pf = struct.pack(">BBBBHHHBBBxxx", 32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
        self.stream.write(struct.pack(">Bxxx", 0) + pf)

    def _set_encodings(self) -> None:
        msg = struct.pack(">BxH", 2, len(CLIENT_ENCODINGS))
        for enc in CLIENT_ENCODINGS:
            msg += struct.pack(">i", enc)
        self.stream.write(msg)

    # ================= 请求/输入 =================
    def request_update(self, incremental: bool = True) -> None:
        self.stream.write(struct.pack(
            ">BBHHHH", 3, 1 if incremental else 0, 0, 0, self.width, self.height))

    def send_pointer(self, button_mask: int, x: int, y: int) -> None:
        x = max(0, min(self.width - 1, x))
        y = max(0, min(self.height - 1, y))
        self.stream.write(struct.pack(">BBHH", 5, button_mask & 0xFF, x, y))

    def send_key(self, keysym: int, down: bool) -> None:
        self.stream.write(struct.pack(">BBHI", 4, 1 if down else 0, 0, keysym))

    def send_cut_text(self, text: str) -> None:
        data = text.encode("latin-1", "replace")
        self.stream.write(struct.pack(">BxxxI", 6, len(data)) + data)

    # ================= 主循环 =================
    def run(self) -> None:
        try:
            self.request_update(incremental=False)
            while not self._stop.is_set():
                msg_type = self.stream.read_exactly(1)[0]
                if msg_type == _MSG_FB_UPDATE:
                    self._handle_fb_update()
                    self.request_update(incremental=True)
                elif msg_type == _MSG_SET_COLORMAP:
                    self._handle_set_colormap()
                elif msg_type == _MSG_BELL:
                    pass
                elif msg_type == _MSG_SERVER_CUT_TEXT:
                    self._handle_server_cut_text()
                else:
                    raise BackendError(f"未知服务器消息类型：{msg_type}")
        except BackendError as e:
            if not self._stop.is_set():
                Debug.error(f"RFB 线程退出：{e}")
        finally:
            self.first_update.set()  # 解除等待

    def stop(self) -> None:
        self._stop.set()

    def _handle_fb_update(self) -> None:
        self.stream.read_exactly(1)  # padding
        nrects = struct.unpack(">H", self.stream.read_exactly(2))[0]
        read = self.stream.read_exactly
        for _ in range(nrects):
            rx, ry, rw, rh = struct.unpack(">HHHH", read(8))
            enc = struct.unpack(">i", read(4))[0]
            if enc == decoders.ENC_DESKTOP_SIZE:
                self._resize(rw, rh)
                continue
            decoder = decoders.DECODERS.get(enc)
            if decoder is None:
                raise BackendError(f"服务器使用了未实现的编码：{enc}")
            with self.fb_lock:
                decoder(read, self.fb, rx, ry, rw, rh, self._state)
        self.first_update.set()

    def _resize(self, w: int, h: int) -> None:
        with self.fb_lock:
            new = np.zeros((h, w, 3), dtype=np.uint8)
            oh = min(h, self.fb.shape[0])
            ow = min(w, self.fb.shape[1])
            new[:oh, :ow] = self.fb[:oh, :ow]
            self.fb = new
            self.width, self.height = w, h
        Debug.info(f"远端分辨率变更为 {w}x{h}")

    def _handle_set_colormap(self) -> None:
        head = self.stream.read_exactly(5)  # padding(1)+first(2)+count(2)
        count = struct.unpack(">H", head[3:5])[0]
        self.stream.read_exactly(count * 6)  # 丢弃（我们用 true-colour）

    def _handle_server_cut_text(self) -> None:
        head = self.stream.read_exactly(7)  # padding(3)+length(4)
        length = struct.unpack(">I", head[3:7])[0]
        self.server_cut_text = self.stream.read_exactly(length).decode("latin-1", "replace")

    # ================= 取屏 =================
    def snapshot(self, rect=None) -> np.ndarray:
        with self.fb_lock:
            if rect is None:
                return self.fb.copy()
            x, y, w, h = rect
            return np.ascontiguousarray(self.fb[y:y + h, x:x + w].copy())
