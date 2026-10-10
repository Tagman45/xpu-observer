"""Scheduler — background collection loop. Never blocks the UI or the recorder.

Fast providers run every cycle (kept cheap); the expensive slow pass (xrt/gpu/processes,
which can take seconds) runs on its own background thread so the frequent fast publish —
and therefore the disk log — is never delayed by it.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from .collector import Collector


class Scheduler:
    def __init__(self, collector: Collector, fast_interval_s: float = 2.0,
                 slow_every: int = 4) -> None:
        self._col = collector
        self._interval = fast_interval_s
        self._slow_every = slow_every
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._slow_thread: Optional[threading.Thread] = None
        self._last_slow = 0.0

    def start(self) -> "Scheduler":
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="xpu-collect", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _loop(self) -> None:
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                self._col.collect_fast()             # publish fast every cycle
            except Exception:  # noqa: BLE001
                pass
            try:
                due = time.monotonic() - self._last_slow >= self._interval * self._slow_every
                idle = self._slow_thread is None or not self._slow_thread.is_alive()
                if due and idle and not self._stop.is_set():
                    self._last_slow = time.monotonic()
                    self._slow_thread = threading.Thread(
                        target=self._col.collect_slow, name="xpu-slow", daemon=True)
                    self._slow_thread.start()
            except Exception:  # noqa: BLE001
                pass
            dt = time.monotonic() - t0
            time.sleep(max(0.05, self._interval - dt))