"""可视元素：Element / Region / Match（对应 design 第 3 节）。

Region 是几乎所有用户动作的载体；Match 继承 Region，所以可在命中区域上继续
查找/操作。坐标统一为目标屏幕绝对坐标。
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Iterator, Optional

from .exceptions import FindFailed, OcrNotConfigured
from .finder import match_all, match_template
from .geometry import Location, Rect
from .ocr.base import OcrEngine, TextRecognizer, get_default_ocr
from .pattern import Pattern, as_pattern
from .settings import Debug, Settings, check_abort

if TYPE_CHECKING:
    import numpy as np

    from .backends.base import Button


class Element:
    """坐标抽象基类：x, y, w, h + center。"""

    def __init__(self, x: int, y: int, w: int, h: int):
        self.x = x
        self.y = y
        self.w = w
        self.h = h

    @property
    def rect(self) -> Rect:
        return Rect(self.x, self.y, self.w, self.h)

    @property
    def center(self) -> Location:
        return self.rect.center

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.x},{self.y},{self.w},{self.h})"


class Region(Element):
    """屏幕上的一块矩形区域，承载 find/wait/click/type/observe。"""

    def __init__(self, x: int, y: int, w: int, h: int, device: "Device"):
        super().__init__(x, y, w, h)
        self._device = device

    # ---- 子区域 ----
    def region(self, x: int, y: int, w: int, h: int) -> "Region":
        """以本区域左上角为原点切出子区域（坐标相对本区域）。"""
        return Region(self.x + x, self.y + y, w, h, self._device)

    # ---- 截屏 ----
    def _capture(self) -> "np.ndarray":
        return self._device.backend.capture(self.rect)

    # =====================================================================
    # 查找
    # =====================================================================
    def _search(
        self,
        target=None,
        *,
        text: "Optional[str]" = None,
        regex: bool = False,
        ocr: "Optional[OcrEngine]" = None,
        find_all: bool = False,
    ) -> "list[Match]":
        """单次截屏 + 查找，返回 Match 列表（图像或 OCR）。"""
        screen = self._capture()
        if text is not None:
            return self._search_text(screen, text, regex, ocr, find_all)
        return self._search_image(screen, target, find_all)

    def _search_image(self, screen, target, find_all: bool) -> "list[Match]":
        pattern: Pattern = as_pattern(target)
        sim = pattern.similarity if pattern.similarity is not None else Settings.min_similarity
        image = pattern.image

        if find_all:
            raws = match_all(screen, image.mat, sim, mask=pattern.mask, gray=pattern.gray)
            return [self._raw_to_match(r, pattern) for r in raws]

        # last-seen 优化：先在上次命中处的小窗口校验。
        quick = self._check_last_seen(image, pattern, sim)
        if quick is not None:
            return [quick]

        raw = match_template(screen, image.mat, sim, mask=pattern.mask, gray=pattern.gray)
        if raw is None:
            return []
        m = self._raw_to_match(raw, pattern)
        image.remember(m.rect, m.score)
        return [m]

    def _check_last_seen(self, image, pattern, sim) -> "Optional[Match]":
        last = image.last_seen
        if last is None:
            return None
        if not self.rect.contains(last):
            return None
        # 截取上次命中矩形稍作扩展的小窗口，单独验证。
        pad = 4
        win = Rect(last.x - pad, last.y - pad, last.w + 2 * pad, last.h + 2 * pad)
        win = win.clip_to(self.rect)
        if win is None:
            return None
        sub = self._device.backend.capture(win)
        raw = match_template(sub, image.mat, sim, mask=pattern.mask, gray=pattern.gray)
        if raw is None:
            return None
        # 把窗口内坐标平移回绝对坐标。
        abs_raw = raw.__class__(win.x + raw.x, win.y + raw.y, raw.w, raw.h, raw.score)
        Debug.trace(f"last-seen 命中 {image.name} @ {abs_raw}")
        return Match.from_raw(abs_raw, pattern, self._device)

    def _raw_to_match(self, raw, pattern: Pattern) -> "Match":
        # raw 坐标相对截屏（即相对本区域左上角）→ 加上区域原点得绝对坐标。
        abs_raw = raw.__class__(self.x + raw.x, self.y + raw.y, raw.w, raw.h, raw.score)
        return Match.from_raw(abs_raw, pattern, self._device)

    def ai_locate(self, desc, *, ai, kind: str = "image") -> "Optional[Match]":
        """用 AI 视觉大模型按描述在本区域画面里定位目标，命中返回 Match，否则 None。

        kind: 'image'(视觉元素) | 'text'(文字)。坐标由模型给出（归一化），换算成绝对像素。
        """
        from .ai.engine import build_prompt
        if ai is None:
            raise OcrNotConfigured("AI 查找需要传入 ai= 引擎")
        screen = self._capture()
        found, box, conf = ai.locate(screen, build_prompt(kind, str(desc)))
        if not found or box is None:
            return None
        h_img, w_img = screen.shape[:2]
        x = self.x + int(box[0] * w_img)
        y = self.y + int(box[1] * h_img)
        w = max(1, int(box[2] * w_img))
        h = max(1, int(box[3] * h_img))
        return Match(x, y, w, h, conf, self._device, ocr_text=str(desc))

    def ai_agent(self, goal, *, ai, max_steps: int = 15, on_step=None):
        """AI 计算机操作代理：用大模型看屏并自动执行多步动作完成 goal。

        返回 (ok: bool, message: str, steps: int)。on_step(step, action, screen, target_xy)
        每步回调（回显/日志用）。中止经 check_abort 协作式响应。
        """
        from .ai.agent import run_agent
        if ai is None:
            raise OcrNotConfigured("AI 代理需要传入 ai= 引擎")
        return run_agent(self, goal, ai=ai, max_steps=max_steps, on_step=on_step)

    def _search_text(self, screen, text, regex, ocr, find_all) -> "list[Match]":
        if ocr is None:
            ocr = get_default_ocr()          # 回退到会话默认引擎（GUI 配置）
        if ocr is None:
            raise OcrNotConfigured(
                "使用了 text= 文字查找，但未传入 ocr= 引擎，也未设置会话默认引擎；"
                "请创建引擎并以 ocr= 传入，或调用 visauto.set_default_ocr(engine)"
            )
        recognizer = TextRecognizer(ocr)
        words = recognizer.find(screen, text, regex=regex)
        matches = []
        for w in words:
            box = w.box.offset(self.x, self.y)  # 相对区域 → 绝对
            matches.append(Match(box.x, box.y, box.w, box.h, w.confidence,
                                 self._device, ocr_text=w.text))
            if not find_all:
                break
        return matches

    # ---- 重试框架（对应 design 第 6 节 Repeatable）----
    def _repeat_until(self, fn, timeout: "Optional[float]"):
        """在 timeout 内按 wait_scan_rate 轮询 fn()，命中(返回真值)即返回；超时返回 None。"""
        if timeout is None:
            timeout = Settings.auto_wait_timeout
        interval = 1.0 / max(0.1, Settings.wait_scan_rate)
        deadline = time.monotonic() + timeout
        while True:
            check_abort()                    # 协作式中止：Stop 时抛 ScriptAborted
            result = fn()
            if result:
                return result
            if time.monotonic() >= deadline:
                return None
            time.sleep(interval)

    # ---- 公共查找 API ----
    def find(self, target=None, *, text=None, regex=False, ocr=None,
             timeout=None) -> "Match":
        result = self._repeat_until(
            lambda: (self._search(target, text=text, regex=regex, ocr=ocr) or [None])[0],
            timeout,
        )
        if result is None:
            raise FindFailed(f"未找到目标：{_desc(target, text)}", target=target, region=self.rect)
        return result

    def exists(self, target=None, *, text=None, regex=False, ocr=None,
               timeout=None) -> "Optional[Match]":
        if timeout is None:
            timeout = 0.0
        return self._repeat_until(
            lambda: (self._search(target, text=text, regex=regex, ocr=ocr) or [None])[0],
            timeout,
        )

    def wait(self, target=None, *, text=None, regex=False, ocr=None,
             timeout=None) -> "Match":
        return self.find(target, text=text, regex=regex, ocr=ocr, timeout=timeout)

    def wait_vanish(self, target=None, *, text=None, regex=False, ocr=None,
                    timeout=None) -> bool:
        """等目标消失；超时仍在则返回 False。"""
        gone = self._repeat_until(
            lambda: not self._search(target, text=text, regex=regex, ocr=ocr),
            timeout,
        )
        return bool(gone)

    def find_all(self, target=None, *, text=None, regex=False, ocr=None,
                 timeout=None) -> "list[Match]":
        result = self._repeat_until(
            lambda: self._search(target, text=text, regex=regex, ocr=ocr, find_all=True) or None,
            timeout,
        )
        return result or []

    # ---- OCR 读取 ----
    def read_text(self, ocr: "Optional[OcrEngine]" = None) -> str:
        if ocr is None:
            raise OcrNotConfigured("read_text 需要传入 ocr= 引擎")
        return TextRecognizer(ocr).read(self._capture())

    # =====================================================================
    # 动作：target=None 时作用于本区域中心；否则先 find 再操作
    # =====================================================================
    def _resolve_target_point(self, target, text, regex, ocr, timeout) -> Location:
        if target is None and text is None:
            return self.center
        m = self.find(target, text=text, regex=regex, ocr=ocr, timeout=timeout)
        return m.target

    def click(self, target=None, *, text=None, regex=False, ocr=None, timeout=None) -> "Location":
        p = self._resolve_target_point(target, text, regex, ocr, timeout)
        self._device.mouse.click(p.x, p.y)
        self._maybe_highlight(target, text)
        return p

    def double_click(self, target=None, *, text=None, regex=False, ocr=None, timeout=None) -> "Location":
        p = self._resolve_target_point(target, text, regex, ocr, timeout)
        self._device.mouse.double_click(p.x, p.y)
        return p

    def right_click(self, target=None, *, text=None, regex=False, ocr=None, timeout=None) -> "Location":
        p = self._resolve_target_point(target, text, regex, ocr, timeout)
        self._device.mouse.right_click(p.x, p.y)
        return p

    def hover(self, target=None, *, text=None, regex=False, ocr=None, timeout=None) -> "Location":
        p = self._resolve_target_point(target, text, regex, ocr, timeout)
        self._device.mouse.hover(p.x, p.y)
        return p

    def drag_drop(self, src, dst, *, ocr=None, timeout=None) -> None:
        """从 src 拖到 dst；二者可为目标(图片/Pattern)或 (x,y)/Location。"""
        p1 = self._point_of(src, ocr, timeout)
        p2 = self._point_of(dst, ocr, timeout)
        self._device.mouse.drag_drop(p1.x, p1.y, p2.x, p2.y)

    def _point_of(self, obj, ocr, timeout) -> Location:
        if isinstance(obj, Location):
            return obj
        if isinstance(obj, (tuple, list)) and len(obj) == 2:
            return Location(int(obj[0]), int(obj[1]))
        if isinstance(obj, Element):
            return obj.center
        return self.find(obj, ocr=ocr, timeout=timeout).target

    def scroll(self, dx: int, dy: int, target=None, *, ocr=None, timeout=None) -> None:
        p = self._resolve_target_point(target, None, False, ocr, timeout)
        self._device.mouse.scroll(p.x, p.y, dx, dy)

    # ---- 键盘 ----
    def type(self, text: str, modifiers=None) -> None:
        self._device.keyboard.type(text, modifiers=modifiers)

    def press_key(self, key: str, modifiers=None) -> None:
        self._device.keyboard.press_key(key, modifiers=modifiers)

    def paste(self, text: str) -> None:
        self._device.keyboard.paste(text)

    # ---- 高亮 ----
    def highlight(self, duration: "Optional[float]" = None) -> None:
        from .highlight import highlight_rect
        highlight_rect(self.rect, duration if duration is not None else Settings.highlight_duration)

    def _maybe_highlight(self, target, text) -> None:
        if Settings.highlight and (target is not None or text is not None):
            self.highlight()


class Match(Region):
    """一次命中：带 score / target / (ocr_text) 的 Region。"""

    def __init__(self, x, y, w, h, score, device, *,
                 target_offset: tuple[int, int] = (0, 0),
                 ocr_text: "Optional[str]" = None):
        super().__init__(x, y, w, h, device)
        self.score = score
        self._target_offset = target_offset
        self.ocr_text = ocr_text

    @property
    def target(self) -> Location:
        """点击目标点：命中中心 + 偏移。"""
        c = self.center
        return c.offset(self._target_offset[0], self._target_offset[1])

    @classmethod
    def from_raw(cls, raw, pattern: Pattern, device) -> "Match":
        return cls(raw.x, raw.y, raw.w, raw.h, raw.score, device,
                   target_offset=pattern.offset)

    def __repr__(self) -> str:
        extra = f" '{self.ocr_text}'" if self.ocr_text else ""
        return (f"Match({self.x},{self.y},{self.w},{self.h} "
                f"score={self.score:.3f}{extra})")


def _desc(target, text) -> str:
    if text is not None:
        return f"text={text!r}"
    return repr(target)


if TYPE_CHECKING:
    from .device import Device
