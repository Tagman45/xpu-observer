"""Process module introspection (DLL enumeration)."""
from __future__ import annotations

from ..providers import processes as _procs


def modules_of(pid: int) -> list[str]:
    """DLL basenames loaded by a process. [] on failure/restricted."""
    return _procs._proc_modules(pid)


def has_module(pid: int, module_basename: str) -> bool:
    low = module_basename.lower()
    return any(m.lower() == low for m in modules_of(pid))