"""Scheduler — background collection loop. Never blocks the UI.

Cadence is coarse by design: fast providers each cycle, slow providers every N cycles.
Costly operations (xrt-smi subprocess, nvidia-smi, DLL scan) are confined to the slow
path so the loop stays light.
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
                slow = (time.monotonic() - self._last_slow >= self._interval * self._slow_every)
                if slow:
                    self._last_slow = time.monotonic()
                self._col.collect_once(force_slow=slow)
            except Exception:  # noqa: BLE001
                pass
            dt = time.monotonic() - t0
            time.sleep(max(0.05, self._interval - dt))