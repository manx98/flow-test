"""设置对话框：映射到 visauto.Settings + 画面刷新 fps。"""
from __future__ import annotations

from ..qt import QtWidgets


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, current_fps: float, current_auto_clear: float = 3.0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        from visauto import Settings

        layout = QtWidgets.QFormLayout(self)

        def dspin(lo, hi, step, val):
            s = QtWidgets.QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setSingleStep(step)
            s.setValue(val)
            return s

        self.fps = dspin(1, 60, 1, current_fps)
        self.auto_clear = dspin(0, 60, 0.5, current_auto_clear)
        self.min_sim = dspin(0.1, 1.0, 0.05, Settings.min_similarity)
        self.auto_wait = dspin(0, 120, 0.5, Settings.auto_wait_timeout)
        self.wait_rate = dspin(0.5, 30, 0.5, Settings.wait_scan_rate)
        self.obs_rate = dspin(0.5, 30, 0.5, Settings.observe_scan_rate)
        self.move_delay = dspin(0, 2, 0.05, Settings.move_delay)
        self.highlight = QtWidgets.QCheckBox()
        self.highlight.setChecked(Settings.highlight)

        layout.addRow("画面刷新 fps", self.fps)
        layout.addRow("标记自动淡出(秒,0=不)", self.auto_clear)
        layout.addRow("min_similarity", self.min_sim)
        layout.addRow("auto_wait_timeout", self.auto_wait)
        layout.addRow("wait_scan_rate", self.wait_rate)
        layout.addRow("observe_scan_rate", self.obs_rate)
        layout.addRow("move_delay", self.move_delay)
        layout.addRow("highlight 命中", self.highlight)

        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._apply)
        box.rejected.connect(self.reject)
        layout.addRow(box)

    def _apply(self) -> None:
        from visauto import Settings
        Settings.min_similarity = self.min_sim.value()
        Settings.auto_wait_timeout = self.auto_wait.value()
        Settings.wait_scan_rate = self.wait_rate.value()
        Settings.observe_scan_rate = self.obs_rate.value()
        Settings.move_delay = self.move_delay.value()
        Settings.highlight = self.highlight.isChecked()
        self.accept()

    def fps_value(self) -> float:
        return self.fps.value()

    def auto_clear_value(self) -> float:
        return self.auto_clear.value()
