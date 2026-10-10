"""Metrics recorder — appends every collected snapshot to disk, independent of the UI.

Subscribes to the event bus, so it writes on the *collector* thread (never the Tk
thread). Append + flush each row: data is on disk even if the UI lags or is closed.
Default log dir: %LOCALAPPDATA%/XPUObserver/logs (override with XPU_LOG_DIR).
"""
from __future__ import annotations

import csv
import os
import threading
import time
from typing import Any, Optional

# Curated columns — stable header, one row per collection cycle.
COLUMNS = [
    "cpu.load_pct", "cpu.freq_mhz", "cpu.temp_c",
    "ram.pct", "ram.used_gb",
    "gpu.0.load_pct", "gpu.0.temp_c", "gpu.0.mem_used_mb", "gpu.0.power_w",
    "igpu.load_pct",
    "npu.load_pct", "npu.display", "npu.dispatch_s", "npu.tps_est",
    "npu.ctx_count", "npu.mem_mb", "npu.temp_c", "npu.power_w",
    "npu.errors", "npu.kernels", "processes.npu_users",
]


def default_log_dir() -> str:
    base = os.environ.get("XPU_LOG_DIR")
    if base:
        return base
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(root, "XPUObserver", "logs")


class MetricsRecorder:
    def __init__(self, bus: Any, log_dir: Optional[str] = None,
                 columns: Optional[list[str]] = None, rotate_daily: bool = True) -> None:
        self.bus = bus
        self.dir = log_dir or default_log_dir()
        self.columns = columns or COLUMNS
        self.rotate_daily = rotate_daily
        self.path: Optional[str] = None
        self.rows = 0
        self._day = ""
        self._fh = None
        self._w = None
        self._lock = threading.Lock()

    def start(self) -> str:
        os.makedirs(self.dir, exist_ok=True)
        self._open(time.strftime("%Y%m%d"))
        self.bus.subscribe("metrics", self._on_metrics)
        return self.path or ""

    def _open(self, day: str) -> None:
        path = os.path.join(self.dir, f"metrics_{day}.csv")
        new = not os.path.exists(path)
        self._fh = open(path, "a", newline="", encoding="utf-8")
        self._w = csv.writer(self._fh)
        if new:
            self._w.writerow(["ts_iso", "ts"] + self.columns)
        self.path = path
        self._day = day

    @staticmethod
    def _val(snap: Any, name: str) -> Any:
        m = snap.metrics.get(name)
        if m is None or m.value is None:
            return ""
        return m.value

    def _on_metrics(self, snap: Any) -> None:
        with self._lock:
            if self._w is None:
                return
            try:
                if self.rotate_daily:
                    day = time.strftime("%Y%m%d")
                    if day != self._day:
                        if self._fh:
                            self._fh.close()
                        self._open(day)
                row = [time.strftime("%Y-%m-%d %H:%M:%S"), round(snap.ts, 3)]
                row += [self._val(snap, c) for c in self.columns]
                self._w.writerow(row)
                self._fh.flush()
                self.rows += 1
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:
        with self._lock:
            if self._fh:
                try:
                    self._fh.close()
                except Exception:  # noqa: BLE001
                    pass
            self._fh = None
            self._w = None

    def status(self) -> dict[str, Any]:
        return {"path": self.path, "rows": self.rows, "dir": self.dir}