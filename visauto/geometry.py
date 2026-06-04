"""基础几何类型：Location 与 Rect。

所有坐标均为目标屏幕的绝对像素坐标（左上角为原点，x 向右、y 向下）。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Location:
    """屏幕上的一个点。"""

    x: int
    y: int

    def offset(self, dx: int, dy: int) -> "Location":
        return Location(self.x + dx, self.y + dy)

    def as_tuple(self) -> tuple[int, int]:
        return (self.x, self.y)

    def __iter__(self):
        yield self.x
        yield self.y


@dataclass(frozen=True)
class Rect:
    """屏幕上的一块矩形区域 (x, y, w, h)。"""

    x: int
    y: int
    w: int
    h: int

    # ---- 派生属性 ----
    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    @property
    def center(self) -> Location:
        return Location(self.x + self.w // 2, self.y + self.h // 2)

    @property
    def area(self) -> int:
        return self.w * self.h

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)

    # ---- 几何运算 ----
    def contains(self, other: "Rect | Location") -> bool:
        if isinstance(other, Location):
            return self.x <= other.x < self.right and self.y <= other.y < self.bottom
        return (
            self.x <= other.x
            and self.y <= other.y
            and other.right <= self.right
            and other.bottom <= self.bottom
        )

    def offset(self, dx: int, dy: int) -> "Rect":
        return Rect(self.x + dx, self.y + dy, self.w, self.h)

    def intersect(self, other: "Rect") -> "Rect | None":
        x = max(self.x, other.x)
        y = max(self.y, other.y)
        right = min(self.right, other.right)
        bottom = min(self.bottom, other.bottom)
        if right <= x or bottom <= y:
            return None
        return Rect(x, y, right - x, bottom - y)

    def clip_to(self, bounds: "Rect") -> "Rect | None":
        """把本矩形裁剪到 bounds 内（用于子区域不越界）。"""
        return self.intersect(bounds)
