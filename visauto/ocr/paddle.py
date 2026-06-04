"""PaddleEngine：封装 PaddleOCR（惰性导入、单实例复用）。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..exceptions import VisautoError
from ..geometry import Rect
from .base import OcrWord

if TYPE_CHECKING:
    import numpy as np


class PaddleEngine:
    """中文/复杂版面更强的 OCR。

    配置在构造时完成（模型加载也发生在这里，用户掌控开销时机）：
        PaddleEngine(lang="ch", use_gpu=False, det=True)
    需 pip install paddleocr paddlepaddle。
    """

    def __init__(
        self,
        lang: str = "ch",
        use_gpu: bool = False,
        use_angle_cls: bool = True,
        det: bool = True,
        min_confidence: float = 0.0,
        **paddle_kwargs,
    ):
        self.lang = lang
        self.det = det
        self.min_confidence = min_confidence
        try:
            from paddleocr import PaddleOCR
        except ImportError as e:
            raise VisautoError(
                "PaddleEngine 需要 paddleocr：pip install paddleocr paddlepaddle"
            ) from e

        kwargs = dict(lang=lang, use_angle_cls=use_angle_cls)
        # 不同 paddleocr 版本对 use_gpu 的支持不一，容错传入。
        kwargs.update(paddle_kwargs)
        try:
            self._ocr = PaddleOCR(use_gpu=use_gpu, **kwargs)
        except (TypeError, ValueError):
            # 新版可能不接受 use_gpu，去掉重试。
            self._ocr = PaddleOCR(**kwargs)

    def recognize(self, image: "np.ndarray") -> list[OcrWord]:
        # PaddleOCR 接受 numpy 数组（BGR 即可）。
        try:
            result = self._ocr.ocr(image, cls=True)
        except TypeError:
            # 新版 predict 接口不接受 cls 参数
            result = self._ocr.ocr(image)

        words: list[OcrWord] = []
        if not result:
            return words

        # 兼容 2.x：result = [ per_image ]，per_image = [ [box, (text, score)], ... ]
        per_image = result[0] if result and isinstance(result[0], list) else result
        if per_image is None:
            return words

        for line in per_image:
            try:
                box_pts, (text, score) = line
            except (ValueError, TypeError):
                continue
            text = (text or "").strip()
            if not text:
                continue
            conf = float(score)
            if conf < self.min_confidence:
                continue
            words.append(OcrWord(text=text, box=_poly_to_rect(box_pts), confidence=conf))
        return words


def _poly_to_rect(points) -> Rect:
    """4 个角点 → 轴对齐包围盒。"""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, y0 = int(min(xs)), int(min(ys))
    x1, y1 = int(max(xs)), int(max(ys))
    return Rect(x0, y0, max(1, x1 - x0), max(1, y1 - y0))
