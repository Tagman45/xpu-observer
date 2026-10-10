"""ETW provider — placeholder (not implemented in V0.1).

Deliberately returns *unavailable* metrics so nothing downstream can mistake the
absence for a measurement. The slot exists to receive a real ETW kernel logger
(AMD XDNA ETW GUIDs) in a later version.
"""
from __future__ import annotations

from typing import Any

from ..core.metrics import Metric


def collect() -> tuple[list[Metric], dict[str, Any]]:
    return ([Metric("etw.status", None, source="etw", available=False,
                    note="ETW provider not implemented in V0.1")],
            {"etw": {"available": False}})