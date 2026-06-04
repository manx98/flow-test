"""TesseractEngine：封装 pytesseract（惰性导入）。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..exceptions import VisautoError
from ..geometry import Rect
from .base import OcrWord

if TYPE_CHECKING:
    import numpy as np


class TesseractEngine:
    """轻量 OCR；适合英文/排版规整文本。

    配置在构造时完成：
        TesseractEngine(lang="chi_sim", config="--psm 6")
    需系统安装 tesseract 二进制 + pip install pytesseract。
    """

    def __init__(self, lang: str = "eng", config: str = "", min_confidence: float = 0.0):
        self.lang = lang
        self.config = config
        self.min_confidence = min_confidence
        try:
            import pytesseract  # noqa: F401
        except ImportError as e:
            raise VisautoError(
                "TesseractEngine 需要 pytesseract：pip install pytesseract，"
                "并安装系统 tesseract 二进制"
            ) from e
        self._pt = pytesseract

    def recognize(self, image: "np.ndarray") -> list[OcrWord]:
        import cv2

        # pytesseract 习惯 RGB；输入是 BGR。
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        data = self._pt.image_to_data(
            rgb, lang=self.lang, config=self.config,
            output_type=self._pt.Output.DICT,
        )
        words: list[OcrWord] = []
        n = len(data["text"])
        for i in range(n):
            text = data["text"][i].strip()
            if not text:
                continue
            try:
                conf = float(data["conf"][i])
            except (ValueError, TypeError):
                conf = -1.0
            conf = conf / 100.0 if conf >= 0 else 0.0
            if conf < self.min_confidence:
                continue
            box = Rect(
                int(data["left"][i]), int(data["top"][i]),
                int(data["width"][i]), int(data["height"][i]),
            )
            words.append(OcrWord(text=text, box=box, confidence=conf))
        return words
