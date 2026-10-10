"""Ctrlcode dump reader — counts/sizes of TXN ctrlcode files.

Accepts an explicit directory (never hardcoded). File naming is runtime-specific;
only size distribution is analysed here (op mapping is runtime-specific, left to
plugins). Missing directory => empty, valid result.
"""
from __future__ import annotations

import glob
import os
from typing import Any, Optional


def scan_ctrlcodes(directory: Optional[str]) -> dict[str, Any]:
    if not directory or not os.path.isdir(directory):
        return {"dir": directory, "files": 0, "total_bytes": 0, "sizes": []}
    sizes: list[tuple[str, int]] = []
    total = 0
    for p in glob.glob(os.path.join(directory, "*")):
        try:
            if os.path.isfile(p):
                sz = os.path.getsize(p)
                sizes.append((os.path.basename(p), sz))
                total += sz
        except Exception:  # noqa: BLE001
            continue
    sizes.sort(key=lambda x: -x[1])
    return {"dir": directory, "files": len(sizes), "total_bytes": total,
            "sizes": sizes[:200]}