"""事件驱动观察（对应 design 第 7 节）。

当某图像/文字出现、消失，或区域发生变化时触发回调。observe() 可前台阻塞或
后台线程运行。
"""
from __future__ import annotations

import enum
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, List, Optional

from .finder import find_changes
from .geometry import Rect
from .settings import Debug, Settings, check_abort

if TYPE_CHECKING:
    from .device import Device
    from .elements import Match


class EventType(enum.Enum):
    APPEAR = "appear"
    VANISH = "vanish"
    CHANGE = "change"


@dataclass
class ObserveEvent:
    """事件载体，传给用户回调。"""

    type: EventType
    device: "Device"
    match: "Optional[Match]" = None        # APPEAR/VANISH 命中
    changes: List[Rect] = field(default_factory=list)  # CHANGE 变化区域

    def __repr__(self) -> str:
        if self.type is EventType.CHANGE:
            return f"ObserveEvent(CHANGE, {len(self.changes)} regions)"
        return f"ObserveEvent({self.type.name}, {self.match})"


@dataclass
class _Observation:
    kind: EventType
    callback: Callable[[ObserveEvent], None]
    target: object = None
    text: Optional[str] = None
    regex: bool = False
    ocr: object = None
    min_area: int = 50
    active: bool = True
    last_present: bool = False
    last_frame: object = None


class Observer:
    """持有一组观察项并驱动检测循环。"""

    def __init__(self, device: "Device"):
        self._device = device
        self._observations: list[_Observation] = []
        self._thread: "Optional[threading.Thread]" = None
        self._stop = threading.Event()

    # ---- 注册 ----
    def on_appear(self, target=None, callback=None, *, text=None, regex=False, ocr=None):
        return self._add(EventType.APPEAR, callback, target=target, text=text,
                         regex=regex, ocr=ocr)

    def on_vanish(self, target=None, callback=None, *, text=None, regex=False, ocr=None):
        return self._add(EventType.VANISH, callback, target=target, text=text,
                         regex=regex, ocr=ocr)

    def on_change(self, callback=None, *, min_area=None):
        return self._add(EventType.CHANGE, callback,
                         min_area=min_area if min_area is not None else Settings.min_change_pixels)

    def _add(self, kind, callback, **kw) -> _Observation:
        if callback is None:
            raise ValueError("必须提供 callback")
        obs = _Observation(kind=kind, callback=callback, **kw)
        self._observations.append(obs)
        return obs

    # ---- 运行 ----
    def observe(self, timeout: "Optional[float]" = None, background: bool = False):
        self._stop.clear()
        if background:
            self._thread = threading.Thread(
                target=self._loop, args=(timeout,), daemon=True, name="visauto-observer")
            self._thread.start()
            return self._thread
        self._loop(timeout)
        return None

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def _loop(self, timeout: "Optional[float]") -> None:
        interval = 1.0 / max(0.1, Settings.observe_scan_rate)
        deadline = (time.monotonic() + timeout) if timeout else None
        Debug.info(f"observe 开始（{len(self._observations)} 项, "
                   f"timeout={timeout}）")
        while not self._stop.is_set():
            check_abort()                    # 协作式中止：Stop 时抛 ScriptAborted（不被下面吞掉）
            for obs in self._observations:
                if not obs.active:
                    continue
                try:
                    self._check(obs)
                except Exception as e:  # 回调/检测异常不应中断整个循环
                    Debug.error(f"观察项异常：{e}")
            if deadline is not None and time.monotonic() >= deadline:
                break
            if self._stop.wait(interval):
                break
        Debug.info("observe 结束")

    def _check(self, obs: _Observation) -> None:
        if obs.kind is EventType.CHANGE:
            frame = self._device._capture()
            if obs.last_frame is not None:
                changes = find_changes(obs.last_frame, frame, obs.min_area)
                if changes:
                    obs.callback(ObserveEvent(
                        EventType.CHANGE, self._device,
                        changes=[Rect(c.x, c.y, c.w, c.h) for c in changes]))
            obs.last_frame = frame
            return

        match = self._device.exists(
            obs.target, text=obs.text, regex=obs.regex, ocr=obs.ocr, timeout=0)
        present = match is not None
        if obs.kind is EventType.APPEAR and present and not obs.last_present:
            obs.callback(ObserveEvent(EventType.APPEAR, self._device, match=match))
        elif obs.kind is EventType.VANISH and obs.last_present and not present:
            obs.callback(ObserveEvent(EventType.VANISH, self._device, match=None))
        obs.last_present = present
