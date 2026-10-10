"""Chrome Trace Format / Perfetto export for dispatch spans.

Produces the standard JSON array consumable by chrome://tracing and Perfetto:
  ph 'X' complete events per dispatch (ts/dur in us), plus instruction-cache
  counters as ph 'C' events.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

from ..diagnostics.dispatch_trace import DispatchSpan


def to_chrome_trace(spans: Iterable[DispatchSpan],
                    counters: dict[str, Any] | None = None) -> str:
    events: list[dict[str, Any]] = []
    for sp in spans:
        if sp.dur_ns <= 0:
            continue
        events.append({
            "name": sp.kernel or "(unknown)",
            "ph": "X",                       # complete event
            "ts": sp.start_ns / 1000.0,      # us (chrome convention)
            "dur": sp.dur_ns / 1000.0,
            "pid": sp.pid,
            "tid": sp.tid,
            "cname": _cat(sp),
            "args": {"hwctx_id": sp.hwctx_id, "instruction_hash": sp.instruction_hash,
                     "bo_id": sp.bo_id, "group_id": sp.group_id,
                     "sync_direction": sp.sync_direction, "status": sp.status,
                     "token_id": sp.token_id, "cache": sp.instruction_cache,
                     "breakdown_us": {"submit": round(sp.submit_us, 1),
                                      "wait": round(sp.wait_us, 1),
                                      "npu": round(sp.npu_us, 1),
                                      "sync": round(sp.sync_us, 1),
                                      "host": round(sp.host_us, 1)}},
        })
    if counters:
        ts = events[0]["ts"] if events else 0.0
        for k, v in counters.items():
            events.append({"name": k, "ph": "C", "ts": ts, "pid": 0, "tid": 0,
                           "args": {k: v}})
    return json.dumps(events, indent=2)


def _cat(sp: DispatchSpan) -> str:
    if sp.status and sp.status.lower() not in ("ok", "done", ""):
        return "bad"
    if sp.instruction_cache == "hit":
        return "cq_build_ok"
    if sp.sync_direction in ("pre", "both"):
        return "cq_build_warn"
    return "good"