"""RAM provider — psutil (fast)."""
from __future__ import annotations

from typing import Any

import psutil

from ..core.metrics import Metric, mk


def collect() -> tuple[list[Metric], dict[str, Any]]:
    try:
        vm = psutil.virtual_memory()
    except Exception:  # noqa: BLE001
        vm = None
    if vm is None:
        return ([Metric("ram.used_gb", None, source="psutil", available=False)],
                {"ram": {}})
    used = vm.used / 1e9
    total = vm.total / 1e9
    m = [
        mk("ram.used_gb", used, "GB", source="psutil"),
        mk("ram.total_gb", total, "GB", source="psutil"),
        mk("ram.pct", vm.percent, "%", source="psutil"),
    ]
    return m, {"ram": {"available_gb": (vm.total - vm.used) / 1e9, "percent": vm.percent}}