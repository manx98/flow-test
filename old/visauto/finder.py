"""找图引擎（对应 design 第 4 节）：纯 numpy/OpenCV，不关心屏幕来源。

输入：screen(BGR ndarray) + 模板(BGR ndarray, 可带 mask) + 阈值；
输出：命中坐标与分数（相对 screen 左上角）。
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class RawMatch:
    """一次模板命中（坐标相对被搜索图左上角）。"""

    x: int
    y: int
    w: int
    h: int
    score: float


def _is_solid_color(template: np.ndarray) -> bool:
    """纯色图判定：所有像素几乎相同。"""
    if template.size == 0:
        return False
    std = float(template.reshape(-1, template.shape[-1]).std(axis=0).mean())
    return std < 1.0


def _pick_method(template: np.ndarray, mask: "np.ndarray | None", gray: bool):
    """根据图像特征选择 OpenCV 匹配方法（复刻 design 4.2）。"""
    if mask is not None:
        return cv2.TM_CCORR_NORMED
    if _is_solid_color(template):
        return cv2.TM_SQDIFF_NORMED
    return cv2.TM_CCOEFF_NORMED


def _to_match_space(method: int, result: np.ndarray) -> np.ndarray:
    """统一成“分数越大越好、范围 0~1”的得分图。

    TM_SQDIFF_NORMED 是越小越好，这里翻转成 1 - x。
    """
    if method == cv2.TM_SQDIFF_NORMED:
        return 1.0 - result
    return result


def _prepare(img: np.ndarray, template: np.ndarray, gray: bool):
    if gray:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    return img, template


def match_template(
    screen: np.ndarray,
    template: np.ndarray,
    similarity: float,
    mask: "np.ndarray | None" = None,
    gray: bool = False,
) -> "RawMatch | None":
    """在 screen 中找 template 的最佳单一命中，分数 >= similarity 才返回。"""
    if (
        template.shape[0] > screen.shape[0]
        or template.shape[1] > screen.shape[1]
    ):
        return None

    method = _pick_method(template, mask, gray)
    s_img, t_img = _prepare(screen, template, gray)

    if mask is not None and method == cv2.TM_CCORR_NORMED:
        result = cv2.matchTemplate(s_img, t_img, method, mask=mask)
    else:
        result = cv2.matchTemplate(s_img, t_img, method)

    result = _to_match_space(method, result)
    # mask 匹配可能产生 inf/nan，清洗。
    result = np.where(np.isfinite(result), result, 0.0)

    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < similarity:
        return None
    h, w = template.shape[:2]
    return RawMatch(int(max_loc[0]), int(max_loc[1]), w, h, float(max_val))


def match_all(
    screen: np.ndarray,
    template: np.ndarray,
    similarity: float,
    mask: "np.ndarray | None" = None,
    gray: bool = False,
    max_matches: int = 100,
) -> list[RawMatch]:
    """找出所有命中，按分数降序，做非极大值抑制式去重。"""
    if (
        template.shape[0] > screen.shape[0]
        or template.shape[1] > screen.shape[1]
    ):
        return []

    method = _pick_method(template, mask, gray)
    s_img, t_img = _prepare(screen, template, gray)

    if mask is not None and method == cv2.TM_CCORR_NORMED:
        result = cv2.matchTemplate(s_img, t_img, method, mask=mask)
    else:
        result = cv2.matchTemplate(s_img, t_img, method)
    result = _to_match_space(method, result)
    result = np.where(np.isfinite(result), result, 0.0).copy()

    h, w = template.shape[:2]
    matches: list[RawMatch] = []
    while len(matches) < max_matches:
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val < similarity:
            break
        x, y = int(max_loc[0]), int(max_loc[1])
        matches.append(RawMatch(x, y, w, h, float(max_val)))
        # NMS：把命中邻域（模板尺寸窗口）压低，避免重复命中同一目标。
        x0 = max(0, x - w // 2)
        y0 = max(0, y - h // 2)
        x1 = min(result.shape[1], x + w // 2 + 1)
        y1 = min(result.shape[0], y + h // 2 + 1)
        result[y0:y1, x0:x1] = -1.0
    return matches


def find_changes(
    before: np.ndarray,
    after: np.ndarray,
    min_area: int = 50,
) -> list[RawMatch]:
    """图像差分找变化区域（对应 design 第 7 节 CHANGE 事件）。

    灰度差 → 阈值化 → 形态学闭运算 → findContours，返回各变化区域包围盒
    （score 字段复用为该区域面积归一值，固定为 1.0）。
    """
    if before.shape != after.shape:
        # 尺寸变了，视为整屏变化。
        h, w = after.shape[:2]
        return [RawMatch(0, 0, w, h, 1.0)]

    g1 = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)
    diff = cv2.absdiff(g1, g2)
    _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
    kernel = np.ones((5, 5), np.uint8)
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    out: list[RawMatch] = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w * h < min_area:
            continue
        out.append(RawMatch(int(x), int(y), int(w), int(h), 1.0))
    return out
