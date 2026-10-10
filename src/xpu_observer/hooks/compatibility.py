"""Compatibility check — conservative by design.

An unknown signature does NOT prove absence; absence of a runtime detection DOES
prevent us from claiming compatibility.
"""
from __future__ import annotations

from typing import Any, Optional

from . import states
from .registry import Hook


def check(hook: Hook, detected_runtimes: Optional[list[str]] = None,
          target_present: Optional[bool] = None) -> dict[str, Any]:
    runtimes = detected_runtimes or []
    if target_present is None:
        target_present = any(r.endswith(hook.target_dll) for r in runtimes)
    runtime_ok = hook.runtime in runtimes or hook.runtime == "any"
    if runtime_ok and target_present:
        return {"compatible": True, "state": states.HOOK_DETECTED,
                "reason": "runtime et DLL cible presentes"}
    if runtime_ok and not target_present:
        return {"compatible": True, "state": states.NOT_INSTALLED,
                "reason": "runtime present, DLL cible non injectee (proposable)"}
    if not runtimes:
        return {"compatible": False, "state": states.UNKNOWN,
                "reason": "aucun runtime detecte: compatibilite inconnue"}
    return {"compatible": False, "state": states.INCOMPATIBLE,
            "reason": f"runtime '{hook.runtime}' non detecte parmi {runtimes}"}