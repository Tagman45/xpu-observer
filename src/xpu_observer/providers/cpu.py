"""CPU provider — psutil (fast)."""
from __future__ import annotations

from typing import Any

import psutil

from ..core.metrics import Metric, mk


def collect() -> tuple[list[Metric], dict[str, Any]]:
    try:
        load = psutil.cpu_percent(interval=None)
    except Exception:  # noqa: BLE001
        load = None
    try:
        per = psutil.cpu_percent(interval=None, percpu=True)
    except Exception:  # noqa: BLE001
        per = []
    freq = None
    try:
        f = psutil.cpu_freq()
        if f:
            freq = f.current
    except Exception:  # noqa: BLE001
        pass
    temp = None
    tmp = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
    for _, entries in tmp.items():
        for e in entries:
            if getattr(e, "current", None):
                temp = e.current
                break
        if temp is not None:
            break
    m = [
        mk("cpu.load_pct", load, "%", source="psutil"),
        mk("cpu.freq_mhz", freq, "MHz", source="psutil"),
        mk("cpu.temp_c", temp, "C", source="psutil:sensors"),
    ]
    raw = {"cpu": {"per_core_pct": per, "count": psutil.cpu_count(), "freq": freq, "temp": temp}}
    return m, raw