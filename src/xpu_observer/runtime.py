"""App runtime — wires collector, scheduler, capabilities and optional subsystems
(API, MCP, hooks, UI). One object handed to every consumer.
"""
from __future__ import annotations

import threading
from typing import Any, Optional

from .core.capabilities import detect as detect_capabilities
from .core.collector import Collector
from .core.event_bus import EventBus
from .core.recorder import MetricsRecorder
from .core.scheduler import Scheduler


class App:
    def __init__(self, bus: Optional[EventBus] = None, log_dir: Optional[str] = None) -> None:
        self.bus = bus or EventBus()
        self.collector = Collector(self.bus)
        self.scheduler = Scheduler(self.collector)
        self.recorder = MetricsRecorder(self.bus, log_dir=log_dir)
        self._caps: Optional[dict[str, Any]] = None
        self._hooks: Any = None
        self._session_lock = threading.Lock()

    @property
    def caps(self) -> dict[str, Any]:
        if self._caps is None:
            self._caps = detect_capabilities()
        return self._caps

    def refresh_caps(self) -> None:
        detect_capabilities.cache_clear()
        self._caps = detect_capabilities()

    @property
    def hooks(self):
        """Lazy hooks manager (hooks.manager.HookManager); None if not yet built."""
        if self._hooks is None:
            try:
                from .hooks.manager import HookManager  # noqa: PLC0415
                self._hooks = HookManager()
            except Exception:  # noqa: BLE001
                self._hooks = None
        return self._hooks

    def start(self, collect_immediately: bool = True) -> None:
        try:
            self.recorder.start()          # disk logging first — independent of UI
        except Exception:  # noqa: BLE001
            pass
        self.scheduler.start()
        if collect_immediately:
            try:
                self.collector.collect_once(force_slow=True)
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:
        self.scheduler.stop()
        try:
            self.recorder.stop()
        except Exception:  # noqa: BLE001
            pass

    def snapshot_dict(self) -> dict[str, Any]:
        return self.collector.snap().as_dict()