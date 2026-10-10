"""Processes provider — merge psutil + nvidia-smi compute-apps + XRT contexts by PID.

DLL inspection is limited to processes that actually use the NPU (cost is bounded).
"""
from __future__ import annotations

import ctypes
import os
from typing import Any, Optional

import psutil

from ..core import util
from ..core.metrics import Metric

_INFERENCE_HINTS = ("flm", "llama", "ggml", "qwen", "onnx", "directml", "lmstudio", "ollama",
                    "npu", "gemm", "mha", "dequant", "vitis")


def _proc_kind(name: str) -> str:
    low = name.lower()
    if any(k in low for k in _INFERENCE_HINTS):
        return "inference"
    if "nvidia" in low or "amd" in low or "igfx" in low:
        return "driver"
    return "other"


def _proc_modules(pid: int) -> list[str]:
    """DLL basenames of a process (Windows, ctypes). Returns [] on failure."""
    out: list[str] = []
    try:
        k32 = ctypes.windll.kernel32
        hproc = k32.OpenProcess(0x1040 | 0x0010, False, pid)  # QUERY_INFORMATION|VM_READ
        if not hproc:
            return out
        try:
            bufsz = 1024
            mods = (ctypes.c_void_p * bufsz)()
            needed = ctypes.c_ulong(0)
            if k32.EnumProcessModulesEx(hproc, mods, ctypes.sizeof(mods),
                                        ctypes.byref(needed), 0x03):
                count = min(bufsz, needed.value // ctypes.sizeof(ctypes.c_void_p))
                for i in range(count):
                    buf = ctypes.create_unicode_buffer(260)
                    if k32.GetModuleFileNameExW(hproc, mods[i], buf, 260):
                        out.append(os.path.basename(buf.value))
        finally:
            k32.CloseHandle(hproc)
    except Exception:  # noqa: BLE001
        pass
    return out


def collect(xrt_raw: Optional[dict] = None) -> tuple[list[Metric], dict[str, Any]]:
    ctxs = (xrt_raw or {}).get("contexts", [])
    ctx_by_pid: dict[int, dict[str, Any]] = {}
    for c in ctxs:
        pid = c.get("pid")
        if not pid:
            continue
        pid = int(pid)
        e = ctx_by_pid.setdefault(pid, {"ctx": 0, "tps": 0.0, "mem_mb": 0.0})
        e["ctx"] += 1
        e["tps"] += float(c.get("rate", 0.0) or c.get("delta", 0.0) or 0.0)
        mb = (c.get("mem_kb") or 0) / 1024.0
        if 0 < mb < 32768:
            e["mem_mb"] = max(e["mem_mb"], mb)
    npu_pids = set(ctx_by_pid)
    # nvidia-smi compute apps (GPU mem per PID)
    gpu_mem: dict[int, float] = {}
    nv = util.find_nvidia_smi()
    if nv:
        rc, out = util.run([nv, "--query-compute-apps=pid,used_memory",
                            "--format=csv,noheader,nounits"], timeout=4)
        if rc == 0:
            for line in out.splitlines():
                p = [x.strip() for x in line.split(",")]
                if len(p) >= 2:
                    try:
                        gpu_mem[int(p[0])] = float(p[1])
                    except Exception:  # noqa: BLE001
                        pass
    procs = []
    try:
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
            try:
                info = p.info
                pid = info.get("pid")
                if not pid:
                    continue
                mem = info.get("memory_info")
                name = (info.get("name") or "?")
                is_npu = pid in npu_pids
                dlls = _proc_modules(pid) if is_npu else []
                procs.append({
                    "pid": pid, "name": name, "kind": _proc_kind(name),
                    "cpu_pct": float(info.get("cpu_percent") or 0.0),
                    "ram_mb": round((mem.rss if mem else 0) / (1024 * 1024), 1),
                    "gpu_mem_mb": gpu_mem.get(pid, 0.0),
                    "npu_ctx": ctx_by_pid.get(pid, {}).get("ctx", 0),
                    "npu_tps": round(ctx_by_pid.get(pid, {}).get("tps", 0.0), 2),
                    "npu_mem_mb": round(ctx_by_pid.get(pid, {}).get("mem_mb", 0.0), 1),
                    "dlls": dlls,
                })
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    procs.sort(key=lambda x: -(x["npu_ctx"] + x.get("npu_tps", 0)))
    m = [Metric("processes.count", float(len(procs)), unit="", source="psutil"),
         Metric("processes.npu_users", float(len([p for p in procs if p["npu_ctx"]])),
                unit="", source="xrt-smi+psutil")]
    return m, {"processes": procs[:200]}