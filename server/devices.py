"""设备会话管理：节点配置 → visauto Device（local/noVNC/RDP），生命周期管理。"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field

import visauto


@dataclass
class DeviceSession:
    id: str
    kind: str                 # local | novnc | rdp
    config: dict
    device: object = None     # visauto Device
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def connect(self) -> None:
        """阻塞连接（调用方放线程池执行）。"""
        kind = self.kind
        cfg = self.config or {}
        if kind == "local":
            self.device = visauto.connect_local(monitor=int(cfg.get("monitor", 1)))
        elif kind == "novnc":
            self.device = visauto.connect_novnc(
                cfg.get("url", ""), password=cfg.get("password") or None)
        elif kind == "rdp":
            self.device = visauto.connect_rdp(
                cfg.get("host", "127.0.0.1"),
                password=cfg.get("password") or None,
                username=cfg.get("username") or None,
                domain=cfg.get("domain") or None,
                auth=cfg.get("auth", "auto"),
                port=int(cfg.get("port", 3389)),
                width=int(cfg.get("width", 1280)),
                height=int(cfg.get("height", 800)),
                connect_timeout=float(cfg.get("connect_timeout", 60)),
                first_update_timeout=float(cfg.get("first_update_timeout", 30)),
            )
        elif kind == "pve":
            from .consoles import connect_pve
            self.device = connect_pve(cfg)
        elif kind == "vmware":
            from .consoles import connect_vmware
            self.device = connect_vmware(cfg)
        else:
            raise ValueError(f"未知设备类型：{kind}")

    @property
    def backend(self):
        return self.device.backend

    def screen_size(self):
        return self.device.backend.screen_size

    def close(self) -> None:
        if self.device is not None:
            try:
                self.device.close()
            except Exception:
                pass
            self.device = None


class SessionManager:
    def __init__(self):
        self._sessions: dict[str, DeviceSession] = {}
        self._by_node: dict[tuple, str] = {}   # (project, node_id) -> session_id
        self._lock = threading.Lock()

    def create(self, kind: str, config: dict,
               project: str | None = None, node_id=None) -> DeviceSession:
        sid = uuid.uuid4().hex[:12]
        sess = DeviceSession(id=sid, kind=kind, config=config or {})
        sess.connect()                 # 阻塞；调用方已在 executor 里
        with self._lock:
            self._sessions[sid] = sess
            if project is not None and node_id is not None:
                self._by_node[(project, node_id)] = sid
        return sess

    def get(self, sid: str) -> "DeviceSession | None":
        with self._lock:
            return self._sessions.get(sid)

    def get_by_node(self, project: str, node_id) -> "DeviceSession | None":
        """取某工程某设备节点已连接的 live-view 会话（供运行复用）。"""
        with self._lock:
            sid = self._by_node.get((project, node_id))
            sess = self._sessions.get(sid) if sid else None
        if sess is not None and _session_alive(sess):
            return sess
        return None

    def close(self, sid: str) -> None:
        with self._lock:
            sess = self._sessions.pop(sid, None)
            for k, v in list(self._by_node.items()):
                if v == sid:
                    del self._by_node[k]
        if sess:
            sess.close()

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            self._by_node.clear()
        for s in sessions:
            s.close()


def _session_alive(sess: "DeviceSession") -> bool:
    if sess.device is None:
        return False
    alive = getattr(sess.device.backend, "is_alive", None)
    return alive() if alive is not None else True


# 进程级单例
sessions = SessionManager()
