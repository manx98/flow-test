"""ScreenView：实时画面视图。

职责：显示实时帧、缩放与坐标映射、Control 模式输入转发、Capture 瞬态橡皮筋框选、
命中高亮叠加。所有「转发到远端」的动作以信号发出，由 MainWindow 调度到 backend。
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from .qt import Qt, QtCore, QtGui, QtWidgets, pyqtSignal

# Qt 特殊键 → visauto 规范键名
_SPECIAL_KEYS = {
    Qt.Key.Key_Return: "enter",
    Qt.Key.Key_Enter: "enter",
    Qt.Key.Key_Backspace: "backspace",
    Qt.Key.Key_Tab: "tab",
    Qt.Key.Key_Escape: "esc",
    Qt.Key.Key_Delete: "delete",
    Qt.Key.Key_Up: "up",
    Qt.Key.Key_Down: "down",
    Qt.Key.Key_Left: "left",
    Qt.Key.Key_Right: "right",
    Qt.Key.Key_Home: "home",
    Qt.Key.Key_End: "end",
    Qt.Key.Key_PageUp: "pageup",
    Qt.Key.Key_PageDown: "pagedown",
}

_BUTTON_NAME = {
    Qt.MouseButton.LeftButton: "left",
    Qt.MouseButton.RightButton: "right",
    Qt.MouseButton.MiddleButton: "middle",
}


class ScreenView(QtWidgets.QWidget):
    mouseMoveDev = pyqtSignal(int, int)
    mousePressDev = pyqtSignal(int, int, str)
    mouseReleaseDev = pyqtSignal(int, int, str)
    wheelDev = pyqtSignal(int, int, int)
    typeText = pyqtSignal(str)
    keyPressName = pyqtSignal(str)
    regionCaptured = pyqtSignal(int, int, int, int)   # 设备坐标
    cursorPos = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus if hasattr(Qt, "FocusPolicy")
                            else Qt.StrongFocus)
        self._image: Optional[QtGui.QImage] = None
        self._scale_mode = "fit"     # "fit" 或浮点缩放
        self._scale = 1.0
        self._offset = (0, 0)
        self._capture_mode = False
        self._frozen: Optional[QtGui.QImage] = None
        self._rubber_start: Optional[QtCore.QPoint] = None
        self._rubber_now: Optional[QtCore.QPoint] = None
        self._highlights: List[Tuple[tuple, str]] = []  # ((x,y,w,h), label)
        # 高亮自动淡出
        self._hl_opacity = 1.0
        self._auto_clear_ms = 3000          # 保持时长（0=不自动清除）
        self._hold_timer = QtCore.QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self._start_fade)
        self._fade_timer = QtCore.QTimer(self)
        self._fade_timer.setInterval(40)
        self._fade_timer.timeout.connect(self._fade_step)
        self.setStyleSheet("background:#202020;")

    # ================= 帧 =================
    def set_frame(self, image: QtGui.QImage) -> None:
        if self._capture_mode:
            return  # 冻结期间不刷新
        self._image = image
        self.update()

    def _active_image(self) -> Optional[QtGui.QImage]:
        return self._frozen if self._capture_mode else self._image

    def clear(self) -> None:
        """彻底清空画面（断开时调用）：清帧、退出冻结/Capture、清高亮。"""
        self._image = None
        self._frozen = None
        self._capture_mode = False
        self._rubber_start = self._rubber_now = None
        self._hold_timer.stop()
        self._fade_timer.stop()
        self._highlights = []
        self._hl_opacity = 1.0
        self.unsetCursor()
        self.update()

    # ================= 缩放/坐标 =================
    def set_zoom(self, mode) -> None:
        """mode: 'fit' 或 浮点(1.0=100%)。"""
        self._scale_mode = mode
        self.update()

    def _recompute_geometry(self, img: QtGui.QImage):
        iw, ih = img.width(), img.height()
        if iw == 0 or ih == 0:
            return 1.0, (0, 0), 0, 0
        if self._scale_mode == "fit":
            scale = min(self.width() / iw, self.height() / ih)
        else:
            scale = float(self._scale_mode)
        dw, dh = iw * scale, ih * scale
        offx = (self.width() - dw) / 2
        offy = (self.height() - dh) / 2
        self._scale = scale
        self._offset = (offx, offy)
        return scale, (offx, offy), dw, dh

    def widget_to_device(self, pos) -> Tuple[int, int]:
        img = self._active_image()
        if img is None or self._scale == 0:
            return 0, 0
        offx, offy = self._offset
        dx = int((pos.x() - offx) / self._scale)
        dy = int((pos.y() - offy) / self._scale)
        dx = max(0, min(img.width() - 1, dx))
        dy = max(0, min(img.height() - 1, dy))
        return dx, dy

    def device_to_widget(self, x, y) -> Tuple[float, float]:
        offx, offy = self._offset
        return x * self._scale + offx, y * self._scale + offy

    # ================= 高亮 =================
    def set_auto_clear(self, seconds: float) -> None:
        """标记保持时长（秒）；0 表示不自动淡出。"""
        self._auto_clear_ms = max(0, int(seconds * 1000))

    def set_highlights(self, rects_with_labels) -> None:
        self._highlights = list(rects_with_labels)
        self._hl_opacity = 1.0
        self._hold_timer.stop()
        self._fade_timer.stop()
        if self._highlights and self._auto_clear_ms > 0:
            self._hold_timer.start(self._auto_clear_ms)   # 保持 N 秒后开始淡出
        self.update()

    def clear_highlights(self) -> None:
        self._hold_timer.stop()
        self._fade_timer.stop()
        self._highlights = []
        self._hl_opacity = 1.0
        self.update()

    def _start_fade(self) -> None:
        self._fade_timer.start()

    def _fade_step(self) -> None:
        self._hl_opacity -= 0.08          # ~0.5s 淡出
        if self._hl_opacity <= 0:
            self._fade_timer.stop()
            self._highlights = []
            self._hl_opacity = 1.0
        self.update()

    # ================= Capture 瞬态 =================
    def begin_capture(self) -> None:
        if self._image is None:
            return
        self._frozen = self._image
        self._capture_mode = True
        self._rubber_start = self._rubber_now = None
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.update()

    def _end_capture(self) -> None:
        self._capture_mode = False
        self._frozen = None
        self._rubber_start = self._rubber_now = None
        self.unsetCursor()
        self.update()

    # ================= 绘制 =================
    def paintEvent(self, _ev) -> None:
        painter = QtGui.QPainter(self)
        img = self._active_image()
        if img is None or img.isNull():
            painter.setPen(QtGui.QColor("#888"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "未连接 / 无画面")
            return
        scale, (offx, offy), dw, dh = self._recompute_geometry(img)
        target = QtCore.QRectF(offx, offy, dw, dh)
        painter.drawImage(target, img)

        # 高亮叠加（带淡出透明度）
        if self._highlights:
            alpha = max(0, min(255, int(255 * self._hl_opacity)))
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 60, 60, alpha), 2))
            for (x, y, w, h), label in self._highlights:
                wx, wy = self.device_to_widget(x, y)
                painter.drawRect(QtCore.QRectF(wx, wy, w * scale, h * scale))
                if label:
                    painter.drawText(QtCore.QPointF(wx, max(10, wy - 3)), label)

        # 橡皮筋
        if self._capture_mode and self._rubber_start and self._rubber_now:
            r = QtCore.QRectF(self._rubber_start, self._rubber_now).normalized()
            painter.setPen(QtGui.QPen(QtGui.QColor(60, 160, 255), 2,
                                      Qt.PenStyle.DashLine))
            painter.fillRect(r, QtGui.QColor(60, 160, 255, 40))
            painter.drawRect(r)

    # ================= 鼠标 =================
    def mouseMoveEvent(self, ev) -> None:
        pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
        dx, dy = self.widget_to_device(pos)
        self.cursorPos.emit(dx, dy)
        if self._capture_mode:
            if self._rubber_start is not None:
                self._rubber_now = pos
                self.update()
        else:
            self.mouseMoveDev.emit(dx, dy)

    def mousePressEvent(self, ev) -> None:
        pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
        if self._capture_mode:
            if ev.button() == Qt.MouseButton.LeftButton:
                self._rubber_start = pos
                self._rubber_now = pos
            return
        btn = _BUTTON_NAME.get(ev.button())
        if btn:
            dx, dy = self.widget_to_device(pos)
            self.mousePressDev.emit(dx, dy, btn)
        self.setFocus()

    def mouseReleaseEvent(self, ev) -> None:
        pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
        if self._capture_mode:
            if self._rubber_start is not None:
                a, b = self._rubber_start, pos
                x0, y0 = self.widget_to_device(QtCore.QPoint(min(a.x(), b.x()),
                                                             min(a.y(), b.y())))
                x1, y1 = self.widget_to_device(QtCore.QPoint(max(a.x(), b.x()),
                                                             max(a.y(), b.y())))
                w, h = max(1, x1 - x0), max(1, y1 - y0)
                self._end_capture()
                if w > 2 and h > 2:
                    self.regionCaptured.emit(x0, y0, w, h)
            return
        btn = _BUTTON_NAME.get(ev.button())
        if btn:
            dx, dy = self.widget_to_device(pos)
            self.mouseReleaseDev.emit(dx, dy, btn)

    def wheelEvent(self, ev) -> None:
        if self._capture_mode:
            return
        pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
        dx, dy = self.widget_to_device(pos)
        notches = ev.angleDelta().y() // 120
        if notches:
            self.wheelDev.emit(dx, dy, int(notches))

    # ================= 键盘 =================
    def keyPressEvent(self, ev) -> None:
        if self._capture_mode:
            return
        name = _SPECIAL_KEYS.get(ev.key())
        if name:
            self.keyPressName.emit(name)
            return
        text = ev.text()
        if text and text.isprintable():
            self.typeText.emit(text)
