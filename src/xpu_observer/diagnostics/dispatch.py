"""Dispatch analysis — read the snapshot's NPU metrics and qualify activity."""
from __future__ import annotations

from typing import Any

from ..core.metrics import Snapshot


def analyze(snap: Snapshot) -> dict[str, Any]:
    m = snap.metrics
    def v(key):
        return (m.get(key).value if m.get(key) else None)
    disp = v("npu.dispatch_s") or 0.0
    state = v("npu.display")
    errors = v("npu.errors") or 0
    fail = v("npu.fail_rate_pct") or 0.0
    ctx = v("npu.ctx_count") or 0
    if disp <= 0:
        verdict = "idle" if state in ("IDLE",) else "unknown"
    elif errors or fail > 1:
        verdict = "errors_or_high_fail"
    else:
        verdict = "dispatching"
    return {
        "state": state, "dispatch_s": disp, "ctx_count": ctx,
        "errors": errors, "fail_rate_pct": fail,
        "verdict": verdict,
        "note": "dispatches are XRT-smi submissions; not equal to physical occupancy",
    }