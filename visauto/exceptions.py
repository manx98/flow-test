"""库异常类型。"""
from __future__ import annotations


class VisautoError(Exception):
    """所有 visauto 异常的基类。"""


class FindFailed(VisautoError):
    """find()/wait() 在超时内未命中目标时抛出。

    exists() 不抛此异常而是返回 None。
    """

    def __init__(self, message: str, target=None, region=None):
        super().__init__(message)
        self.target = target
        self.region = region


class OcrNotConfigured(VisautoError):
    """使用了 text= 文字查找但未传入 ocr= 引擎，且未设置会话默认引擎。"""


class ScriptAborted(VisautoError):
    """协作式中止：外部置位 abort 事件后，wait/observe 轮询循环抛出。"""


class BackendError(VisautoError):
    """后端（本地/noVNC）连接或操作失败。"""
