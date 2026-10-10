"""Minimal thread-safe event bus (pub/sub by topic).

Used to fan a single collection pass out to UI, API, MCP and exporters without
duplicating work. Subscribers never block the collector thread.
"""
from __future__ import annotations

import queue
import threading
from collections import defaultdict
from typing import Any, Callable


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[Any], None]]] = defaultdict(list)
        self._queues: dict[str, list[queue.Queue]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, topic: str, fn: Callable[[Any], None]) -> None:
        with self._lock:
            self._subs[topic].append(fn)

    def subscribe_queue(self, topic: str) -> "queue.Queue[Any]":
        q: "queue.Queue[Any]" = queue.Queue(maxsize=256)
        with self._lock:
            self._queues[topic].append(q)
        return q

    def publish(self, topic: str, payload: Any) -> None:
        with self._lock:
            subs = list(self._subs.get(topic, []))
            qs = list(self._queues.get(topic, []))
        for fn in subs:
            try:
                fn(payload)
            except Exception:  # noqa: BLE001
                pass
        for q in qs:
            try:
                q.put_nowait(payload)
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(payload)
                except Exception:  # noqa: BLE001
                    pass
