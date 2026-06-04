"""visauto —— 基于计算机视觉的 GUI 自动化库。

设计参考 SikuliX（见 design.md / py-design.md）：截屏 → OpenCV 找图/OCR →
模拟鼠标键盘，支持本地与 noVNC 远程后端。

快速上手：

    from visauto import connect_local, Pattern
    dev = connect_local()
    dev.click("login.png")
    dev.wait("home.png", timeout=10)

OCR（引擎由用户创建并显式传入）：

    from visauto.ocr import PaddleEngine
    ocr = PaddleEngine(lang="ch")
    dev.click(text="提交", ocr=ocr)
"""
from __future__ import annotations

from .backends.base import Backend, Button
from .device import Device, connect_local, connect_novnc, connect_rdp
from .elements import Element, Match, Region
from .exceptions import (
    BackendError,
    FindFailed,
    OcrNotConfigured,
    ScriptAborted,
    VisautoError,
)
from .geometry import Location, Rect
from .image import Image, ImagePath
from .input import Key
from .observer import EventType, ObserveEvent
from .ocr.base import get_default_ocr, set_default_ocr
from .pattern import Pattern
from .settings import (
    Debug,
    Settings,
    check_abort,
    clear_abort_event,
    set_abort_event,
)

__version__ = "0.1.0"

__all__ = [
    # 入口
    "connect_local",
    "connect_novnc",
    "connect_rdp",
    "Device",
    # 元素
    "Element",
    "Region",
    "Match",
    "Image",
    "ImagePath",
    "Pattern",
    "Location",
    "Rect",
    # 输入
    "Key",
    "Button",
    # 观察
    "EventType",
    "ObserveEvent",
    # OCR 会话默认引擎
    "set_default_ocr",
    "get_default_ocr",
    # 协作式中止
    "set_abort_event",
    "clear_abort_event",
    "check_abort",
    # 配置/异常
    "Settings",
    "Debug",
    "Backend",
    "VisautoError",
    "FindFailed",
    "OcrNotConfigured",
    "ScriptAborted",
    "BackendError",
    "__version__",
]
