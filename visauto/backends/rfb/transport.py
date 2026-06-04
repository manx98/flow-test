"""WSStream：把 noVNC 的 websocket 二进制帧缓冲成可按字节精确读取的流。

RFB 是面向字节流的协议，但 websocket 以“帧”为单位收发，帧边界与 RFB 消息
边界不对齐，故需内部缓冲并提供 read_exactly(n)。
"""
from __future__ import annotations

import threading

from ...exceptions import BackendError


class WSStream:
    """对 websocket 连接的字节流封装。读由后台线程独占；写加锁可多线程。"""

    def __init__(self, url: str, subprotocols=("binary",), timeout: float = 10.0,
                 header=None, **ws_kwargs):
        try:
            import websocket  # websocket-client
        except ImportError as e:  # pragma: no cover
            raise BackendError(
                "noVNC 后端需要 websocket-client：pip install websocket-client"
            ) from e
        self._ws = websocket.create_connection(
            url,
            subprotocols=list(subprotocols),
            timeout=timeout,
            enable_multithread=True,
            header=header or [],
            **ws_kwargs,
        )
        # 连接建立后切换为阻塞读（无超时），由上层 close 中断。
        self._ws.settimeout(None)
        self._buf = bytearray()
        self._send_lock = threading.Lock()
        self._closed = False

    def read_exactly(self, n: int) -> bytes:
        """精确读取 n 字节，不足则继续从 websocket 收帧。"""
        while len(self._buf) < n:
            try:
                data = self._ws.recv()
            except Exception as e:
                raise BackendError(f"websocket 读失败：{e}") from e
            if data is None or data == b"" or data == "":
                raise BackendError("websocket 连接已被对端关闭")
            if isinstance(data, str):
                # websockify 一般用二进制帧；万一收到文本帧按 latin-1 还原字节。
                data = data.encode("latin-1")
            self._buf.extend(data)
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def write(self, data: bytes) -> None:
        with self._send_lock:
            if self._closed:
                return
            try:
                self._ws.send_binary(data)
            except Exception as e:
                raise BackendError(f"websocket 写失败：{e}") from e

    def close(self) -> None:
        self._closed = True
        try:
            self._ws.close()
        except Exception:
            pass
