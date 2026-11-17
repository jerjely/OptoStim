"""OptoStim main window (PySide6)."""
from __future__ import annotations

import os
import platform
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PySide6 import QtCore
from PySide6.QtCore import QPointF, QRectF, QSettings, Qt, QTimer
from PySide6.QtGui import (QAction, QColor, QIcon, QKeySequence, QPainter, QPalette,
                           QPen, QPixmap, QShortcut)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
                               QLabel, QMainWindow, QMessageBox, QProgressBar, QPushButton,
                               QSizePolicy, QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from . import APP_AUTHOR, APP_NAME, APP_URL, __version__
from .app import resource_path
from .core import (SIM_PORT, LogEntry, Protocol, ProtocolRun, list_serial_ports,
                   make_device, now_iso, timing_summary, write_log_csv)

APP_ID = "io.github.jerjely.OptoStim"
MAX_TABLE_ROWS = 2000
BAUD_RATES = ["9600", "19200", "38400", "57600", "115200"]
LOG_HINT = "Timestamps are when each command was sent to the port."

STYLE = """
QMainWindow, QDialog { background: #f2f4fa; }
QGroupBox { background: #ffffff; border: 1px solid #d6dbe8; border-radius: 8px;
            margin-top: 14px; padding: 12px 10px 8px 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #101d3d;
                   font-weight: bold; }
QPushButton { background: #ffffff; border: 1px solid #c4cbe0; border-radius: 6px;
              padding: 6px 14px; }
QPushButton:hover { background: #eef1fb; }
QPushButton:disabled { color: #9aa3bd; background: #f3f5fa; border-color: #dfe3ee; }
QPushButton#primary { background: #2f46d9; border-color: #2f46d9; color: #ffffff; font-weight: bold; }
QPushButton#primary:hover { background: #2639b8; }
QPushButton#primary:disabled { background: #aab3ec; border-color: #aab3ec; color: #ffffff; }
QPushButton#danger { background: #d6334a; border-color: #d6334a; color: #ffffff; font-weight: bold; }
QPushButton#danger:hover { background: #b82a3e; }
QPushButton#danger:disabled { background: #eab5bd; border-color: #eab5bd; color: #ffffff; }
QPushButton#laserOn { background: #6c4cff; border-color: #6c4cff; color: #ffffff; font-weight: bold;
                      padding: 10px 14px; }
QPushButton#laserOn:hover { background: #5a3be6; }
QPushButton#laserOn:disabled { background: #cfc5ff; border-color: #cfc5ff; color: #ffffff; }
QPushButton#laserOff { padding: 10px 14px; font-weight: bold; }
QTableWidget { background: #ffffff; alternate-background-color: #f6f8fd; border: 1px solid #d6dbe8;
               gridline-color: #e6e9f3; border-radius: 6px; }
QHeaderView::section { background: #eef1fb; color: #101d3d; border: none; border-bottom: 1px solid #d6dbe8;
                       padding: 4px 6px; font-weight: bold; }
QProgressBar { border: 1px solid #c4cbe0; border-radius: 6px; background: #ffffff; text-align: center;
               min-height: 20px; }
QProgressBar::chunk { background: #6c4cff; border-radius: 5px; }
QStatusBar { color: #5a6482; }
"""


def fmt_time(s: float) -> str:
    """Compact time label: '2.5 s', '45 s', '1:05', '1:02:03'."""
    if s < 60:
        txt = f"{s:.2f}".rstrip("0").rstrip(".")
        return f"{txt or '0'} s"
    total = int(round(s))
    m, sec = divmod(total, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def app_icon() -> QIcon:
    icon = QIcon()
    for name in ("icon_256.png", "icon_512.png"):
        path = resource_path(name)
        if path.exists():
            icon.addFile(str(path))
    return icon


def apply_style(app: QApplication) -> None:
    """Same light look on every OS (ignores the system dark mode)."""
    app.setStyle("Fusion")
    pal = QPalette()
    R = QPalette.ColorRole
    G = QPalette.ColorGroup
    ink, paper = QColor("#1b2440"), QColor("#ffffff")
    for role, colour in [(R.Window, "#f2f4fa"), (R.WindowText, ink), (R.Base, paper),
                         (R.AlternateBase, "#f6f8fd"), (R.Text, ink), (R.Button, paper),
                         (R.ButtonText, ink), (R.ToolTipBase, "#ffffe8"), (R.ToolTipText, ink),
                         (R.Highlight, "#2f46d9"), (R.HighlightedText, "#ffffff"),
                         (R.PlaceholderText, "#8a93ad")]:
        pal.setColor(role, QColor(colour))
    for role in (R.WindowText, R.Text, R.ButtonText):
        pal.setColor(G.Disabled, role, QColor("#9aa3bd"))
    app.setPalette(pal)
    app.setStyleSheet(STYLE)


# --------------------------------------------------------------------------
class TimelineWidget(QWidget):
    """Picture of the planned ON periods, with a moving cursor while running."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(92)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._intervals: list = []
        self._total: Optional[float] = None
        self._message = ""
        self._cursor: Optional[float] = None
        self._base: Optional[QPixmap] = None

    def set_plan(self, intervals: list, total: Optional[float], message: str = "") -> None:
        self._intervals, self._total, self._message = intervals, total, message
        self._base = None
        self.update()

    def set_cursor(self, t: Optional[float]) -> None:
        if t != self._cursor:
            self._cursor = t
            self.update()

    def resizeEvent(self, event):
        self._base = None
        super().resizeEvent(event)

    def _plot_rect(self) -> QRectF:
        return QRectF(14, 10, max(10, self.width() - 28), max(10, self.height() - 36))

    def _span(self) -> float:
        if self._total:
            return self._total
        starts = [a for a, _ in self._intervals]
        return (max(starts) if starts else 0.0) + 10.0

    def _render_base(self) -> QPixmap:
        dpr = self.devicePixelRatioF()
        pm = QPixmap(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#d6dbe8"), 1))
        p.setBrush(QColor("#fbfcff"))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 8, 8)
        plot, span = self._plot_rect(), self._span()
        p.setPen(QPen(QColor("#c4cbe0"), 1))
        p.drawLine(QPointF(plot.left(), plot.bottom()), QPointF(plot.right(), plot.bottom()))
        p.setPen(Qt.PenStyle.NoPen)
        top, height = plot.top() + 6, plot.height() - 6
        for a, b in self._intervals:
            x0 = plot.left() + a / span * plot.width()
            if b is None:
                p.setBrush(QColor("#cfc5ff"))
                x1 = plot.right()
            else:
                p.setBrush(QColor("#6c4cff"))
                x1 = plot.left() + b / span * plot.width()
            p.drawRect(QRectF(x0, top, max(1.3, x1 - x0), height))
        font = p.font()
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() * 0.9)
        p.setFont(font)
        p.setPen(QColor("#5a6482"))
        for i in range(5):
            x = plot.left() + i / 4 * plot.width()
            p.drawLine(QPointF(x, plot.bottom()), QPointF(x, plot.bottom() + 4))
            label = fmt_time(i / 4 * span) if (self._total or i == 0) else ""
            if i == 0:
                rect, align = QRectF(x, plot.bottom() + 5, 90, 18), Qt.AlignmentFlag.AlignLeft
            elif i == 4:
                rect, align = QRectF(x - 90, plot.bottom() + 5, 90, 18), Qt.AlignmentFlag.AlignRight
            else:
                rect, align = QRectF(x - 45, plot.bottom() + 5, 90, 18), Qt.AlignmentFlag.AlignHCenter
            p.drawText(rect, int(align | Qt.AlignmentFlag.AlignVCenter), label)
        if self._message:
            p.setPen(QColor("#a32035"))
            p.drawText(plot, int(Qt.AlignmentFlag.AlignCenter), self._message)
        elif self._total is None and self._intervals:
            p.setPen(QColor("#5a3be6"))
            p.drawText(plot.adjusted(0, 0, -8, 0),
                       int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop),
                       "until stopped")
        p.end()
        return pm

    def paintEvent(self, _event):
        if self._base is None:
            self._base = self._render_base()
        p = QPainter(self)
        p.drawPixmap(0, 0, self._base)
        if self._cursor is not None:
            plot, span = self._plot_rect(), self._span()
            x = plot.left() + min(max(self._cursor / span, 0.0), 1.0) * plot.width()
            p.setPen(QPen(QColor("#e0334d"), 2))
            p.drawLine(QPointF(x, plot.top() - 2), QPointF(x, plot.bottom() + 2))
        p.end()


# --------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, settings: Optional[QSettings] = None):
        super().__init__()
        self.settings = settings if settings is not None else QSettings("jerjely", APP_NAME)
        self.device = None
        self.run: Optional[ProtocolRun] = None
        self.log: List[LogEntry] = []
        self._run_counter = 0
        self._n_seen = 0
        self._t_conn = time.perf_counter()
        self._ready = False
        self._manual_on = False
        self._problems: List[str] = []

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setWindowIcon(app_icon())
        self.resize(1000, 780)
        self.setMinimumSize(900, 700)

        self._build_ui()
        self._build_menu()
        self._set_conn_status("off")
        self._restore_settings()
        self.refresh_ports()
        self._protocol_changed()
        self._update_enabled()
        self._update_indicator()

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.emergency_stop)
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    # ---- UI construction ---------------------------------------------------
    @staticmethod
    def _dspin(lo, hi, value, decimals, suffix, step=1.0) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(decimals)
        s.setSingleStep(step)
        s.setSuffix(suffix)
        s.setValue(value)
        s.setAlignment(Qt.AlignmentFlag.AlignRight)
        return s

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        page = QVBoxLayout(central)
        page.setContentsMargins(12, 6, 12, 8)
        page.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(12)
        page.addLayout(top, 0)
        left = QVBoxLayout()
        left.setSpacing(6)
        top.addLayout(left, 0)

        # 1 - connection
        box = QGroupBox("1  Connection")
        box.setFixedWidth(330)
        form = QFormLayout(box)
        self.port_combo = QComboBox()
        form.addRow("Port", self.port_combo)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(BAUD_RATES)
        form.addRow("Baud rate", self.baud_combo)
        row = QHBoxLayout()
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("primary")
        self.refresh_btn = QPushButton("Rescan ports")
        row.addWidget(self.connect_btn, 1)
        row.addWidget(self.refresh_btn)
        form.addRow(row)
        self.conn_status = QLabel()
        self.conn_status.setWordWrap(True)
        form.addRow(self.conn_status)
        left.addWidget(box)

        # 2 - manual control
        box = QGroupBox("2  Manual control")
        box.setFixedWidth(330)
        v = QVBoxLayout(box)
        self.laser_pill = QLabel("LASER OFF")
        self.laser_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.laser_pill.setMinimumHeight(58)
        v.addWidget(self.laser_pill)
        row = QHBoxLayout()
        self.on_btn = QPushButton("Laser ON")
        self.on_btn.setObjectName("laserOn")
        self.off_btn = QPushButton("Laser OFF")
        self.off_btn.setObjectName("laserOff")
        row.addWidget(self.on_btn)
        row.addWidget(self.off_btn)
        v.addLayout(row)
        self.manual_hint = QLabel("Sends B (on) or N (off) to the Arduino.")
        self.manual_hint.setStyleSheet("color: #5a6482;")
        self.manual_hint.setWordWrap(True)
        v.addWidget(self.manual_hint)
        left.addWidget(box)
        left.addStretch(1)

        # 3 - protocol
        box = QGroupBox("3  Protocol")
        v = QVBoxLayout(box)
        head = QHBoxLayout()
        head.addWidget(QLabel("Mode"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Pulse train", "train")
        self.mode_combo.addItem("Continuous", "continuous")
        head.addWidget(self.mode_combo)
        head.addStretch(1)
        self.save_proto_btn = QPushButton("Save protocol...")
        self.load_proto_btn = QPushButton("Load protocol...")
        head.addWidget(self.save_proto_btn)
        head.addWidget(self.load_proto_btn)
        v.addLayout(head)

        self.delay_spin = self._dspin(0, 86400, 0, 2, " s", 0.5)
        self.pulse_spin = self._dspin(0.1, 10000, 10, 1, " ms", 1)
        self.freq_spin = self._dspin(0.01, 500, 20, 2, " Hz", 1)
        self.pulses_spin = QSpinBox()
        self.pulses_spin.setRange(1, 200000)
        self.pulses_spin.setValue(20)
        self.trains_spin = QSpinBox()
        self.trains_spin.setRange(1, 100000)
        self.trains_spin.setValue(1)
        self.rest_spin = self._dspin(0, 86400, 10, 2, " s", 1)
        self.duration_spin = self._dspin(0, 86400, 5, 1, " s", 1)
        self.duration_spin.setSpecialValueText("until stopped")
        for sp in (self.pulses_spin, self.trains_spin):
            sp.setAlignment(Qt.AlignmentFlag.AlignRight)
        for w in (self.port_combo, self.baud_combo, self.mode_combo, self.delay_spin, self.pulse_spin,
                  self.freq_spin, self.pulses_spin, self.trains_spin, self.rest_spin, self.duration_spin):
            w.setMinimumHeight(30)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        lbl_delay, lbl_rest = QLabel("Start delay"), QLabel("Rest between trains")
        lbl_dur = QLabel("Duration")
        lbl_pw, lbl_f = QLabel("Pulse width"), QLabel("Frequency")
        lbl_np, lbl_nt = QLabel("Pulses per train"), QLabel("Number of trains")
        grid.addWidget(lbl_delay, 0, 0)
        grid.addWidget(self.delay_spin, 0, 1)
        grid.addWidget(lbl_rest, 0, 2)
        grid.addWidget(self.rest_spin, 0, 3)
        grid.addWidget(lbl_dur, 0, 2)               # same cell as "rest": only one is shown
        grid.addWidget(self.duration_spin, 0, 3)
        grid.addWidget(lbl_pw, 1, 0)
        grid.addWidget(self.pulse_spin, 1, 1)
        grid.addWidget(lbl_f, 1, 2)
        grid.addWidget(self.freq_spin, 1, 3)
        grid.addWidget(lbl_np, 2, 0)
        grid.addWidget(self.pulses_spin, 2, 1)
        grid.addWidget(lbl_nt, 2, 2)
        grid.addWidget(self.trains_spin, 2, 3)
        v.addLayout(grid)
        self.train_only = [lbl_rest, self.rest_spin, lbl_pw, self.pulse_spin, lbl_f, self.freq_spin,
                           lbl_np, self.pulses_spin, lbl_nt, self.trains_spin]
        self.cont_only = [lbl_dur, self.duration_spin]

        self.summary = QLabel()
        self.summary.setStyleSheet("color: #1b2440;")
        v.addWidget(self.summary)
        self.warn_label = QLabel()
        self.warn_label.setWordWrap(True)
        v.addWidget(self.warn_label)
        self.timeline = TimelineWidget()
        v.addWidget(self.timeline)

        run_row = QHBoxLayout()
        self.start_btn = QPushButton("Start protocol")
        self.start_btn.setObjectName("primary")
        self.stop_btn = QPushButton("Stop  (Esc)")
        self.stop_btn.setObjectName("danger")
        run_row.addWidget(self.start_btn)
        run_row.addWidget(self.stop_btn)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setFormat("")
        run_row.addWidget(self.progress, 1)
        v.addLayout(run_row)
        self.run_status = QLabel("Idle.")
        self.run_status.setWordWrap(True)
        v.addWidget(self.run_status)
        top.addWidget(box, 1)

        self.param_widgets = [self.mode_combo, self.delay_spin, self.pulse_spin, self.freq_spin,
                              self.pulses_spin, self.trains_spin, self.rest_spin,
                              self.duration_spin, self.save_proto_btn, self.load_proto_btn]

        # 4 - log (full width)
        box = QGroupBox("4  Log")
        v = QVBoxLayout(box)
        self.log_table = QTableWidget(0, 8)
        self.log_table.setHorizontalHeaderLabels(
            ["Run", "Command", "Train", "Pulse", "Planned (s)", "Sent (s)", "Error (ms)", "Time"])
        self.log_table.setMinimumHeight(150)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setAlternatingRowColors(True)
        self.log_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.log_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.log_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v.addWidget(self.log_table, 1)
        row = QHBoxLayout()
        self.log_info = QLabel(LOG_HINT)
        self.log_info.setStyleSheet("color: #5a6482;")
        row.addWidget(self.log_info, 1)
        self.save_log_btn = QPushButton("Save log (CSV)...")
        self.clear_log_btn = QPushButton("Clear")
        row.addWidget(self.save_log_btn)
        row.addWidget(self.clear_log_btn)
        v.addLayout(row)
        page.addWidget(box, 1)

        foot = QLabel("Laser safety: wear eyewear rated for your laser's wavelength and power. "
                      "Esc stops everything and switches the laser off.")
        foot.setStyleSheet("color: #5a6482;")
        self.statusBar().addWidget(foot, 1)

        # signals
        self.refresh_btn.clicked.connect(lambda: self.refresh_ports())
        self.connect_btn.clicked.connect(self._toggle_connection)
        self.on_btn.clicked.connect(lambda: self._manual(True))
        self.off_btn.clicked.connect(lambda: self._manual(False))
        self.start_btn.clicked.connect(self._start)
        self.stop_btn.clicked.connect(self.emergency_stop)
        self.save_log_btn.clicked.connect(self._save_log)
        self.clear_log_btn.clicked.connect(self._clear_log)
        self.save_proto_btn.clicked.connect(self._save_protocol)
        self.load_proto_btn.clicked.connect(self._load_protocol)
        self.mode_combo.currentIndexChanged.connect(self._protocol_changed)
        for w in (self.delay_spin, self.pulse_spin, self.freq_spin, self.rest_spin,
                  self.duration_spin, self.pulses_spin, self.trains_spin):
            w.valueChanged.connect(self._protocol_changed)

    def _build_menu(self) -> None:
        m = self.menuBar().addMenu("&File")
        for text, slot in [("Save log (CSV)...", self._save_log),
                           ("Save protocol...", self._save_protocol),
                           ("Load protocol...", self._load_protocol)]:
            a = QAction(text, self)
            a.triggered.connect(slot)
            m.addAction(a)
        m.addSeparator()
        q = QAction("Quit", self)
        q.setShortcut(QKeySequence.StandardKey.Quit)
        q.triggered.connect(self.close)
        m.addAction(q)
        h = self.menuBar().addMenu("&Help")
        a = QAction(f"About {APP_NAME}", self)
        a.setMenuRole(QAction.MenuRole.AboutRole)
        a.triggered.connect(self.show_about)
        h.addAction(a)

    # ---- settings ----------------------------------------------------------
    def _restore_settings(self) -> None:
        s = self.settings
        baud = str(s.value("baud", "9600"))
        if baud in BAUD_RATES:
            self.baud_combo.setCurrentText(baud)
        text = s.value("protocol", "")
        if text:
            try:
                self._set_ui_from_protocol(Protocol.from_json(str(text)))
            except Exception:
                pass
        geo = s.value("geometry")
        if geo is not None:
            try:
                self.restoreGeometry(geo)
            except Exception:
                pass

    def _save_settings(self) -> None:
        s = self.settings
        s.setValue("port", self.port_combo.currentData() or "")
        s.setValue("baud", self.baud_combo.currentText())
        s.setValue("protocol", self._protocol_from_ui().to_json())
        s.setValue("geometry", self.saveGeometry())
        s.sync()

    # ---- ports / connection -----------------------------------------------
    @staticmethod
    def _looks_like_arduino(dev: str, desc: str) -> bool:
        text = f"{dev} {desc}".lower()
        return any(k in text for k in ("arduino", "ch340", "ch341", "usb serial", "usb-serial",
                                       "ftdi", "cp210", "usbmodem", "usbserial", "ttyacm", "ttyusb"))

    def refresh_ports(self) -> None:
        wanted = self.port_combo.currentData() or self.settings.value("port", "")
        self.port_combo.clear()
        guess = -1
        for dev, desc in list_serial_ports():
            label = dev if desc in (dev, "n/a", "") else f"{dev}  -  {desc}"
            self.port_combo.addItem(label, dev)
            if guess < 0 and self._looks_like_arduino(dev, desc):
                guess = self.port_combo.count() - 1
        self.port_combo.addItem("Simulator (no hardware)", SIM_PORT)
        idx = self.port_combo.findData(wanted)
        if idx < 0:
            idx = guess if guess >= 0 else 0      # likely Arduino, else first port or the simulator
        self.port_combo.setCurrentIndex(idx)

    def _set_conn_status(self, state: str, extra: str = "") -> None:
        colours = {"off": "#8a93ad", "wait": "#d98a00", "ready": "#1a9a4a", "error": "#d6334a"}
        texts = {"off": "Not connected", "wait": "Connecting - waiting for the Arduino to restart...",
                 "ready": "Connected and ready", "error": "Connection lost"}
        text = texts[state] + (f"  ({extra})" if extra else "")
        self.conn_status.setText(f'<span style="color:{colours[state]}">&#9679;</span> {text}')

    def _toggle_connection(self) -> None:
        if self.device is None:
            self._connect()
        else:
            self._disconnect()

    def _connect(self) -> None:
        port = self.port_combo.currentData()
        if not port:
            return
        try:
            dev = make_device(port, int(self.baud_combo.currentText()))
            dev.open()
        except Exception as exc:
            QMessageBox.critical(self, "Cannot open port",
                                 f"Could not open {port}:\n\n{exc}\n\n"
                                 "Is another program (for example the Arduino IDE's Serial Monitor) "
                                 "using this port?")
            return
        self.device = dev
        self._ready = False
        self._t_conn = time.perf_counter()
        self._set_conn_status("wait")
        self._update_enabled()
        if dev.reset_wait_s <= 0:
            self._device_ready()
        else:
            QTimer.singleShot(int(dev.reset_wait_s * 1000), self._device_ready)

    def _device_ready(self) -> None:
        dev = self.device
        if dev is None or self._ready:
            return
        try:
            if hasattr(dev, "wait_ready"):
                dev.wait_ready()
            dev.set_laser(False)          # start from a known state
        except Exception as exc:
            self._connection_lost(str(exc))
            return
        self._ready = True
        self._manual_on = False
        self._set_conn_status("ready", dev.name)
        self._update_enabled()
        self._update_indicator()

    def _disconnect(self) -> None:
        self._stop_run(wait=True)
        dev = self.device
        if dev is not None:
            try:
                if self._ready:
                    dev.set_laser(False)
            except Exception:
                pass
            try:
                dev.close()
            except Exception:
                pass
        self.device = None
        self._ready = False
        self._manual_on = False
        self._set_conn_status("off")
        self._update_enabled()
        self._update_indicator()

    def _connection_lost(self, message: str) -> None:
        dev, self.device = self.device, None
        self._ready = False
        self._manual_on = False
        if dev is not None:
            try:
                dev.close()
            except Exception:
                pass
        self._set_conn_status("error")
        self._update_enabled()
        self._update_indicator()
        QMessageBox.warning(self, "Connection problem",
                            f"{message}\n\nThe laser was switched off if the Arduino could still be reached. "
                            "Check the cable and connect again.")

    # ---- manual control ----------------------------------------------------
    def _manual(self, on: bool) -> None:
        if not self._ready or self.run is not None:
            return
        try:
            self.device.set_laser(on)
        except Exception as exc:
            self._connection_lost(str(exc))
            return
        self._manual_on = on
        self._add_log([LogEntry("manual", "ON" if on else "OFF", 0, 0, None,
                                time.perf_counter() - self._t_conn, None, now_iso())])
        self._update_indicator()

    def emergency_stop(self) -> None:
        if self.run is not None:
            self.run.stop()
        elif self._ready and self._manual_on:
            self._manual(False)

    # ---- protocol ----------------------------------------------------------
    def _protocol_from_ui(self) -> Protocol:
        return Protocol(mode=self.mode_combo.currentData(), delay_s=self.delay_spin.value(),
                        duration_s=self.duration_spin.value(), pulse_ms=self.pulse_spin.value(),
                        freq_hz=self.freq_spin.value(), pulses=self.pulses_spin.value(),
                        trains=self.trains_spin.value(), rest_s=self.rest_spin.value())

    def _set_ui_from_protocol(self, p: Protocol) -> None:
        widgets = [self.mode_combo, self.delay_spin, self.pulse_spin, self.freq_spin, self.rest_spin,
                   self.duration_spin, self.pulses_spin, self.trains_spin]
        for w in widgets:
            w.blockSignals(True)
        idx = self.mode_combo.findData(p.mode)
        self.mode_combo.setCurrentIndex(max(0, idx))
        self.delay_spin.setValue(p.delay_s)
        self.pulse_spin.setValue(p.pulse_ms)
        self.freq_spin.setValue(p.freq_hz)
        self.pulses_spin.setValue(p.pulses)
        self.trains_spin.setValue(p.trains)
        self.rest_spin.setValue(p.rest_s)
        self.duration_spin.setValue(p.duration_s)
        for w in widgets:
            w.blockSignals(False)
        self._protocol_changed()

    def _protocol_changed(self, *_args) -> None:
        p = self._protocol_from_ui()
        is_train = p.mode == "train"
        for w in self.train_only:
            w.setVisible(is_train)
        for w in self.cont_only:
            w.setVisible(not is_train)
        self._problems = p.problems()
        if self._problems:
            self.summary.setText("")
            self.warn_label.setStyleSheet("color: #a32035;")
            self.warn_label.setText(" ".join(self._problems))
            self.timeline.set_plan([], None, "Fix the protocol to see the preview")
        else:
            total = p.total_s()
            if is_train:
                self.summary.setText(
                    f"Period {p.period_s * 1000:.4g} ms  |  duty cycle {p.duty * 100:.3g} %  |  "
                    f"one train {fmt_time(p.train_s)}  |  total "
                    f"{fmt_time(total) if total is not None else 'until stopped'}")
            else:
                self.summary.setText("Laser on for " + (fmt_time(p.duration_s) if p.duration_s > 0
                                                        else "as long as you wait"))
            warns = p.warnings()
            self.warn_label.setStyleSheet("color: #9a6200;")
            self.warn_label.setText(" ".join(warns))
            self.timeline.set_plan(p.intervals(), total)
        self.warn_label.setVisible(bool(self.warn_label.text()))
        self._update_enabled()

    def _save_protocol(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save protocol", self._dir("protocol.json"),
                                              "OptoStim protocol (*.json)")
        if path:
            try:
                Path(path).write_text(self._protocol_from_ui().to_json(), encoding="utf-8")
                self.settings.setValue("last_dir", str(Path(path).parent))
            except OSError as exc:
                QMessageBox.critical(self, "Cannot save", str(exc))

    def _load_protocol(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load protocol", self._dir(""),
                                              "OptoStim protocol (*.json)")
        if path:
            try:
                self._set_ui_from_protocol(Protocol.from_json(Path(path).read_text(encoding="utf-8")))
                self.settings.setValue("last_dir", str(Path(path).parent))
            except Exception as exc:
                QMessageBox.critical(self, "Cannot load protocol", str(exc))

    def _dir(self, name: str) -> str:
        base = str(self.settings.value("last_dir", str(Path.home())))
        return str(Path(base) / name) if name else base

    # ---- running -----------------------------------------------------------
    def _start(self) -> None:
        if not self._ready or self.run is not None:
            return
        proto = self._protocol_from_ui()
        problems = proto.problems()
        if problems:
            QMessageBox.warning(self, "Protocol not valid", " ".join(problems))
            return
        if self._manual_on:
            try:
                self.device.set_laser(False)
            except Exception as exc:
                self._connection_lost(str(exc))
                return
            self._manual_on = False
        self._run_counter += 1
        self.run = ProtocolRun(self.device, proto, f"run {self._run_counter}")
        self._n_seen = 0
        self.progress.setRange(0, 1000 if self.run.total_s else 0)
        self.progress.setValue(0)
        self.run_status.setStyleSheet("")
        self.run_status.setText(f"Running {self.run.label}...")
        self.run.start()
        self._update_enabled()

    def _stop_run(self, wait: bool = False) -> None:
        run = self.run
        if run is None:
            return
        run.stop()
        if wait:
            run.join(3.0)
            self._poll()

    def _poll(self) -> None:
        run = self.run
        if run is not None:
            running = run.running           # read before the entries so none are missed
            entries = run.entries
            n = len(entries)
            if n > self._n_seen:
                new = entries[self._n_seen:n]
                self._n_seen = n
                self._add_log(new)
            elapsed = run.elapsed_s
            total = run.total_s
            if running:
                if total:
                    self.progress.setValue(min(1000, int(elapsed / total * 1000)))
                    self.run_status.setText(
                        f"Running {run.label}:  {fmt_time(elapsed)} of {fmt_time(total)}"
                        f"  |  {n} commands sent")
                else:
                    self.run_status.setText(f"Running {run.label}:  {fmt_time(elapsed)}  |  until stopped")
                self.timeline.set_cursor(elapsed)
            else:
                self._finish_run(run)
        self._update_indicator()

    def _finish_run(self, run: ProtocolRun) -> None:
        self.run = None
        self.timeline.set_cursor(None)
        self.progress.setRange(0, 1000)
        stats = timing_summary(run.entries)
        timing = (f"timing error: mean {stats['mean_abs_ms']:.2f} ms, max {stats['max_abs_ms']:.2f} ms"
                  if stats["n"] else "")
        if run.error:
            self.progress.setValue(0)
            self.run_status.setStyleSheet("color: #a32035;")
            self.run_status.setText(f"{run.label} failed: {run.error}")
            self._connection_lost(run.error)
        elif run.stopped:
            self.progress.setValue(0)
            self.run_status.setStyleSheet("color: #9a6200;")
            self.run_status.setText(f"{run.label} stopped after {fmt_time(run.elapsed_s)} - laser off.  {timing}")
        else:
            self.progress.setValue(1000)
            self.run_status.setStyleSheet("color: #1a7a3a;")
            self.run_status.setText(f"{run.label} finished: {len(run.entries)} commands sent, {timing}")
        self._update_enabled()

    # ---- log ---------------------------------------------------------------
    def _add_log(self, entries: List[LogEntry]) -> None:
        self.log.extend(entries)
        t = self.log_table
        t.setUpdatesEnabled(False)
        right = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for e in entries:
            r = t.rowCount()
            t.insertRow(r)
            cells = [e.run, e.command, str(e.train or ""), str(e.pulse or ""),
                     "" if e.planned_s is None else f"{e.planned_s:.4f}", f"{e.sent_s:.4f}",
                     "" if e.error_ms is None else f"{e.error_ms:+.2f}", e.wall_time[11:23]]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c >= 2:
                    item.setTextAlignment(right)
                if c == 1:
                    item.setForeground(QColor("#5a3be6" if e.command == "ON" else "#5a6482"))
                t.setItem(r, c, item)
        extra = t.rowCount() - MAX_TABLE_ROWS
        for _ in range(max(0, extra)):
            t.removeRow(0)
        t.scrollToBottom()
        t.setUpdatesEnabled(True)
        shown = t.rowCount()
        self.log_info.setText(
            f"{len(self.log)} commands logged"
            + (f" (last {shown} shown; the saved file has all)" if len(self.log) > shown else "")
            + ".  " + LOG_HINT)

    def _clear_log(self) -> None:
        self.log.clear()
        self.log_table.setRowCount(0)
        self.log_info.setText(LOG_HINT)

    def _save_log(self) -> None:
        if not self.log:
            QMessageBox.information(self, "Nothing to save", "The log is empty.")
            return
        default = f"optostim_log_{datetime.now():%Y%m%d_%H%M%S}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Save log", self._dir(default), "CSV (*.csv)")
        if path:
            try:
                write_log_csv(path, self.log)
                self.settings.setValue("last_dir", str(Path(path).parent))
            except OSError as exc:
                QMessageBox.critical(self, "Cannot save", str(exc))

    # ---- state -------------------------------------------------------------
    def _update_indicator(self) -> None:
        on = self.run.laser_on if self.run is not None else (self._manual_on and self._ready)
        if on:
            self.laser_pill.setText("LASER ON")
            self.laser_pill.setStyleSheet("background: #6c4cff; color: #ffffff; border-radius: 10px;"
                                          "font-size: 20px; font-weight: bold; letter-spacing: 2px;")
        else:
            self.laser_pill.setText("LASER OFF")
            self.laser_pill.setStyleSheet("background: #e6e9f3; color: #5a6482; border-radius: 10px;"
                                          "font-size: 20px; font-weight: bold; letter-spacing: 2px;")

    def _update_enabled(self) -> None:
        connected = self.device is not None
        running = self.run is not None
        ready = connected and self._ready
        self.port_combo.setEnabled(not connected)
        self.baud_combo.setEnabled(not connected)
        self.refresh_btn.setEnabled(not connected)
        self.connect_btn.setText("Disconnect" if connected else "Connect")
        self.connect_btn.setEnabled(not running)
        self.on_btn.setEnabled(ready and not running)
        self.off_btn.setEnabled(ready and not running)
        self.start_btn.setEnabled(ready and not running and not self._problems)
        self.stop_btn.setEnabled(running)
        for w in self.param_widgets:
            w.setEnabled(not running)

    # ---- misc --------------------------------------------------------------
    def show_about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(f"About {APP_NAME}")
        pm = QPixmap(str(resource_path("icon_256.png")))
        if not pm.isNull():
            box.setIconPixmap(pm.scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(
            f"<h3>{APP_NAME} {__version__}</h3>"
            "<p>Laser pulse-train controller for an Arduino-driven MOSFET switch.</p>"
            f"<p>&copy; 2026 {APP_AUTHOR}. MIT License.<br>"
            f'<a href="{APP_URL}">{APP_URL}</a></p>'
            f'<p style="color:#5a6482">Python {platform.python_version()}, Qt {QtCore.qVersion()}, '
            f"{platform.system()} {platform.machine()}</p>")
        box.exec()

    def shutdown(self) -> None:
        self._timer.stop()
        self._stop_run(wait=True)
        self._disconnect()

    def closeEvent(self, event) -> None:
        try:
            self._save_settings()
        finally:
            self.shutdown()
        event.accept()


def run_gui() -> int:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("jerjely")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon())
    apply_style(app)
    win = MainWindow()
    win.show()
    return app.exec()
