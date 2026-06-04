"""Pattern：当需要非默认相似度、点击偏移、mask、灰度时包装 Image。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .image import Image, as_image

if TYPE_CHECKING:
    import numpy as np


class Pattern:
    """Image + similarity + offset(点击偏移) + mask + gray。"""

    def __init__(
        self,
        source,
        similarity: "float | None" = None,
        offset: tuple[int, int] = (0, 0),
        mask: "np.ndarray | None" = None,
        gray: bool = False,
    ):
        self.image: Image = as_image(source)
        self.similarity = similarity          # None → 用 Settings.min_similarity
        self.offset = offset                  # 点击目标相对命中中心的偏移
        self._mask = mask
        self.gray = gray

    @property
    def mask(self):
        return self._mask if self._mask is not None else self.image.mask

    # —— 流式配置（返回新 Pattern，便于链式）——
    def similar(self, value: float) -> "Pattern":
        return self._copy(similarity=value)

    def target_offset(self, dx: int, dy: int) -> "Pattern":
        return self._copy(offset=(dx, dy))

    def grayscale(self, value: bool = True) -> "Pattern":
        return self._copy(gray=value)

    def _copy(self, **kw) -> "Pattern":
        params = dict(
            source=self.image,
            similarity=self.similarity,
            offset=self.offset,
            mask=self._mask,
            gray=self.gray,
        )
        params.update(kw)
        return Pattern(**params)

    def __repr__(self) -> str:
        return (
            f"Pattern({self.image.name!r}, similarity={self.similarity}, "
            f"offset={self.offset}, gray={self.gray})"
        )


def as_pattern(obj) -> Pattern:
    """把 str / ndarray / Image / Pattern 统一成 Pattern。"""
    if isinstance(obj, Pattern):
        return obj
    return Pattern(obj)
