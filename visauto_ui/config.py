"""应用级配置的本地持久化（QSettings）。

实时保存：每次 set 立即 sync 落盘。Linux 下默认写到 ~/.config/visauto/visauto_ui.conf。
复杂结构（连接参数/设置/OCR 选择）以 JSON 串存单键，避免 QSettings 的类型强制问题；
窗口几何/布局以 QByteArray 直接存。
"""
from __future__ import annotations

import json

from .qt import QtCore


class AppConfig:
    def __init__(self):
        self._s = QtCore.QSettings("visauto", "visauto_ui")

    @property
    def path(self) -> str:
        return self._s.fileName()

    # ---- JSON 结构 ----
    def set_json(self, key: str, obj) -> None:
        self._s.setValue(key, json.dumps(obj, ensure_ascii=False))
        self._s.sync()

    def get_json(self, key: str, default=None):
        raw = self._s.value(key, None)
        if not raw:
            return {} if default is None else default
        try:
            return json.loads(raw)
        except Exception:
            return {} if default is None else default

    # ---- 原始（QByteArray 等）----
    def set_value(self, key: str, value) -> None:
        self._s.setValue(key, value)
        self._s.sync()

    def get_value(self, key: str, default=None):
        return self._s.value(key, default)
