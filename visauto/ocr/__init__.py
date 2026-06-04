"""OCR 引擎子系统（对应 design 第 4.4 节）。

库不内置默认引擎、不惰性创建；引擎由用户构造，每次 OCR 调用显式传入 ocr=。
"""
from .base import (
    OcrEngine,
    OcrWord,
    TextRecognizer,
    get_default_ocr,
    locate_text,
    set_default_ocr,
)
from .paddle import PaddleEngine
from .tesseract import TesseractEngine

__all__ = [
    "OcrEngine",
    "OcrWord",
    "TextRecognizer",
    "locate_text",
    "set_default_ocr",
    "get_default_ocr",
    "PaddleEngine",
    "TesseractEngine",
]
