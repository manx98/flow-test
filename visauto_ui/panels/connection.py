"""连接面板：选后端 + 动态字段 + 连接/断开。"""
from __future__ import annotations

from ..qt import QtWidgets, pyqtSignal


class ConnectionPanel(QtWidgets.QWidget):
    # 发出一个零参可调用对象，调用后返回已连接的 Device（在后台线程执行）。
    connectRequested = pyqtSignal(object)
    disconnectRequested = pyqtSignal()
    changed = pyqtSignal()   # 任一字段变化（用于实时保存）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._build()
        self._connect_change_signals()

    def _all_fields(self):
        """所有连接配置输入控件（连接中/已连接时整体禁用）。"""
        return [
            self.backend, self.local_monitor, self.vnc_url, self.vnc_pwd,
            self.rdp_host, self.rdp_port, self.rdp_user, self.rdp_pwd,
            self.rdp_domain, self.rdp_auth, self.rdp_w, self.rdp_h,
        ]

    def _connect_change_signals(self) -> None:
        def emit():
            if not self._loading:
                self.changed.emit()
        self.backend.currentIndexChanged.connect(emit)
        self.local_monitor.valueChanged.connect(emit)
        for le in (self.vnc_url, self.vnc_pwd, self.rdp_host, self.rdp_user,
                   self.rdp_pwd, self.rdp_domain):
            le.textChanged.connect(emit)
        for sp in (self.rdp_port, self.rdp_w, self.rdp_h):
            sp.valueChanged.connect(emit)
        self.rdp_auth.currentIndexChanged.connect(emit)
        self.auto_reconnect.toggled.connect(emit)

    def _build(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        self.backend = QtWidgets.QComboBox()
        self.backend.addItems(["Local", "noVNC", "RDP"])
        self.backend.currentIndexChanged.connect(self._on_backend_changed)
        form_top = QtWidgets.QFormLayout()
        form_top.addRow("后端", self.backend)
        layout.addLayout(form_top)

        self.stack = QtWidgets.QStackedWidget()
        self.stack.addWidget(self._build_local())
        self.stack.addWidget(self._build_novnc())
        self.stack.addWidget(self._build_rdp())
        layout.addWidget(self.stack)

        btns = QtWidgets.QHBoxLayout()
        self.connect_btn = QtWidgets.QPushButton("连接")
        self.disconnect_btn = QtWidgets.QPushButton("断开")
        self.disconnect_btn.setEnabled(False)
        self.connect_btn.clicked.connect(self._on_connect)
        self.disconnect_btn.clicked.connect(self.disconnectRequested)
        btns.addWidget(self.connect_btn)
        btns.addWidget(self.disconnect_btn)
        layout.addLayout(btns)

        self.auto_reconnect = QtWidgets.QCheckBox("断线自动重连")
        layout.addWidget(self.auto_reconnect)

        self.status = QtWidgets.QLabel("未连接")
        layout.addWidget(self.status)
        layout.addStretch(1)

    # ---- 各后端字段 ----
    def _build_local(self):
        w = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(w)
        self.local_monitor = QtWidgets.QSpinBox()
        self.local_monitor.setRange(0, 8)
        self.local_monitor.setValue(1)
        f.addRow("显示器", self.local_monitor)
        return w

    def _build_novnc(self):
        w = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(w)
        self.vnc_url = QtWidgets.QLineEdit("ws://127.0.0.1:6080/websockify")
        self.vnc_pwd = QtWidgets.QLineEdit()
        self.vnc_pwd.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        f.addRow("URL", self.vnc_url)
        f.addRow("密码", self.vnc_pwd)
        return w

    def _build_rdp(self):
        w = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(w)
        self.rdp_host = QtWidgets.QLineEdit("127.0.0.1")
        self.rdp_port = QtWidgets.QSpinBox()
        self.rdp_port.setRange(1, 65535)
        self.rdp_port.setValue(3389)
        self.rdp_user = QtWidgets.QLineEdit()
        self.rdp_pwd = QtWidgets.QLineEdit()
        self.rdp_pwd.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.rdp_domain = QtWidgets.QLineEdit()
        self.rdp_auth = QtWidgets.QComboBox()
        self.rdp_auth.addItems(["auto", "tls", "nla"])
        self.rdp_w = QtWidgets.QSpinBox()
        self.rdp_w.setRange(320, 7680)
        self.rdp_w.setValue(1280)
        self.rdp_h = QtWidgets.QSpinBox()
        self.rdp_h.setRange(240, 4320)
        self.rdp_h.setValue(800)
        f.addRow("主机", self.rdp_host)
        f.addRow("端口", self.rdp_port)
        f.addRow("用户名", self.rdp_user)
        f.addRow("密码", self.rdp_pwd)
        f.addRow("域", self.rdp_domain)
        f.addRow("认证", self.rdp_auth)
        f.addRow("宽", self.rdp_w)
        f.addRow("高", self.rdp_h)
        return w

    def _on_backend_changed(self, idx: int) -> None:
        self.stack.setCurrentIndex(idx)

    # ---- 连接 ----
    def _make_connector(self):
        import visauto
        kind = self.backend.currentText()
        if kind == "Local":
            mon = self.local_monitor.value()
            return lambda: visauto.connect_local(monitor=mon)
        if kind == "noVNC":
            url = self.vnc_url.text().strip()
            pwd = self.vnc_pwd.text() or None
            return lambda: visauto.connect_novnc(url, password=pwd)
        host = self.rdp_host.text().strip()
        params = dict(
            password=self.rdp_pwd.text() or None,
            username=self.rdp_user.text() or None,
            domain=self.rdp_domain.text() or None,
            auth=self.rdp_auth.currentText(),
            port=self.rdp_port.value(),
            width=self.rdp_w.value(),
            height=self.rdp_h.value(),
        )
        return lambda: visauto.connect_rdp(host, **params)

    def _on_connect(self) -> None:
        self.connectRequested.emit(self._make_connector())

    # ---- 状态联动 ----
    def _set_fields_enabled(self, enabled: bool) -> None:
        for w in self._all_fields():
            w.setEnabled(enabled)

    def set_connecting(self) -> None:
        """发起连接后、结果返回前：禁止重复点击与修改配置。"""
        self.connect_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(False)
        self._set_fields_enabled(False)
        self.status.setText("连接中…")

    def set_connected(self, connected: bool, text: str = "") -> None:
        self.connect_btn.setEnabled(not connected)
        self.disconnect_btn.setEnabled(connected)
        self._set_fields_enabled(not connected)   # 已连接时禁用全部配置字段
        self.status.setText(text or ("已连接" if connected else "未连接"))

    # ---- 工程元数据存取 ----
    def to_meta(self) -> dict:
        return {
            "backend": self.backend.currentText(),
            "local_monitor": self.local_monitor.value(),
            "novnc_url": self.vnc_url.text(),
            "novnc_pwd": self.vnc_pwd.text(),       # 注意：明文保存
            "rdp_host": self.rdp_host.text(),
            "rdp_port": self.rdp_port.value(),
            "rdp_user": self.rdp_user.text(),
            "rdp_pwd": self.rdp_pwd.text(),          # 注意：明文保存
            "rdp_domain": self.rdp_domain.text(),
            "rdp_auth": self.rdp_auth.currentText(),
            "rdp_w": self.rdp_w.value(),
            "rdp_h": self.rdp_h.value(),
            "auto_reconnect": self.auto_reconnect.isChecked(),
        }

    def from_meta(self, m: dict) -> None:
        if not m:
            return
        self._loading = True
        try:
            self._apply_meta(m)
        finally:
            self._loading = False

    def _apply_meta(self, m: dict) -> None:
        idx = max(0, self.backend.findText(m.get("backend", "Local")))
        self.backend.setCurrentIndex(idx)
        self.local_monitor.setValue(int(m.get("local_monitor", self.local_monitor.value())))
        self.vnc_url.setText(m.get("novnc_url", self.vnc_url.text()))
        self.vnc_pwd.setText(m.get("novnc_pwd", ""))
        self.rdp_host.setText(m.get("rdp_host", self.rdp_host.text()))
        self.rdp_port.setValue(int(m.get("rdp_port", self.rdp_port.value())))
        self.rdp_user.setText(m.get("rdp_user", ""))
        self.rdp_pwd.setText(m.get("rdp_pwd", ""))
        self.rdp_domain.setText(m.get("rdp_domain", ""))
        self.rdp_auth.setCurrentText(m.get("rdp_auth", "auto"))
        self.rdp_w.setValue(int(m.get("rdp_w", self.rdp_w.value())))
        self.rdp_h.setValue(int(m.get("rdp_h", self.rdp_h.value())))
        self.auto_reconnect.setChecked(bool(m.get("auto_reconnect", False)))
