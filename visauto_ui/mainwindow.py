"""MainWindow：组装 dock/工具栏/菜单，管理 Device 生命周期与各线程，串联所有面板。"""
from __future__ import annotations

import os
import threading

import cv2

from .config import AppConfig
from .dialogs.ocr_settings import OcrSettingsDialog
from .dialogs.settings import SettingsDialog
from .panels.connection import ConnectionPanel
from .panels.console import ConsolePanel
from .panels.editor import ScriptEditor
from .panels.findtest import FindTestPanel
from .panels.imagelibrary import ImageLibraryPanel
from .panels.patterndialog import PatternDialog
from .panels.projecttree import ProjectTreePanel
from .project import Project
from .qt import Qt, QtCore, QtWidgets, exec_dialog
from .screenview import ScreenView
from .workers import ActionWorker, CaptureThread, ScriptThread, ndarray_to_qimage


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("visauto client")
        self.resize(1280, 800)

        self.device = None
        self.capture_thread = None
        self.script_thread = None
        self.abort_event = None
        self._last_connector = None
        self.project = None
        self._fps = 10.0
        self._hl_auto_clear = 3.0   # 标记自动淡出秒数（0=不自动）
        self._workers = []   # 持有 ActionWorker 防 GC
        self.config = AppConfig()
        self._ocr_cfg = {}

        self._build_central()
        self._build_docks()
        self._build_toolbar()
        self._build_menu()
        self._build_status()
        self._wire()
        self._restore_config()

    # ================= 构建 =================
    def _build_central(self):
        self.screen = ScreenView()
        self.setCentralWidget(self.screen)

    def _build_docks(self):
        DA = Qt.DockWidgetArea
        # 左：连接 + 工程文件树 + 图片库
        self.conn_panel = ConnectionPanel()
        self.tree_panel = ProjectTreePanel()
        self.lib_panel = ImageLibraryPanel()
        self._add_dock("连接", self.conn_panel, DA.LeftDockWidgetArea)
        self._add_dock("工程文件", self.tree_panel, DA.LeftDockWidgetArea)
        self._add_dock("图片库", self.lib_panel, DA.LeftDockWidgetArea)
        # 右：脚本编辑 + Find/OCR 测试
        self.editor = ScriptEditor()
        self.find_panel = FindTestPanel()
        self._add_dock("脚本编辑器", self.editor, DA.RightDockWidgetArea)
        self._add_dock("Find/OCR 测试", self.find_panel, DA.RightDockWidgetArea)
        # 底：控制台
        self.console = ConsolePanel()
        self._add_dock("控制台", self.console, DA.BottomDockWidgetArea)

    def _add_dock(self, title, widget, area):
        dock = QtWidgets.QDockWidget(title, self)
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        if not hasattr(self, "_docks"):
            self._docks = {}
        self._docks[title] = dock
        return dock

    def _build_toolbar(self):
        tb = self.addToolBar("main")
        self.act_capture = tb.addAction("Capture▣", self._on_capture)
        tb.addSeparator()
        self.act_run = tb.addAction("Run▶", self._on_run)
        self.act_stop = tb.addAction("Stop■", self._on_stop)
        self.act_stop.setEnabled(False)
        tb.addSeparator()
        tb.addAction("Find", lambda: self.find_panel._run("find"))
        tb.addAction("FindAll", lambda: self.find_panel._run("find_all"))
        tb.addAction("OCR", lambda: self.find_panel._run("read_text"))
        tb.addAction("清除标记", self._clear_marks)
        tb.addSeparator()
        self.zoom = QtWidgets.QComboBox()
        self.zoom.addItems(["适应窗口", "100%", "50%", "200%"])
        self.zoom.currentTextChanged.connect(self._on_zoom)
        tb.addWidget(self.zoom)

    def _build_menu(self):
        mb = self.menuBar()
        m_file = mb.addMenu("文件")
        m_file.addAction("新建工程", self._new_project)
        m_file.addAction("打开工程", self._open_project)
        m_file.addAction("保存工程", self._save_project)
        m_view = mb.addMenu("视图")
        for title, dock in self._docks.items():
            m_view.addAction(dock.toggleViewAction())
        m_run = mb.addMenu("运行")
        m_run.addAction("运行脚本", self._on_run)
        m_run.addAction("停止", self._on_stop)
        m_set = mb.addMenu("设置")
        m_set.addAction("OCR 设置", self._open_ocr_settings)
        m_set.addAction("参数设置", self._open_settings)

    def _build_status(self):
        self.sb_conn = QtWidgets.QLabel("未连接")
        self.sb_cursor = QtWidgets.QLabel("—")
        self.sb_info = QtWidgets.QLabel("")
        for w in (self.sb_conn, self.sb_cursor, self.sb_info):
            self.statusBar().addWidget(w)

    # ================= 接线 =================
    def _wire(self):
        self.conn_panel.connectRequested.connect(self._do_connect)
        self.conn_panel.disconnectRequested.connect(self._do_disconnect)
        self.conn_panel.changed.connect(self._save_connection)   # 实时保存连接配置

        sv = self.screen
        sv.mouseMoveDev.connect(lambda x, y: self._fwd("move", x, y))
        sv.mousePressDev.connect(lambda x, y, b: self._fwd("press", x, y, b))
        sv.mouseReleaseDev.connect(lambda x, y, b: self._fwd("release", x, y, b))
        sv.wheelDev.connect(lambda x, y, n: self._fwd("wheel", x, y, None, n))
        sv.typeText.connect(self._fwd_type)
        sv.keyPressName.connect(self._fwd_key)
        sv.regionCaptured.connect(self._on_region_captured)
        sv.cursorPos.connect(lambda x, y: self.sb_cursor.setText(f"光标 {x},{y}"))

        self.lib_panel.insertCode.connect(
            lambda name: self.editor.insert_at_cursor(f'dev.click("{name}")\n'))
        self.lib_panel.useInTest.connect(self.find_panel.set_target)
        self.lib_panel.openPattern.connect(self._open_pattern)

        self.tree_panel.openScript.connect(self._load_script_file)
        self.tree_panel.insertImage.connect(
            lambda name: self.editor.insert_at_cursor(f'dev.click("{name}")\n'))
        self.tree_panel.useInTest.connect(self.find_panel.set_target)
        self.tree_panel.openPattern.connect(self._open_pattern)

        self.find_panel.runRequested.connect(self._run_find_test)
        self.find_panel.insertCode.connect(self.editor.insert_at_cursor)
        self.find_panel.clearRequested.connect(self._clear_marks)

    # ================= 配置持久化（实时本地保存）=================
    def _restore_config(self):
        self.conn_panel.from_meta(self.config.get_json("connection"))
        self._apply_saved_settings(self.config.get_json("settings"))
        self._ocr_cfg = self.config.get_json("ocr")
        geo = self.config.get_value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        state = self.config.get_value("winstate")
        if state is not None:
            self.restoreState(state)

    def _save_connection(self):
        self.config.set_json("connection", self.conn_panel.to_meta())

    def _apply_saved_settings(self, d):
        if not d:
            return
        from visauto import Settings
        for k in ("min_similarity", "auto_wait_timeout", "wait_scan_rate",
                  "observe_scan_rate", "move_delay"):
            if k in d:
                setattr(Settings, k, float(d[k]))
        if "highlight" in d:
            Settings.highlight = bool(d["highlight"])
        if "fps" in d:
            self._fps = float(d["fps"])
        if "hl_auto_clear" in d:
            self._hl_auto_clear = float(d["hl_auto_clear"])
        self.screen.set_auto_clear(self._hl_auto_clear)

    def _save_settings(self):
        from visauto import Settings
        self.config.set_json("settings", {
            "min_similarity": Settings.min_similarity,
            "auto_wait_timeout": Settings.auto_wait_timeout,
            "wait_scan_rate": Settings.wait_scan_rate,
            "observe_scan_rate": Settings.observe_scan_rate,
            "move_delay": Settings.move_delay,
            "highlight": Settings.highlight,
            "fps": self._fps,
            "hl_auto_clear": self._hl_auto_clear,
        })

    # ================= 连接 =================
    def _do_connect(self, connector):
        self._last_connector = connector   # 供断线自动重连复用
        self.conn_panel.set_connecting()   # 立刻禁用按钮与配置字段，防重复点击/改配置
        self.sb_conn.setText("连接中…")
        worker = ActionWorker(connector)
        worker.finished_ok.connect(self._on_connected)
        worker.failed.connect(self._on_connect_failed)
        self._workers.append(worker)
        worker.start()

    def _on_connected(self, device):
        self.device = device
        w, h = device.backend.screen_size
        self.conn_panel.set_connected(True, f"已连接 {w}x{h}")
        self.sb_conn.setText(f"●已连接 {w}x{h}")
        self.capture_thread = CaptureThread(device, fps=self._fps)
        self.capture_thread.frameReady.connect(self._on_frame)
        self.capture_thread.error.connect(lambda m: self.console.append(m, "ERR"))
        self.capture_thread.disconnected.connect(self._on_backend_disconnected)
        self.capture_thread.start()
        self.console.append("已连接，开始拉流", "OK")

    def _on_backend_disconnected(self, msg):
        """后端被对端断开（如 RDP 被服务器 reset）。"""
        self.console.append(f"连接已断开：{msg}", "ERR")
        self._do_disconnect()
        if self.conn_panel.auto_reconnect.isChecked() and self._last_connector:
            self.sb_conn.setText("连接已断开，2 秒后自动重连…")
            self.console.append("断线自动重连中…", "RUN")
            QtCore.QTimer.singleShot(2000, lambda: self._do_connect(self._last_connector))

    def _on_connect_failed(self, msg):
        self.conn_panel.set_connected(False, "连接失败")
        self.sb_conn.setText("连接失败")
        self.console.append(msg, "ERR")
        QtWidgets.QMessageBox.warning(self, "连接失败", msg.splitlines()[0])

    def _do_disconnect(self):
        if self.capture_thread:
            self.capture_thread.stop()
            self.capture_thread = None
        if self.device:
            try:
                self.device.close()
            except Exception as e:
                self.console.append(f"断开异常：{e}", "ERR")
        self.device = None
        self.conn_panel.set_connected(False)
        self.sb_conn.setText("未连接")
        self.screen.clear()

    def _on_frame(self, frame):
        if self.device is None:      # 忽略断开后仍在队列里的迟到帧
            return
        self.screen.set_frame(ndarray_to_qimage(frame))

    # ================= 输入转发 =================
    def _fwd(self, kind, x, y, button=None, notches=0):
        if not self.device:
            return
        from visauto.backends.base import Button
        bmap = {"left": Button.LEFT, "right": Button.RIGHT, "middle": Button.MIDDLE}
        be = self.device.backend
        try:
            if kind == "move":
                be.mouse_move(x, y)
            elif kind == "press":
                be.mouse_move(x, y)
                be.mouse_press(bmap.get(button, Button.LEFT))
            elif kind == "release":
                be.mouse_release(bmap.get(button, Button.LEFT))
            elif kind == "wheel":
                be.mouse_move(x, y)
                be.mouse_scroll(0, notches)
        except Exception as e:
            self.console.append(f"输入转发失败：{e}", "ERR")

    def _fwd_type(self, text):
        if self.device:
            try:
                self.device.backend.type_text(text)
            except Exception as e:
                self.console.append(f"输入失败：{e}", "ERR")

    def _fwd_key(self, name):
        if self.device:
            try:
                self.device.backend.key_press(name)
                self.device.backend.key_release(name)
            except Exception as e:
                self.console.append(f"按键失败：{e}", "ERR")

    # ================= Capture =================
    def _on_capture(self):
        if not self.device:
            QtWidgets.QMessageBox.information(self, "提示", "请先连接")
            return
        self.screen.begin_capture()

    def _on_region_captured(self, x, y, w, h):
        if not self.device:
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "保存模板", "文件名：", text="img.png")
        if not ok or not name.strip():
            return
        if not name.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
            name += ".png"
        if self.project is None:
            QtWidgets.QMessageBox.information(self, "提示", "请先新建/打开工程以保存图片")
            return
        from visauto.geometry import Rect

        def grab():
            frame = self.device.capture(Rect(x, y, w, h))
            path = self.project.image_path(name)
            cv2.imwrite(path, frame)
            return path

        worker = ActionWorker(grab)
        worker.finished_ok.connect(lambda p: (self.lib_panel.refresh(),
                                              self.console.append(f"已保存模板 {p}", "OK")))
        worker.failed.connect(lambda m: self.console.append(m, "ERR"))
        self._workers.append(worker)
        worker.start()

    # ================= 脚本运行 =================
    def _script_namespace(self):
        import visauto
        ns = {
            "dev": self.device,
            "visauto": visauto,
            "Pattern": visauto.Pattern,
            "Region": visauto.Region,
            "Match": visauto.Match,
            "Location": visauto.Location,
            "Key": visauto.Key,
            "Settings": visauto.Settings,
            "FindFailed": visauto.FindFailed,
            "ocr": visauto.get_default_ocr(),
        }
        return ns

    def _on_run(self):
        if self.script_thread and self.script_thread.isRunning():
            return
        if not self.device:
            QtWidgets.QMessageBox.information(self, "提示", "请先连接再运行脚本")
            return
        self.abort_event = threading.Event()
        code = self.editor.text()
        self.script_thread = ScriptThread(code, self._script_namespace(), self.abort_event)
        self.script_thread.output.connect(self.console.append_raw)
        self.script_thread.finished_run.connect(self._on_script_done)
        self.act_run.setEnabled(False)
        self.act_stop.setEnabled(True)
        self.console.append("脚本开始", "RUN")
        self.script_thread.start()

    def _on_stop(self):
        if self.abort_event:
            self.abort_event.set()
            self.console.append("已请求中止…", "RUN")

    def _on_script_done(self, ok, msg):
        self.act_run.setEnabled(True)
        self.act_stop.setEnabled(False)
        self.console.append(msg, "OK" if ok else "ERR")

    # ================= Find/OCR 测试 =================
    def _run_find_test(self, spec):
        if not self.device:
            QtWidgets.QMessageBox.information(self, "提示", "请先连接")
            return
        dev = self.device

        def task():
            import visauto
            op = spec["op"]
            if op == "read_text":
                return ("text", dev.read_text(ocr=visauto.get_default_ocr()))
            if spec["is_image"]:
                pat = visauto.Pattern(spec["target"], similarity=spec["similarity"])
                target_kw = {}
                arg = pat
            else:
                arg = None
                target_kw = {"text": spec["target"], "regex": spec["regex"]}
            if op == "find_all":
                matches = dev.find_all(arg, timeout=0, **target_kw)
            else:  # find / exists 都用 exists(timeout=0) 取单个，不阻塞
                m = dev.exists(arg, timeout=0, **target_kw)
                matches = [m] if m else []
            return ("matches", matches)

        worker = ActionWorker(task)
        worker.finished_ok.connect(self._on_find_result)
        worker.failed.connect(lambda m: self.console.append(m, "ERR"))
        self._workers.append(worker)
        worker.start()

    def _on_find_result(self, result):
        kind, data = result
        if kind == "text":
            self.find_panel.set_results([data or "(空)"])
            self.screen.clear_highlights()
            return
        matches = data
        highlights = []
        lines = []
        for m in matches:
            label = (f"{m.score:.2f}" if getattr(m, "score", None) is not None else "")
            if getattr(m, "ocr_text", None):
                label = f"{m.ocr_text} {label}"
            highlights.append(((m.x, m.y, m.w, m.h), label))
            lines.append(f"({m.x},{m.y}) {m.w}x{m.h} {label}")
        self.screen.set_highlights(highlights)
        self.find_panel.set_results(lines or ["未命中"])
        self.sb_info.setText(f"命中 {len(matches)}")

    def _load_script_file(self, path):
        """从工程文件树双击 .py → 载入编辑器（覆盖当前内容前确认）。"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            self.console.append(f"打开失败：{e}", "ERR")
            return
        if self.editor.text().strip():
            btn = QtWidgets.QMessageBox.question(
                self, "打开脚本", f"用 {path} 覆盖当前编辑器内容？")
            yes = getattr(QtWidgets.QMessageBox.StandardButton, "Yes", None) \
                or QtWidgets.QMessageBox.Yes
            if btn != yes:
                return
        self.editor.set_text(text)
        self.console.append(f"已载入 {path}", "OK")

    def _clear_marks(self):
        """清除画面上的 find/OCR 高亮框与结果列表。"""
        self.screen.clear_highlights()
        self.find_panel.set_results([])
        self.sb_info.setText("")

    # ================= 对话框 =================
    def _open_pattern(self, name):
        if self.project is None:
            return
        path = self.project.image_path(name)
        dlg = PatternDialog(path, self)
        if exec_dialog(dlg):
            self.editor.insert_at_cursor(f"dev.click({dlg.code_snippet()})\n")

    def _open_ocr_settings(self):
        dlg = OcrSettingsDialog(self, initial=self._ocr_cfg)
        if exec_dialog(dlg):
            self._ocr_cfg = dlg.config()
            self.config.set_json("ocr", self._ocr_cfg)   # 实时保存
            self.console.append("OCR 引擎已设为会话默认（配置已保存）", "OK")

    def _open_settings(self):
        dlg = SettingsDialog(self._fps, self._hl_auto_clear, self)
        if exec_dialog(dlg):
            self._fps = dlg.fps_value()
            if self.capture_thread:
                self.capture_thread.set_fps(self._fps)
            self._hl_auto_clear = dlg.auto_clear_value()
            self.screen.set_auto_clear(self._hl_auto_clear)
            self._save_settings()   # 实时保存

    def _on_zoom(self, text):
        self.screen.set_zoom("fit" if text == "适应窗口" else float(text.rstrip("%")) / 100)

    # ================= 工程 =================
    def _use_project(self, path, new):
        import visauto
        self.project = Project(path)
        self.project.ensure()
        visauto.ImagePath.add(self.project.images_dir)
        self.lib_panel.set_dir(self.project.images_dir)
        self.tree_panel.set_root(self.project.path)
        if new:
            self.project.save_script(self.editor.text())
        else:
            self.editor.set_text(self.project.load_script() or self.editor.text())
            self.conn_panel.from_meta(self.project.load_meta())
            meta = self.project.load_meta()
            self._fps = float(meta.get("fps", self._fps))
        self.setWindowTitle(f"visauto client — {os.path.basename(path)}")
        self.console.append(f"工程：{path}", "OK")

    def _new_project(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "选择新建工程目录")
        if path:
            self._use_project(path, new=True)

    def _open_project(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "打开工程目录")
        if path:
            self._use_project(path, new=False)

    def _save_project(self):
        if self.project is None:
            self._new_project()
            if self.project is None:
                return
        self.project.save_script(self.editor.text())
        meta = self.conn_panel.to_meta()
        meta["fps"] = self._fps
        self.project.save_meta(meta)
        self.console.append("工程已保存", "OK")

    # ================= 关闭 =================
    def closeEvent(self, ev):
        # 保存窗口几何与 dock 布局
        self.config.set_value("geometry", self.saveGeometry())
        self.config.set_value("winstate", self.saveState())
        if self.script_thread and self.script_thread.isRunning() and self.abort_event:
            self.abort_event.set()
            self.script_thread.wait(2000)
        if self.capture_thread:
            self.capture_thread.stop()
        if self.device:
            try:
                self.device.close()
            except Exception:
                pass
        super().closeEvent(ev)
