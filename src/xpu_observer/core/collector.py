"""Collector — runs providers once per pass and keeps the latest consistent snapshot.

The snapshot is the single source of truth for UI, API, MCP and exporters. History is
bounded and stores metric values only (raw structured data is not retained in history
to keep memory low).
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
        self._last_run: dict[str, float] = {}

    def collect_once(self, force_slow: bool = False) -> Snapshot:
        snap = Snapshot()
        raw_ctx: dict[str, Any] = {}
        self._cycle += 1
        fast = [n for n, (c, _) in providers.REGISTRY.items() if c == "fast"]
        for name in fast:
            try:
                cost, fn = providers.get(name)
                m, raw = fn()
                snap.add_all(m)
                raw_ctx[name] = raw
            except Exception as exc:  # noqa: BLE001
                snap.add(Metric(f"{name}.error", None, source=name, available=False,
                                validity="error", note=str(exc)))
        slow = bool(self._cycle % 4 == 0) or force_slow
        if slow:
            for name in SLOW_ORDER:
                try:
                    cost, fn = providers.get(name)
                    # processes needs xrt contexts for NPU attribution
                    if name == "processes":
                        xrt_raw = raw_ctx.get("npu", {}).get("xrt")
                        m, raw = fn(xrt_raw)
                    else:
                        m, raw = fn()
                    snap.add_all(m)
                    raw_ctx[name] = raw
                except Exception as exc:  # noqa: BLE001
                    snap.add(Metric(f"{name}.error", None, source=name, available=False,
                                    validity="error", note=str(exc)))
        snap.raw = raw_ctx
        snap.ts = time.time()
        with self._lock:
            self.snapshot = snap
            self.history.append({"ts": snap.ts,
                                 "metrics": {k: v.as_dict() for k, v in snap.metrics.items()}})
        self.bus.publish("metrics", snap)
        return snap

    def snap(self) -> Snapshot:
        with self._lock:
            s = self.snapshot
            return Snapshot(ts=s.ts, metrics=dict(s.metrics), raw=dict(s.raw))

    def history_list(self, max_items: Optional[int] = None) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self.history)
        return items[-max_items:] if max_items else items