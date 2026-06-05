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
        ocr_version: str = "auto",   # OCR 模型版本：auto(最新) | PP-OCRv5 | PP-OCRv4 | PP-OCRv3
        api_version: str = "auto",   # auto | 2.x | 3.x：强制按某代包 API 初始化/解析（内部用）
        **paddle_kwargs,
    ):
        self.lang = lang
        self.det = det
        self.min_confidence = min_confidence
        v = str(api_version).lower().lstrip("v")
        self._api = "3" if v.startswith("3") else "2" if v.startswith("2") else "auto"
        if ocr_version and str(ocr_version).lower() != "auto":
            paddle_kwargs.setdefault("ocr_version", ocr_version)   # 选 PP-OCRv5/v4/v3 模型
        try:
            from paddleocr import PaddleOCR
        except ImportError as e:
            raise VisautoError(
                "PaddleEngine 需要 paddleocr：pip install paddleocr paddlepaddle"
            ) from e

        # 3.x 关 mkldnn 规避 paddle 3.x 的 oneDNN 推理 bug；按 api_version 选尝试顺序
        three = [
            dict(lang=lang, use_textline_orientation=use_angle_cls,
                 device=("gpu" if use_gpu else "cpu"), enable_mkldnn=False),
            dict(lang=lang, use_textline_orientation=use_angle_cls, enable_mkldnn=False),
        ]
        two = [
            dict(lang=lang, use_angle_cls=use_angle_cls, use_gpu=use_gpu),
            dict(lang=lang),
        ]
        attempts = three if self._api == "3" else two if self._api == "2" else three + two

        last_err = None
        self._ocr = None
        for kw in attempts:
            try:
                kw.update(paddle_kwargs)
                self._ocr = PaddleOCR(**kw)
                break
            except (TypeError, ValueError) as e:
                last_err = e
        if self._ocr is None:
            raise VisautoError(f"PaddleOCR 初始化失败：{last_err}")

    def recognize(self, image: "np.ndarray") -> list[OcrWord]:
        # 3.x：predict() 返回 [OCRResult(dict)]，含 rec_texts/rec_scores/rec_polys
        if self._api in ("auto", "3") and hasattr(self._ocr, "predict"):
            try:
                res = self._ocr.predict(image)
            except Exception:
                res = None
            words = self._parse_v3(res)
            if words is not None:
                return words
            if self._api == "3":
                return []

        # 2.x：ocr(image[, cls]) → [ [ [box, (text, score)], ... ] ]
        try:
            result = self._ocr.ocr(image, cls=True)
        except TypeError:
            result = self._ocr.ocr(image)
        return self._parse_v2(result)

    def _parse_v3(self, res) -> "list[OcrWord] | None":
        if not isinstance(res, list) or not res:
            return None
        r0 = res[0]
        if not hasattr(r0, "get") or r0.get("rec_texts") is None:
            return None

        # 注意：rec_* 可能是 numpy 数组，不能用 `x or []`（对数组取布尔会报歧义）
        def _aslist(v):
            return list(v) if v is not None else []

        texts = _aslist(r0.get("rec_texts"))
        scores = _aslist(r0.get("rec_scores"))
        polys = r0.get("rec_polys")
        if polys is None:
            polys = r0.get("dt_polys")
        if polys is None:
            polys = r0.get("rec_boxes")
        polys = _aslist(polys)
        words: list[OcrWord] = []
        for i, t in enumerate(texts):
            t = (str(t) or "").strip()
            if not t:
                continue
            conf = float(scores[i]) if i < len(scores) else 1.0
            if conf < self.min_confidence:
                continue
            box = _poly_to_rect(polys[i]) if i < len(polys) else Rect(0, 0, 1, 1)
            words.append(OcrWord(text=t, box=box, confidence=conf))
        return words

    def _parse_v2(self, result) -> list[OcrWord]:
        words: list[OcrWord] = []
        if not result:
            return words
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
