"""后台工作线程：CaptureThread / ScriptThread / ActionWorker。

铁律：visauto 同步阻塞，所有耗时操作在这里跑；UI 更新一律经 Qt 信号回主线程。
"""
from __future__ import annotations

import io
import threading
import time
import traceback
from typing import Any, Callable, Optional

import numpy as np

from .qt import QtCore, pyqtSignal


def ndarray_to_qimage(frame: np.ndarray):
    """BGR ndarray → QImage（拷贝，脱离原缓冲）。"""
    from .qt import QtGui
    if frame is None or frame.size == 0:
        return QtGui.QImage()
    h, w = frame.shape[:2]
    rgb = np.ascontiguousarray(frame[:, :, ::-1])  # BGR → RGB
    img = QtGui.QImage(rgb.data, w, h, 3 * w, QtGui.QImage.Format.Format_RGB888)
    return img.copy()


class CaptureThread(QtCore.QThread):
    """循环 device.capture() 出帧。"""

    frameReady = pyqtSignal(object)   # np.ndarray(BGR)
    error = pyqtSignal(str)
    disconnected = pyqtSignal(str)    # 连接被对端断开（致命）

    def __init__(self, device, fps: float = 10.0, parent=None):
        super().__init__(parent)
        self._device = device
        self._fps = max(1.0, fps)
        self._running = True

    def set_fps(self, fps: float) -> None:
        self._fps = max(1.0, fps)

    def run(self) -> None:
        while self._running:
            t0 = time.monotonic()
            try:
                frame = self._device.capture()
                self.frameReady.emit(frame)
            except Exception as e:
                # 后端报告连接已断开 → 致命，发信号并停线程，不再刷错误
                is_alive = getattr(self._device.backend, "is_alive", None)
                if is_alive is not None and not is_alive():
                    self.disconnected.emit(str(e))
                    return
                self.error.emit(f"capture 失败：{e}")
                time.sleep(0.5)
            dt = time.monotonic() - t0
            wait = max(0.0, 1.0 / self._fps - dt)
            if wait:
                time.sleep(wait)

    def stop(self) -> None:
        self._running = False
        self.wait(2000)


class ActionWorker(QtCore.QThread):
    """跑一个一次性可调用对象（连接/断开/单次 find/OCR 等），结果经信号返回。"""

    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn: Callable[[], Any], parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            result = self._fn()
            self.finished_ok.emit(result)
        except Exception as e:
            self.failed.emit(f"{e}\n{traceback.format_exc()}")


class _ConsoleRedirect(io.TextIOBase):
    """把脚本 print 的文本经回调投出去。"""

    def __init__(self, emit: Callable[[str], None]):
        self._emit = emit

    def write(self, s: str) -> int:
        if s:
            self._emit(s)
        return len(s)

    def flush(self) -> None:  # noqa: D401
        pass


class ScriptThread(QtCore.QThread):
    """在独立线程 exec 用户脚本；注入 dev/ocr 等；支持协作式中止。"""

    output = pyqtSignal(str)      # stdout/stderr 文本
    finished_run = pyqtSignal(bool, str)  # (success, message)

    def __init__(self, code: str, namespace: dict, abort_event: threading.Event,
                 parent=None):
        super().__init__(parent)
        self._code = code
        self._namespace = namespace
        self._abort_event = abort_event

    def run(self) -> None:
        import sys

        import visauto

        visauto.set_abort_event(self._abort_event)
        redirect = _ConsoleRedirect(self.output.emit)
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = redirect
        ns = dict(self._namespace)
        ns.setdefault("__name__", "__visauto_script__")
        try:
            compiled = compile(self._code, "<script>", "exec")
            exec(compiled, ns)
            self.finished_run.emit(True, "脚本执行完成")
        except visauto.ScriptAborted:
            self.finished_run.emit(False, "脚本已中止")
        except Exception as e:
            self.output.emit(traceback.format_exc())
            self.finished_run.emit(False, f"脚本出错：{e}")
        finally:
            sys.stdout, sys.stderr = old_out, old_err
            visauto.clear_abort_event()
