"""Creates the README screenshots in docs/screenshots/ from synthetic data.

    pip install -r requirements.txt pillow
    python tools/make_screenshots.py

Runs the real GUI offscreen against the built-in simulator (no hardware, no
personal data), drives it like a user would and saves ~1400 px wide JPEGs.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "1.4")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image                                   # noqa: E402
from PySide6.QtCore import QSettings                    # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase          # noqa: E402
from PySide6.QtWidgets import QApplication             # noqa: E402

from optostim.core import SIM_PORT, Protocol            # noqa: E402
from optostim.gui import MainWindow, apply_style        # noqa: E402

OUT = ROOT / "docs" / "screenshots"
TARGET_WIDTH = 1400


def pump(app, seconds=0.0, until=None, timeout=60.0):
    end = time.time() + (timeout if until else seconds)
    while time.time() < end:
        app.processEvents()
        if until and until():
            break
        time.sleep(0.01)
    app.processEvents()


def shot(app, win, name, tmp, settle=0.15):
    pump(app, settle)
    png = Path(tmp) / f"{name}.png"
    win.grab().save(str(png), "PNG")
    img = Image.open(png).convert("RGB")
    if img.width != TARGET_WIDTH:
        img = img.resize((TARGET_WIDTH, round(img.height * TARGET_WIDTH / img.width)), Image.Resampling.LANCZOS)
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / f"{name}.jpg", quality=88, optimize=True)
    print(f"saved {name}.jpg  {img.width}x{img.height}")


def main():
    app = QApplication(["optostim-screenshots"])
    if "Inter" in QFontDatabase.families():
        app.setFont(QFont("Inter", 10))
    apply_style(app)
    with tempfile.TemporaryDirectory() as tmp:
        win = MainWindow(QSettings(str(Path(tmp) / "s.ini"), QSettings.Format.IniFormat))
        win.resize(1000, 780)
        win.show()
        win.port_combo.setCurrentIndex(win.port_combo.findData(SIM_PORT))
        win.connect_btn.click()
        pump(app, until=lambda: win._ready, timeout=5)

        # a short earlier run so the log is not empty
        win._set_ui_from_protocol(Protocol(delay_s=0.1, pulse_ms=10, freq_hz=40, pulses=6, trains=2, rest_s=0.2))
        win.start_btn.click()
        pump(app, until=lambda: win.run is None)

        # 1  overview with a pulse-train protocol
        win._set_ui_from_protocol(Protocol(mode="train", delay_s=2, pulse_ms=10, freq_hz=20,
                                           pulses=20, trains=3, rest_s=10))
        shot(app, win, "01-main-window", tmp)

        # 2  mid-run, laser on (slow pulses so the pill is lit when the picture is taken)
        win._set_ui_from_protocol(Protocol(mode="train", delay_s=0.5, pulse_ms=200, freq_hz=2,
                                           pulses=12, trains=2, rest_s=3))
        win._clear_log()
        win.start_btn.click()
        pump(app, until=lambda: win.run is not None and win.run.elapsed_s > 3.0
             and win.laser_pill.text() == "LASER ON", timeout=30)
        shot(app, win, "02-running-pulse-train", tmp, settle=0)
        win.stop_btn.click()
        pump(app, until=lambda: win.run is None)

        # 3  continuous mode and manual control
        win.mode_combo.setCurrentIndex(win.mode_combo.findData("continuous"))
        win.duration_spin.setValue(30)
        win.delay_spin.setValue(0)
        win.on_btn.click()
        shot(app, win, "03-continuous-and-manual-control", tmp)
        win.off_btn.click()

        # 4  timing log after a finished run
        win._clear_log()
        win._set_ui_from_protocol(Protocol(mode="train", delay_s=0.2, pulse_ms=15, freq_hz=25,
                                           pulses=24, trains=1, rest_s=0))
        win.start_btn.click()
        pump(app, until=lambda: win.run is None)
        shot(app, win, "04-timing-log", tmp)

        # 5  a long multi-train protocol in the preview
        win._set_ui_from_protocol(Protocol(mode="train", delay_s=2, pulse_ms=50, freq_hz=5,
                                           pulses=20, trains=5, rest_s=6))
        shot(app, win, "05-five-train-protocol-preview", tmp)

        win.close()
        pump(app, 0.1)


if __name__ == "__main__":
    main()
