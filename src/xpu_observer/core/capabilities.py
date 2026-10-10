"""Capability detection: what hardware, drivers and tools are present on THIS machine.

Detection is done once and cached. Nothing here is machine-specific: GPUs, NPU and
tools are enumerated at runtime. Absence of a capability is a valid, first-class result.
"""
from __future__ import annotations

import ctypes
import functools
import os
import platform
import shutil
from typing import Any, Optional

from . import util


def _pdh_available() -> bool:
    if not util.is_windows():
        return False
    try:
        q = ctypes.c_void_p(0)
        rc = ctypes.windll.Pdh.PdhOpenQueryW(None, 0, ctypes.byref(q))
        if rc == 0 and q:
            ctypes.windll.Pdh.PdhCloseQuery(q)
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def detect_gpus() -> list[dict[str, Any]]:
    """Enumerate display/compute adapters via CIM (portable, no `wmi` dependency)."""
    gpus: list[dict[str, Any]] = []
    raw = util.ps_json(
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,AdapterCompatibility,PNPDeviceID,DriverVersion,AdapterRAM | "
        "ConvertTo-Json -Compress", timeout=12)
    items = raw if isinstance(raw, list) else ([raw] if raw else [])
    for it in items:
        if not it:
            continue
        pnp = (it.get("PNPDeviceID") or "")
        name = it.get("Name") or "?"
        gpus.append({
            "name": name,
            "vendor": it.get("AdapterCompatibility") or "",
            "pnp_id": pnp,
            "driver_version": it.get("DriverVersion") or "",
            "adapter_ram_mb": round((it.get("AdapterRAM") or 0) / (1024 * 1024), 1)
            if isinstance(it.get("AdapterRAM"), (int, float)) else None,
            "kind": _classify_gpu(name),
        })
    return gpus


def _classify_gpu(name: str) -> str:
    n = name.lower()
    if "nvidia" in n or "geforce" in n or "rtx" in n or "quadro" in n:
        return "discrete"
    if "intel" in n and ("arc" in n):
        return "discrete"
    if "amd" in n or "radeon" in n:
        return "integrated_or_amd"
    return "unknown"


def detect_npu() -> dict[str, Any]:
    """Detect an AMD XDNA/XDNA2 NPU (and leave room for Intel/Qualcomm)."""
    info: dict[str, Any] = {"present": False, "vendor": None, "name": None,
                            "status": None, "instance_id": None, "xrt": None}
    if not util.is_windows():
        return info
    raw = util.ps_json(
        "Get-PnpDevice -Class ComputeAccelerator -ErrorAction SilentlyContinue | "
        "Where-Object { $_.FriendlyName -match 'NPU|XDNA|AI|Accelerator' } | "
        "Select-Object FriendlyName,Status,InstanceId | ConvertTo-Json -Compress",
        timeout=12)
    items = raw if isinstance(raw, list) else ([raw] if raw else [])
    for it in items:
        if not it:
            continue
        fn = (it.get("FriendlyName") or "")
        info.update(present=True, name=fn, status=it.get("Status"),
                    instance_id=it.get("InstanceId"))
        low = fn.lower()
        info["vendor"] = "amd" if ("xdna" in low or "npu" in low or "ryzen" in low) else "unknown"
        break
    xrt = util.find_xrt_smi()
    info["xrt"] = xrt
    return info


def detect_driver_service(names: tuple[str, ...] = ("amdxdna", "amdxnna", "npu")) -> dict[str, Any]:
    """Query SCM for NPU-related kernel drivers (read-only)."""
    out: dict[str, Any] = {}
    for n in names:
        rc, o = util.run(["sc", "query", n], timeout=5)
        out[n] = {"queried": rc == 0, "running": ("RUNNING" in o.upper()) if rc == 0 else False}
    return out


@functools.lru_cache(maxsize=1)
def detect() -> dict[str, Any]:
    """Full capability map. Cached — call detect.cache_clear() to refresh."""
    gpus = detect_gpus()
    npu = detect_npu()
    nv = util.find_nvidia_smi()
    return {
        "os": {
            "platform": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "cpu": {
            "logical_cores": os.cpu_count(),
            "physical_cores": _physical_cores(),
        },
        "gpus": gpus,
        "npu": npu,
        "tools": {
            "xrt_smi": npu.get("xrt"),
            "nvidia_smi": nv,
        },
        "pdh": _pdh_available(),
        "drivers": detect_driver_service(),
    }


def _physical_cores() -> Optional[int]:
    try:
        import psutil  # noqa: PLC0415
        return psutil.cpu_count(logical=False)
    except Exception:  # noqa: BLE001
        return None
