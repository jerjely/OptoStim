"""Built-in self-test: `OptoStim --selftest`.

Runs the real code paths on a small synthetic dataset (a synthetic pulse-train
protocol on a simulated device and on a pySerial loopback port, then the whole
GUI driven offscreen) and exits with code 0 only if everything works. The
release workflow runs this against every freshly built app, so a broken
installer is never published.
"""
from __future__ import annotations

import csv
import faulthandler
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path


class _Ctx:
    def __init__(self, tmp: Path, expect_version, log):
        self.tmp = tmp
        self.expect_version = expect_version
        self.log = log
        self.entries = []        # filled by the simulated-run test, reused by the CSV test


def _pump(app, condition, timeout: float, what: str) -> None:
    end = time.time() + timeout
    while not condition():
        if time.time() > end:
            raise AssertionError(f"timed out waiting for: {what}")
        app.processEvents()
        time.sleep(0.005)


# --------------------------------------------------------------------------
def t_version(ctx):
    from . import __version__
    assert __version__, "empty version"
    if ctx.expect_version:
        want = ctx.expect_version.lstrip("v")
        assert __version__ == want, f"built-in version {__version__!r} != expected {want!r}"
    ctx.log(f"    version {__version__}")


def t_imports(ctx):
    import PySide6  # noqa: F401
    import serial  # noqa: F401
    import serial.urlhandler.protocol_loop  # noqa: F401   (needs bundling by PyInstaller)
    from serial.tools import list_ports
    ports = list(list_ports.comports())
    ctx.log(f"    {len(ports)} serial port(s) visible")


def t_protocol_math(ctx):
    from .core import Protocol
    p = Protocol(mode="train", delay_s=0.5, pulse_ms=10, freq_hz=20, pulses=5, trains=2, rest_s=0.2)
    edges = p.schedule()
    assert len(edges) == 20, len(edges)
    assert abs(p.train_s - 0.21) < 1e-9, p.train_s
    assert abs(edges[0].t - 0.5) < 1e-9 and edges[0].on
    assert abs(edges[1].t - 0.51) < 1e-9 and not edges[1].on
    assert abs(edges[10].t - (0.5 + 0.21 + 0.2)) < 1e-9, edges[10]     # first pulse of train 2
    assert edges[10].train == 2 and edges[10].pulse == 1
    assert abs(p.total_s() - (0.5 + 2 * 0.21 + 0.2)) < 1e-9
    assert [e.t for e in edges] == sorted(e.t for e in edges)
    assert len(p.intervals()) == 10
    c = Protocol(mode="continuous", duration_s=0)
    assert c.total_s() is None and len(c.schedule()) == 1
    bad = Protocol(mode="train", pulse_ms=60, freq_hz=20)
    assert bad.problems(), "pulse longer than the period must be rejected"
    try:
        bad.schedule()
    except ValueError:
        pass
    else:
        raise AssertionError("schedule() accepted an invalid protocol")


def t_simulated_run(ctx):
    from .core import Protocol, ProtocolRun, SimulatedDevice, timing_summary
    dev = SimulatedDevice()
    dev.open()
    p = Protocol(mode="train", pulse_ms=8, freq_hz=50, pulses=10, trains=2, rest_s=0.1)
    run = ProtocolRun(dev, p, "selftest")
    run.start()
    run.join(10)
    assert not run.running, "run did not finish"
    assert run.completed and not run.error, run.error
    assert len(run.entries) == 40, len(run.entries)
    assert len(dev.events) == 40 and [e[1] for e in dev.events] == [True, False] * 20
    assert not run.laser_on and dev.events[-1][1] is False
    stats = timing_summary(run.entries)
    assert stats["max_abs_ms"] < 60, f"timing error too large: {stats}"
    on_ms = [(run.entries[i + 1].sent_s - run.entries[i].sent_s) * 1000 for i in range(0, 40, 2)]
    assert all(abs(d - 8) < 40 for d in on_ms), on_ms
    ctx.entries = list(run.entries)
    ctx.log(f"    40 commands, timing error mean {stats['mean_abs_ms']:.2f} ms, max {stats['max_abs_ms']:.2f} ms")


def t_stop(ctx):
    from .core import Protocol, ProtocolRun, SimulatedDevice
    dev = SimulatedDevice()
    dev.open()
    run = ProtocolRun(dev, Protocol(mode="continuous", duration_s=0), "selftest-stop")
    run.start()
    time.sleep(0.3)
    assert run.laser_on, "laser should be on"
    run.stop()
    run.join(5)
    assert not run.running and run.stopped
    assert dev.events[0][1] is True and dev.events[-1][1] is False, "laser must end OFF after Stop"


def t_serial_loopback(ctx):
    from .core import Protocol, ProtocolRun, SerialDevice
    dev = SerialDevice("loop://", 9600)
    dev.open()
    dev.wait_ready()
    dev.set_laser(True)
    dev.set_laser(False)
    assert dev.read_available() == b"BN", "serial protocol bytes are wrong"
    run = ProtocolRun(dev, Protocol(mode="train", pulse_ms=5, freq_hz=20, pulses=3, rest_s=0), "selftest-serial")
    run.start()
    run.join(10)
    assert run.completed and not run.error, run.error
    assert dev.read_available() == b"BNBNBN"
    dev.close()


def t_csv_and_json(ctx):
    from .core import LOG_COLUMNS, Protocol, write_log_csv
    assert ctx.entries, "needs the simulated-run test to have run"
    path = ctx.tmp / "log.csv"
    write_log_csv(str(path), ctx.entries)
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == len(ctx.entries) and list(rows[0].keys()) == LOG_COLUMNS
    p = Protocol(mode="train", delay_s=1.5, pulse_ms=12.5, freq_hz=7, pulses=33, trains=4, rest_s=6.5)
    assert Protocol.from_json(p.to_json()) == p


def t_gui(ctx):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from .core import SIM_PORT, Protocol, write_log_csv
    from .gui import MainWindow, app_icon, apply_style

    app = QApplication.instance() or QApplication(["optostim-selftest"])
    apply_style(app)
    ctx.log(f"    Qt platform: {app.platformName()}")
    assert not app_icon().isNull(), "application icon missing from the bundle"

    settings = QSettings(str(ctx.tmp / "gui.ini"), QSettings.Format.IniFormat)
    win = MainWindow(settings)
    win.show()
    app.processEvents()
    assert "OptoStim" in win.windowTitle()

    win.port_combo.setCurrentIndex(win.port_combo.findData(SIM_PORT))
    win.connect_btn.click()
    _pump(app, lambda: win._ready, 5, "simulator connection")
    assert win.start_btn.isEnabled()

    win._set_ui_from_protocol(Protocol(mode="train", delay_s=0.05, pulse_ms=10, freq_hz=40,
                                       pulses=6, trains=2, rest_s=0.1))
    win.start_btn.click()
    _pump(app, lambda: win.run is None, 15, "protocol to finish")
    assert len(win.log) == 24, len(win.log)
    assert win.log_table.rowCount() == 24
    assert win.run_status.text().startswith("run 1 finished"), win.run_status.text()

    win.on_btn.click()
    assert win.laser_pill.text() == "LASER ON"
    win.off_btn.click()
    assert win.laser_pill.text() == "LASER OFF"
    assert len(win.log) == 26

    win.mode_combo.setCurrentIndex(win.mode_combo.findData("continuous"))
    win.duration_spin.setValue(0)
    win.start_btn.click()
    _pump(app, lambda: win.run is not None and win.run.laser_on, 5, "continuous laser on")
    win.stop_btn.click()
    _pump(app, lambda: win.run is None, 5, "continuous run to stop")
    assert win.laser_pill.text() == "LASER OFF"

    img = win.grab().toImage()
    assert img.width() > 400 and img.height() > 300, (img.width(), img.height())
    colours = {img.pixel(x, y) for x in range(0, img.width(), 37) for y in range(0, img.height(), 29)}
    assert len(colours) > 6, "window rendered blank"

    write_log_csv(str(ctx.tmp / "gui_log.csv"), win.log)
    win.close()
    app.processEvents()


TESTS = [
    ("version", t_version),
    ("imports", t_imports),
    ("protocol maths", t_protocol_math),
    ("run on simulated device", t_simulated_run),
    ("stop switches laser off", t_stop),
    ("serial protocol (loopback)", t_serial_loopback),
    ("log CSV and protocol JSON", t_csv_and_json),
    ("GUI end to end", t_gui),
]


def run_selftest(log_path=None, expect_version=None) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    path = Path(log_path) if log_path else Path(tempfile.gettempdir()) / "optostim-selftest.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "w", buffering=1, encoding="utf-8")
    faulthandler.enable(file=fh)        # a hard crash leaves a traceback in the log

    def log(msg: str) -> None:
        fh.write(msg + "\n")
        if sys.stdout is not None:
            try:
                print(msg, flush=True)
            except Exception:
                pass

    from . import __version__
    log(f"OptoStim {__version__} self-test  (python {sys.version.split()[0]}, {sys.platform})")
    failures = 0
    with tempfile.TemporaryDirectory(prefix="optostim-selftest-") as tmp:
        ctx = _Ctx(Path(tmp), expect_version, log)
        for name, fn in TESTS:
            t0 = time.perf_counter()
            try:
                fn(ctx)
                log(f"PASS  {name}  ({(time.perf_counter() - t0) * 1000:.0f} ms)")
            except Exception:
                failures += 1
                log(f"FAIL  {name}")
                log(traceback.format_exc())
    log("SELFTEST OK" if failures == 0 else f"SELFTEST FAILED ({failures} failed)")
    faulthandler.disable()
    fh.close()
    return 0 if failures == 0 else 1
