"""Provider registry. One collection infrastructure feeds UI/API/MCP/export.

Each provider returns (list[Metric], raw_dict). `cost` groups providers by cadence:
  'fast' runs every cycle, 'slow' runs every N cycles.
"""
from __future__ import annotations

from typing import Any, Callable

from ..core.metrics import Metric  # noqa: F401

ProviderFn = Callable[..., tuple[list[Metric], dict[str, Any]]]

FAST: dict[str, ProviderFn] = {
    "cpu": None,  # cheap but a couple of syscalls; run at medium cadence
}
SLOW: dict[str, ProviderFn] = {}

# Filled below to avoid circular imports at module load.
REGISTRY: dict[str, tuple[str, ProviderFn]] = {}


def _register() -> None:
    from . import cpu, npu, ram
    from . import etw as _etw
    from . import gpu as _gpu
    from . import processes as _procs

    REGISTRY.clear()
    REGISTRY["cpu"] = ("fast", cpu.collect)
    REGISTRY["ram"] = ("fast", ram.collect)
    REGISTRY["npu"] = ("slow", npu.collect)          # xrt subprocess + pdh
    REGISTRY["gpu"] = ("slow", _gpu.collect)         # nvidia-smi subprocess
    REGISTRY["processes"] = ("slow", _procs.collect)
    REGISTRY["etw"] = ("fast", _etw.collect)


def names() -> list[str]:
    if not REGISTRY:
        _register()
    return list(REGISTRY)


def get(name: str) -> tuple[str, ProviderFn]:
    if not REGISTRY:
        _register()
    return REGISTRY[name]