"""API exports — CSV and JSON serialization of a snapshot."""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from ..core.metrics import Snapshot

CSV_COLUMNS = ["name", "value", "unit", "source", "ts", "available", "validity", "note"]


def snapshot_to_csv(snap: Snapshot) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    w.writeheader()
    for m in sorted(snap.metrics.values(), key=lambda x: x.name):
        w.writerow({c: getattr(m, c, "") if c != "ts" else round(m.ts, 3)
                    for c in CSV_COLUMNS})
    return buf.getvalue()


def snapshot_to_json(snap: Snapshot, indent: int = 2) -> str:
    return json.dumps(snap.as_dict(), indent=indent)


def history_to_csv(items: list[dict[str, Any]]) -> str:
    """Items are per-cycle {"ts": float, "metrics": {name: metric_dict}}.

    Columns = ts + every metric name (union); cells hold scalar value or blank
    when that metric was not present on that cycle.
    """
    names: list[str] = []
    for it in items:
        for k in (it.get("metrics") or {}):
            if k not in names:
                names.append(k)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ts"] + names)
    for it in items:
        met = it.get("metrics") or {}
        w.writerow([round(it.get("ts", 0), 3)] + [met.get(n, {}).get("value", "") for n in names])
    return buf.getvalue()