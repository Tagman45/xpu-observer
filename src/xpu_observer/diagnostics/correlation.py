"""Temporal correlation of inference events, one monotonic timeline.

Contract: only events actually observed are placed; every missing step stays
explicitly UNKNOWN. Never interpolate.
"""
from __future__ import annotations

import time
from typing import Any, Optional

STEP_ORDER = ["TOKEN_BEGIN", "CPU_PREPROCESS", "XRT_SUBMIT", "BUFFER_SYNC",
              "NPU_DISPATCH", "NPU_COMPLETION", "TOKEN_END"]


class Timeline:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def add(self, step: str, ts: float, dll: str = "", detail: str = "") -> None:
        self.events.append({"step": step, "ts_m": ts, "dll": dll, "detail": detail})

    def render(self) -> list[dict[str, Any]]:
        """Annotate each step as PRESENT or UNKNOWN_ABSENT based on what we saw."""
        seen = {e["step"] for e in self.events}
        out = []
        for step in STEP_ORDER:
            if step in seen:
                ev = next(e for e in self.events if e["step"] == step)
                out.append({"step": step, "present": True, "ts_m": ev["ts_m"],
                            "dll": ev.get("dll"), "detail": ev.get("detail")})
            else:
                out.append({"step": step, "present": False,
                            "ts_m": None, "detail": "non observe (inconnu explicite)"})
        return out


def timeline_from_metrics(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Best-effort: NPU_DISPATCH accepted only when there is observable activity
    (dispatches/s > 0); everything else is UNKNOWN unless a dedicated trace exists.
    """
    tl = Timeline()
    last_disp = 0.0
    for it in history:
        met = it.get("metrics") or {}
        d = (met.get("npu.dispatch_s") or {}).get("value", 0.0)
        if d and d > 0:
            last_disp = d
    if last_disp > 0:
        tl.add("NPU_DISPATCH", time.monotonic(), dll="xrt", detail=f"dispatch_s={last_disp:.1f}")
    return tl.render()