"""Metric value object.

Every metric carries its provenance and reliability so no consumer can mistake
a WDDM-declared activity for physical silicon occupancy, or a missing value for 0.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# validity states
OK = "ok"
STALE = "stale"
UNAVAILABLE = "unavailable"
ERROR = "error"
ESTIMATED = "estimated"   # heuristic (e.g. tokens/s from dispatches)


@dataclass
class Metric:
    name: str
    value: Optional[float]
    unit: str = ""
    source: str = ""              # e.g. "pdh:GPU Engine", "xrt-smi", "nvidia-smi", "psutil"
    ts: float = field(default_factory=time.time)
    available: bool = True
    validity: str = OK
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def mk(name: str, value: Optional[float], unit: str = "", source: str = "",
       available: bool = True, validity: str = OK, note: str = "") -> Metric:
    if value is None:
        available, validity = False, UNAVAILABLE
    return Metric(name=name, value=value, unit=unit, source=source,
                  available=available, validity=validity, note=note)


def unavailable(name: str, source: str, note: str = "") -> Metric:
    return Metric(name=name, value=None, source=source, available=False,
                  validity=UNAVAILABLE, note=note)


@dataclass
class Snapshot:
    """A consistent read of all providers at one instant."""
    ts: float = field(default_factory=time.time)
    metrics: dict[str, Metric] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)   # structured extra (processes, gpus...)

    def add(self, m: Metric) -> None:
        self.metrics[m.name] = m

    def add_all(self, items: list[Metric]) -> None:
        for m in items:
            self.add(m)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "metrics": {k: v.as_dict() for k, v in self.metrics.items()},
            "raw": self.raw,
        }
