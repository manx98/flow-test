"""Image 与 ImagePath（对应 design 第 3 节）。

把“图片名字字符串”背后的复杂度（从文件/内存加载、缓存、记住上次命中位置）
封装起来；ImagePath 维护图片搜索路径列表。
"""
from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING

import cv2
import numpy as np

from .exceptions import VisautoError

if TYPE_CHECKING:
    from .geometry import Rect


class ImagePath:
    """图片搜索路径列表（全局单例风格）。"""

    _paths: list[str] = [os.getcwd()]
    _lock = threading.Lock()

    @classmethod
    def add(cls, path: str) -> None:
        path = os.path.abspath(path)
        with cls._lock:
            if path not in cls._paths:
                cls._paths.append(path)

    @classmethod
    def remove(cls, path: str) -> None:
        path = os.path.abspath(path)
        with cls._lock:
            if path in cls._paths:
                cls._paths.remove(path)

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._paths = [os.getcwd()]

    @classmethod
    def all(cls) -> list[str]:
        with cls._lock:
            return list(cls._paths)

    @classmethod
    def resolve(cls, filename: str) -> "str | None":
        if os.path.isabs(filename) and os.path.exists(filename):
            return filename
        for base in cls.all():
            candidate = os.path.join(base, filename)
            if os.path.exists(candidate):
                return candidate
        # 直接相对当前目录兜底
        if os.path.exists(filename):
            return os.path.abspath(filename)
        return None


# 已加载图片缓存：绝对路径 → BGR ndarray
_CACHE: dict[str, np.ndarray] = {}
_CACHE_LOCK = threading.Lock()


class Image:
    """内存中的模板图像 + 来源 + last-seen 缓存。"""

    def __init__(self, source, name: "str | None" = None):
        self._name = name
        self._mat: "np.ndarray | None" = None
        self._mask: "np.ndarray | None" = None
        # last-seen：上次命中的绝对矩形与分数（用于优化）
        self.last_seen: "Rect | None" = None
        self.last_score: float = 0.0
        self._load(source)

    # ---- 加载 ----
    def _load(self, source) -> None:
        if isinstance(source, np.ndarray):
            self._mat = self._normalize(source)
            if self._name is None:
                self._name = "<ndarray>"
            return
        if isinstance(source, str):
            path = ImagePath.resolve(source)
            if path is None:
                raise VisautoError(f"找不到图片：{source}（搜索路径 {ImagePath.all()}）")
            if self._name is None:
                self._name = source
            self._mat, self._mask = self._load_file(path)
            return
        raise VisautoError(f"无法从 {type(source)!r} 创建 Image")

    @staticmethod
    def _normalize(arr: np.ndarray):
        """统一成 BGR uint8；带 alpha 的拆出 mask。"""
        mask = None
        if arr.ndim == 2:
            arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
        elif arr.shape[2] == 4:
            mask = arr[:, :, 3].copy()
            arr = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
        if arr.dtype != np.uint8:
            arr = arr.astype(np.uint8)
        return np.ascontiguousarray(arr)

    def _load_file(self, path: str):
        with _CACHE_LOCK:
            cached = _CACHE.get(path)
        if cached is not None:
            raw = cached
        else:
            raw = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if raw is None:
                raise VisautoError(f"无法读取图片文件：{path}")
            with _CACHE_LOCK:
                _CACHE[path] = raw
        mask = None
        if raw.ndim == 3 and raw.shape[2] == 4:
            # 有 alpha：透明区域作为 mask（255 参与匹配，0 忽略）
            alpha = raw[:, :, 3]
            mask = alpha.copy()
            mat = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
        elif raw.ndim == 2:
            mat = cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)
        else:
            mat = raw
        return np.ascontiguousarray(mat), mask

    # ---- 访问 ----
    @property
    def name(self) -> str:
        return self._name or "<image>"

    @property
    def mat(self) -> np.ndarray:
        return self._mat

    @property
    def mask(self) -> "np.ndarray | None":
        return self._mask

    @property
    def width(self) -> int:
        return self._mat.shape[1]

    @property
    def height(self) -> int:
        return self._mat.shape[0]

    def remember(self, rect: "Rect", score: float) -> None:
        self.last_seen = rect
        self.last_score = score

    def __repr__(self) -> str:
        return f"Image({self.name!r}, {self.width}x{self.height})"


def as_image(obj) -> Image:
    """把 str / ndarray / Image 统一成 Image。"""
    if isinstance(obj, Image):
        return obj
    return Image(obj)


# 清理缓存（测试/换图时用）
def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
