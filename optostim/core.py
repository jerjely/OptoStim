"""OptoStim core logic: protocol maths, devices and the pulse scheduler.

Nothing in this module imports Qt, so it can be tested (and used in scripts)
without a display.

Serial protocol (one byte per command, matches firmware/OptoStim_Arduino):
    b"B"  -> laser output HIGH (on)
    b"N"  -> laser output LOW  (off)
"""
from __future__ import annotations

import csv
import json
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from typing import Callable, List, Optional

ON_BYTE = b"B"
OFF_BYTE = b"N"

SIM_PORT = "sim://"          # pseudo port name for the built-in simulator
MAX_EDGES = 400_000          # sanity limit for one protocol (ON + OFF edges)


# --------------------------------------------------------------------------
# Protocol
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Edge:
    """One planned switching event."""
    t: float        # seconds after protocol start
    on: bool
    train: int      # 1-based
    pulse: int      # 1-based


@dataclass
class Protocol:
    mode: str = "train"          # "train" or "continuous"
    delay_s: float = 0.0         # wait before the first light
    # continuous mode
    duration_s: float = 5.0      # 0 = until stopped
    # pulse-train mode
    pulse_ms: float = 10.0
    freq_hz: float = 20.0
    pulses: int = 20
    trains: int = 1
    rest_s: float = 10.0         # gap between the end of a train and the next start

    # ---- derived numbers -------------------------------------------------
    @property
    def period_s(self) -> float:
        return 1.0 / self.freq_hz if self.freq_hz > 0 else float("inf")

    @property
    def duty(self) -> float:
        return (self.pulse_ms / 1000.0) / self.period_s

    @property
    def train_s(self) -> float:
        return (self.pulses - 1) * self.period_s + self.pulse_ms / 1000.0

    def total_s(self) -> Optional[float]:
        """Planned duration in seconds, or None if it runs until stopped."""
        if self.mode == "continuous":
            if self.duration_s <= 0:
                return None
            return self.delay_s + self.duration_s
        return self.delay_s + self.trains * self.train_s + (self.trains - 1) * self.rest_s

    # ---- validation ------------------------------------------------------
    def problems(self) -> List[str]:
        """Reasons why this protocol cannot be run (empty list = fine)."""
        out: List[str] = []
        if self.mode not in ("train", "continuous"):
            out.append("Unknown mode.")
            return out
        if self.delay_s < 0:
            out.append("Start delay cannot be negative.")
        if self.mode == "continuous":
            if self.duration_s < 0:
                out.append("Duration cannot be negative.")
            return out
        if self.freq_hz <= 0:
            out.append("Frequency must be above 0 Hz.")
            return out
        if self.pulse_ms <= 0:
            out.append("Pulse width must be above 0 ms.")
        if self.pulse_ms / 1000.0 >= self.period_s:
            out.append("Pulse width must be shorter than the period "
                       f"({self.period_s * 1000:.1f} ms at {self.freq_hz:g} Hz).")
        if self.pulses < 1:
            out.append("At least one pulse per train is needed.")
        if self.trains < 1:
            out.append("At least one train is needed.")
        if self.rest_s < 0:
            out.append("Rest between trains cannot be negative.")
        if self.pulses * self.trains * 2 > MAX_EDGES:
            out.append(f"Too many pulses (limit {MAX_EDGES // 2}).")
        return out

    def warnings(self) -> List[str]:
        """Things that are allowed but worth a second look."""
        out: List[str] = []
        if self.mode == "train" and not self.problems():
            if self.freq_hz > 100:
                out.append("Above 100 Hz the USB serial timing is no longer precise; "
                           "use a hardware timer for fast trains.")
            if self.pulse_ms < 2:
                out.append("Pulses shorter than 2 ms will vary by a large fraction of their width.")
            total = self.total_s()
            if total and total > 3600:
                out.append("This protocol runs for more than an hour.")
        if self.mode == "continuous" and self.duration_s == 0:
            out.append("Laser stays on until you press Stop.")
        return out

    # ---- schedule --------------------------------------------------------
    def schedule(self) -> List[Edge]:
        """All switching events in time order. Raises ValueError if invalid."""
        problems = self.problems()
        if problems:
            raise ValueError(" ".join(problems))
        if self.mode == "continuous":
            edges = [Edge(self.delay_s, True, 1, 1)]
            if self.duration_s > 0:
                edges.append(Edge(self.delay_s + self.duration_s, False, 1, 1))
            return edges
        pulse_s = self.pulse_ms / 1000.0
        period = self.period_s
        edges = []
        train_start = self.delay_s
        for k in range(self.trains):
            for j in range(self.pulses):
                t_on = train_start + j * period
                edges.append(Edge(t_on, True, k + 1, j + 1))
                edges.append(Edge(t_on + pulse_s, False, k + 1, j + 1))
            train_start += self.train_s + self.rest_s
        return edges

    def intervals(self) -> List[tuple]:
        """(start, end) pairs of the planned ON periods; end is None if open-ended."""
        out = []
        start = None
        for e in self.schedule():
            if e.on:
                start = e.t
            elif start is not None:
                out.append((start, e.t))
                start = None
        if start is not None:
            out.append((start, None))
        return out

    # ---- (de)serialisation -----------------------------------------------
    def to_json(self) -> str:
        return json.dumps({"optostim_protocol": 1, **asdict(self)}, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Protocol":
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("Not an OptoStim protocol file.")
        kwargs = {}
        for f in fields(cls):
            if f.name in data:
                default = getattr(cls(), f.name)
                try:
                    kwargs[f.name] = type(default)(data[f.name])
                except (TypeError, ValueError):
                    raise ValueError(f"Bad value for '{f.name}'.") from None
        return cls(**kwargs)


# --------------------------------------------------------------------------
# Devices
# --------------------------------------------------------------------------
class Device:
    """Something that can switch the laser."""
    name = "device"
    reset_wait_s = 0.0          # time after open() before commands are reliable

    def open(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def set_laser(self, on: bool) -> None:
        raise NotImplementedError


class SerialDevice(Device):
    """Arduino (or anything speaking the B/N protocol) on a serial port.

    `port` may be a normal port name (COM3, /dev/ttyACM0, /dev/cu.usbmodem1101)
    or any pySerial URL such as ``loop://`` (used by the self-test).
    An Arduino Uno resets when the port is opened, so commands are only
    reliable after ``reset_wait_s`` seconds.
    """

    def __init__(self, port: str, baud: int = 9600, reset_wait_s: Optional[float] = None):
        self.port = port
        self.baud = int(baud)
        self.name = f"{port} @ {self.baud}"
        if reset_wait_s is None:
            reset_wait_s = 0.0 if "://" in port else 2.0
        self.reset_wait_s = reset_wait_s
        self._ser = None
        self._opened_at = 0.0

    def open(self) -> None:
        import serial  # imported lazily so the module loads without pyserial
        self._ser = serial.serial_for_url(self.port, baudrate=self.baud,
                                          timeout=0.2, write_timeout=1.0)
        self._opened_at = time.monotonic()

    def wait_ready(self) -> None:
        remaining = self.reset_wait_s - (time.monotonic() - self._opened_at)
        if remaining > 0:
            time.sleep(remaining)
        if self._ser is not None:
            self._ser.reset_input_buffer()

    def set_laser(self, on: bool) -> None:
        if self._ser is None:
            raise RuntimeError("Serial port is not open.")
        self._ser.write(ON_BYTE if on else OFF_BYTE)

    def read_available(self) -> bytes:
        """Bytes that came back (only useful with loop:// in tests)."""
        if self._ser is None:
            return b""
        return self._ser.read(self._ser.in_waiting or 0)

    def close(self) -> None:
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.flush()
            finally:
                ser.close()


class SimulatedDevice(Device):
    """No hardware: records what would have been sent."""
    name = "Simulator"

    def __init__(self):
        self.events: List[tuple] = []     # (perf_counter, bool)
        self.written = bytearray()
        self.is_open = False

    def open(self) -> None:
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def set_laser(self, on: bool) -> None:
        if not self.is_open:
            raise RuntimeError("Simulator is not open.")
        self.events.append((time.perf_counter(), on))
        self.written += ON_BYTE if on else OFF_BYTE


def make_device(port: str, baud: int = 9600) -> Device:
    if port == SIM_PORT:
        return SimulatedDevice()
    return SerialDevice(port, baud)


def list_serial_ports() -> List[tuple]:
    """[(device, description)] for the serial ports found on this computer."""
    try:
        from serial.tools import list_ports
        return [(p.device, p.description or p.device) for p in sorted(list_ports.comports())]
    except Exception:
        return []


# --------------------------------------------------------------------------
# Running a protocol
# --------------------------------------------------------------------------
@dataclass
class LogEntry:
    run: str                   # "run 1", "manual", ...
    command: str               # "ON" / "OFF"
    train: int
    pulse: int
    planned_s: Optional[float]  # None for manual / safety commands
    sent_s: float              # when the command was handed to the port
    error_ms: Optional[float]
    wall_time: str             # ISO 8601, local time with offset


LOG_COLUMNS = ["run", "command", "train", "pulse", "planned_s", "sent_s", "error_ms", "wall_time"]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def write_log_csv(path: str, entries: List[LogEntry]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(LOG_COLUMNS)
        for e in entries:
            w.writerow([
                e.run, e.command,
                e.train or "", e.pulse or "",
                "" if e.planned_s is None else f"{e.planned_s:.6f}",
                f"{e.sent_s:.6f}",
                "" if e.error_ms is None else f"{e.error_ms:.3f}",
                e.wall_time,
            ])


def timing_summary(entries: List[LogEntry]) -> dict:
    errs = [abs(e.error_ms) for e in entries if e.error_ms is not None]
    if not errs:
        return {"n": 0, "mean_abs_ms": 0.0, "max_abs_ms": 0.0}
    return {"n": len(errs), "mean_abs_ms": sum(errs) / len(errs), "max_abs_ms": max(errs)}


@contextmanager
def _fine_timer():
    """Ask Windows for 1 ms timer resolution while a protocol runs."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.winmm.timeBeginPeriod(1)
        except Exception:
            yield
            return
        try:
            yield
        finally:
            try:
                ctypes.windll.winmm.timeEndPeriod(1)
            except Exception:
                pass
    else:
        yield


def _wait_until(target: float, stop: threading.Event, clock: Callable[[], float]) -> bool:
    """Sleep until clock() >= target. Returns False if stop was set first."""
    while True:
        if stop.is_set():
            return False
        remaining = target - clock()
        if remaining <= 0:
            return True
        if remaining > 0.006:
            time.sleep(min(remaining - 0.004, 0.02))
        # else: spin for the last few milliseconds


class ProtocolRun:
    """Runs a Protocol on a Device in a background thread.

    Poll ``entries``, ``elapsed_s``, ``laser_on`` and ``running`` from any thread.
    The laser is always switched off when the run ends, is stopped or fails.
    """

    def __init__(self, device: Device, protocol: Protocol, label: str = "run 1",
                 clock: Callable[[], float] = time.perf_counter):
        problems = protocol.problems()
        if problems:
            raise ValueError(" ".join(problems))
        self.device = device
        self.protocol = protocol
        self.label = label
        self._clock = clock
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._t0: Optional[float] = None
        self.entries: List[LogEntry] = []
        self.laser_on = False
        self.stopped = False
        self.completed = False
        self.error: Optional[str] = None
        self.total_s = protocol.total_s()

    # ---- control -----------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._main, name="optostim-run", daemon=True)
        self._t0 = self._clock()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: Optional[float] = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def elapsed_s(self) -> float:
        return 0.0 if self._t0 is None else self._clock() - self._t0

    # ---- worker ------------------------------------------------------------
    def _send(self, on: bool, planned: Optional[float], train: int, pulse: int) -> None:
        t_cmd = self._clock()
        self.device.set_laser(on)
        self.laser_on = on
        sent = t_cmd - self._t0
        self.entries.append(LogEntry(
            run=self.label, command="ON" if on else "OFF", train=train, pulse=pulse,
            planned_s=planned, sent_s=sent,
            error_ms=None if planned is None else (sent - planned) * 1000.0,
            wall_time=now_iso()))

    def _main(self) -> None:
        with _fine_timer():
            try:
                edges = self.protocol.schedule()
                aborted = False
                for edge in edges:
                    if not _wait_until(self._t0 + edge.t, self._stop, self._clock):
                        aborted = True
                        break
                    self._send(edge.on, edge.t, edge.train, edge.pulse)
                if not aborted and self.total_s is None:
                    # open-ended continuous run: wait for Stop
                    while not self._stop.is_set():
                        time.sleep(0.02)
                    aborted = True
                if aborted:
                    self.stopped = True
                else:
                    self.completed = True
            except Exception as exc:  # serial unplugged, write timeout, ...
                self.error = f"{type(exc).__name__}: {exc}"
            finally:
                if self.laser_on or self.stopped or self.error:
                    try:
                        self._send(False, None, 0, 0)
                    except Exception as exc:
                        if self.error is None:
                            self.error = f"{type(exc).__name__}: {exc}"
                        self.laser_on = False
