"""HookManager — discovery, state tracking, confirmation queue. NO automatic injection.

Activation flows through `pending` confirmation requests that the UI must display and
the user must approve. The manager itself never loads a DLL.
"""
from __future__ import annotations

import time
from typing import Any

import psutil

from . import states
from .compatibility import check as compat_check
from .registry import CATALOG, Hook, find as find_hook, RUNTIME_DLLS
from . import discovery

_CANDIDATE_HINTS = ("llama", "flm", "ggml", "onnx", "qwen", "ollama", "lm-studio",
                    "lm studio", "python", "node", "fastflow", "vitis", "npu")


class HookManager:
    def __init__(self) -> None:
        self.catalog = CATALOG
        self.pending: list[dict[str, Any]] = []
        self._state: dict[str, str] = {h.id: states.NOT_INSTALLED for h in CATALOG}
        self._reasons: dict[str, str] = {}
        self._runtimes: dict[str, list[int]] = {}   # runtime -> pids
        self._last_detect_ts = 0.0

    # ------------------------------------------------------------------ detection
    def _scan(self) -> tuple[dict[str, list[int]], set[str]]:
        runtimes: dict[str, list[int]] = {}
        modules_seen: set[str] = set()
        checked = 0
        try:
            for p in psutil.process_iter(["pid", "name"]):
                name = (p.info.get("name") or "").lower()
                if not any(h in name for h in _CANDIDATE_HINTS):
                    continue
                pid = p.info.get("pid")
                if not pid:
                    continue
                checked += 1
                if checked > 40:
                    break
                try:
                    mods = discovery.modules_of(pid)
                except Exception:  # noqa: BLE001
                    continue
                modules_seen.update(m.lower() for m in mods)
                for runtime, pats in RUNTIME_DLLS.items():
                    if any(_match(pats, m.lower()) for m in mods):
                        runtimes.setdefault(runtime, []).append(pid)
        except Exception:  # noqa: BLE001
            pass
        return runtimes, modules_seen

    def detect(self) -> dict[str, Any]:
        self._runtimes, _seen = self._scan()
        self._modules_seen = {m.lower() for m in _seen}
        for h in self.catalog:
            runtimes = list(self._runtimes)
            target_present = (
                h.target_dll not in ("multi", "runtime", "<runtime npa>")
                and h.target_dll.lower() in self._modules_seen)
            res = compat_check(h, detected_runtimes=runtimes, target_present=target_present)
            self._state[h.id] = res["state"]
            self._reasons[h.id] = res["reason"]
        self._last_detect_ts = time.time()
        return {"detected_runtimes": self._runtimes,
                "checked_at": self._last_detect_ts}

    # ------------------------------------------------------------------ queries
    def status(self) -> dict[str, Any]:
        return {"hooks": [
            {"id": h.id, "name": h.name, "state": self._state.get(h.id),
             "target_dll": h.target_dll, "runtime": h.runtime,
             "reason": self._reasons.get(h.id, "")}
            for h in self.catalog],
            "detected_runtimes": {k: len(v) for k, v in self._runtimes.items()},
            "pending": len(self.pending),
            "last_detect_ts": self._last_detect_ts}

    def available(self) -> list[dict[str, Any]]:
        return [h.as_dict() for h in self.catalog
                if self._state.get(h.id) in (states.NOT_INSTALLED, states.DLL_PRESENT)]

    def compatibility(self, hook_id: str) -> dict[str, Any]:
        h = find_hook(hook_id)
        if h is None:
            return {"error": f"hook inconnu: {hook_id}",
                    "known": [x.id for x in self.catalog]}
        if not self._runtimes:
            self.detect()
        return compat_check(h, detected_runtimes=list(self._runtimes))

    def events(self, hook_id: str) -> dict[str, Any]:
        h = find_hook(hook_id)
        return {"hook": hook_id, "state": self._state.get(hook_id),
                "events": [], "note": "aucun capteur actif/verifié — événements inconnus"
                if h else "hook inconnu"}

    def diagnostics(self, hook_id: str) -> dict[str, Any]:
        h = find_hook(hook_id)
        return {"hook": hook_id, "state": self._state.get(hook_id),
                "reason": self._reasons.get(hook_id),
                "verifiable": h.verifiable if h else "",
                "last_detect_ts": self._last_detect_ts}


def _match(patterns: tuple[str, ...], module: str) -> bool:
    low = module.lower()
    return any(p.lower() in low if "*" not in p else
               (low.startswith(p.split("*")[0].lower()) and low.endswith(p.split("*")[-1].lower()))
               for p in patterns)