"""设备后端：把“屏幕捕获 + 输入模拟”抽象为可插拔的 Backend。"""
from .base import Backend, Button, Frame

__all__ = ["Backend", "Button", "Frame"]
