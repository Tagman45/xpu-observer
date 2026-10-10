"""JSON helpers — write snapshot / history as JSON text."""
from __future__ import annotations

import json
from typing import Any


def dump(obj: Any, indent: int = 2) -> str:
    return json.dumps(obj, indent=indent, default=str)