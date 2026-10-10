"""Hook verifier — confirm a hook is actually running (never infer from presence)."""
from __future__ import annotations

from typing import Any

from . import discovery
from .registry import Hook


def verify_hook(hook: Hook, pid: int) -> dict[str, Any]:
    """Best-effort runtime verification of an active hook.

    Returns verifiable status; for generic hooks (multi-DLL, env-based) only a
    positive module check is possible, anything else is flagged UNKNOWN.
    """
    if not pid:
        return {"verified": False, "state": "UNKNOWN",
                "reason": "pid manquant"}
    if hook.target_dll in ("multi", "runtime", "<runtime npa>"):
        return {"verified": None, "state": "UNKNOWN",
                "reason": "cible generique: verification specifique a l instrument installé"}
    try:
        present = discovery.has_module(pid, hook.target_dll)
    except Exception as exc:  # noqa: BLE001
        return {"verified": False, "state": "UNKNOWN", "reason": f"erreur: {exc}"}
    if present:
        return {"verified": True, "state": "HOOK_ACTIVE",
                "reason": f"{hook.target_dll} charge dans pid {pid}"}
    return {"verified": False, "state": "NOT_INSTALLED",
            "reason": f"{hook.target_dll} absent de pid {pid}"}