"""OCR 引擎协议、统一结果类型与文字定位逻辑。

引擎对象自持配置（语言/GPU/模型路径），recognize 只收图；上层定位逻辑
对具体引擎无感。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import numpy as np

from ..geometry import Rect


@dataclass(frozen=True)
class OcrWord:
    """一个识别出的文本单元（词/行）及其在图像内的包围盒。"""

    text: str
    box: Rect          # 相对被识别图像左上角
    confidence: float


@runtime_checkable
class OcrEngine(Protocol):
    """OCR 引擎统一接口。所有配置在构造函数里完成。"""

    def recognize(self, image: "np.ndarray") -> list[OcrWord]:
        """识别图像，返回 OcrWord 列表（坐标相对图像左上角）。"""
        ...


# ---------------------------------------------------------------------------
# 会话默认引擎（可选）：库默认仍是“无”；显式 set 后，find(text=...) 省略 ocr= 时回退到它。
# 主要给 GUI 用——OCR 设置面板配置一次，脚本里即可省略 ocr=。
# ---------------------------------------------------------------------------
_default_engine: "OcrEngine | None" = None


def set_default_ocr(engine: "OcrEngine | None") -> None:
    global _default_engine
    _default_engine = engine


def get_default_ocr() -> "OcrEngine | None":
    return _default_engine


def locate_text(
    words: list[OcrWord],
    query: str,
    regex: bool = False,
    ignore_case: bool = True,
) -> list[OcrWord]:
    """在识别结果里按子串/正则匹配查询文本，返回命中的 OcrWord（按置信度降序）。"""
    matched: list[OcrWord] = []
    if regex:
        flags = re.IGNORECASE if ignore_case else 0
        pattern = re.compile(query, flags)
        for w in words:
            if pattern.search(w.text):
                matched.append(w)
    else:
        needle = query.lower() if ignore_case else query
        for w in words:
            hay = w.text.lower() if ignore_case else w.text
            if needle in hay:
                matched.append(w)
    matched.sort(key=lambda w: w.confidence, reverse=True)
    return matched


class TextRecognizer:
    """把“识别 + 定位”串起来的便捷封装，供 Region/Device 调用。"""

    def __init__(self, engine: OcrEngine):
        self.engine = engine

    def words(self, image: "np.ndarray") -> list[OcrWord]:
        return self.engine.recognize(image)

    def find(
        self,
        image: "np.ndarray",
        query: str,
        regex: bool = False,
        ignore_case: bool = True,
    ) -> list[OcrWord]:
        return locate_text(self.words(image), query, regex=regex, ignore_case=ignore_case)

    def read(self, image: "np.ndarray") -> str:
        """读出图像里全部文字（按从上到下、从左到右拼接）。"""
        words = self.words(image)
        words.sort(key=lambda w: (w.box.y, w.box.x))
        return " ".join(w.text for w in words)
