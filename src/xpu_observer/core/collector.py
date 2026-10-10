"""Collector — one collection pass -> one published Snapshot.

Fast/slow decoupling: cheap providers (cpu/ram/pdh/etw) publish every cycle (~2 s) so
the disk recorder and the UI stay fresh; expensive providers (xrt/gpu/processes, which
can take seconds) run on a separate background pass and are merged in as soon as ready.
The noisy slow pass never blocks the frequent log.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Optional

from .event_bus import EventBus
from .metrics import Metric, Snapshot
from .. import providers

SLOW_ORDER = ["npu", "gpu", "processes"]

HISTORY_MAX = 600


class Collector:
    def __init__(self, bus: Optional[EventBus] = None, history_max: int = HISTORY_MAX) -> None:
        self.bus = bus or EventBus()
        self._lock = threading.Lock()
        self._cycle = 0
        self.snapshot = Snapshot()
        self.history: deque[dict[str, Any]] = deque(maxlen=history_max)
        self._slow_m: list[Metric] = []
        self._slow_raw: dict[str, Any] = {}
        self._slow_busy = False

    # ------------------------------------------------------------------ helpers
    def _run(self, names: list[str], raw_ctx: dict[str, Any]) -> list[Metric]:
        metrics: list[Metric] = []
        for name in names:
            try:
                _cost, fn = providers.get(name)
                if name == "processes":
                    xrt_raw = (raw_ctx.get("npu") or {}).get("xrt")
                    m, raw = fn(xrt_raw)
                else:
                    m, raw = fn()
                metrics += list(m)
                raw_ctx.update(raw or {})   # providers own their top-level keys
            except Exception as exc:  # noqa: BLE001
                metrics.append(Metric(f"{name}.error", None, source=name,
                                      available=False, validity="error", note=str(exc)))
        return metrics

    def _publish(self, fast_m: list[Metric], fast_raw: dict[str, Any]) -> Snapshot:
        with self._lock:
            slow_m = list(self._slow_m)
            slow_raw = dict(self._slow_raw)
        snap = Snapshot()
        snap.add_all(slow_m)          # last known slow data
        snap.add_all(fast_m)          # fresh fast data overrides
        snap.raw = {**slow_raw, **fast_raw}
        snap.ts = time.time()
        with self._lock:
            self.snapshot = snap
            self.history.append({"ts": snap.ts,
                                 "metrics": {k: v.as_dict() for k, v in snap.metrics.items()}})
        self.bus.publish("metrics", snap)
        return snap

    # ------------------------------------------------------------------ passes
    def collect_fast(self) -> Snapshot:
        """Cheap pass only — runs every cycle, never blocked by slow providers."""
        self._cycle += 1
        raw: dict[str, Any] = {}
        fast = [n for n, (c, _) in providers.REGISTRY.items() if c == "fast"]
        m = self._run(fast, raw)
        return self._publish(m, raw)

    def collect_slow(self) -> None:
        """Expensive pass — call from a background thread. Guarded against overlap."""
        if self._slow_busy:
            return
        self._slow_busy = True
        try:
            raw: dict[str, Any] = {}
            m = self._run(SLOW_ORDER, raw)
            with self._lock:
                self._slow_m = m
                self._slow_raw = raw
        finally:
            self._slow_busy = False

    def collect_once(self, force_slow: bool = False) -> Snapshot:
        """Synchronous full pass (tests / --once / one-shot). Fast + optional slow."""
        self._cycle += 1
        raw: dict[str, Any] = {}
        fast = [n for n, (c, _) in providers.REGISTRY.items() if c == "fast"]
        m = self._run(fast, raw)
        if force_slow or self._cycle % 4 == 0:
            slow_raw: dict[str, Any] = {}
            sm = self._run(SLOW_ORDER, slow_raw)
            with self._lock:
                self._slow_m = sm
                self._slow_raw = slow_raw
            raw.update(slow_raw)
        return self._publish(m, raw)

    @property
    def slow_busy(self) -> bool:
        return self._slow_busy

    # ------------------------------------------------------------------ reads
    def snap(self) -> Snapshot:
        with self._lock:
            s = self.snapshot
            return Snapshot(ts=s.ts, metrics=dict(s.metrics), raw=dict(s.raw))

    def history_list(self, max_items: Optional[int] = None) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self.history)
        return items[-max_items:] if max_items else items