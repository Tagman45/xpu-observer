"""GPU provider — multi-GPU NVIDIA via nvidia-smi (slow); PDH supplies iGPU/dGPU loads.

Supports 0..N discrete NVIDIA GPUs plus integrated AMD via CIM capabilities + PDH.
Intel iGPU is reported by CIM (no perf counters beyond PDH load).
"""
from __future__ import annotations

from typing import Any

from ..core import util
from ..core.metrics import Metric, mk


def nvidia_gpus() -> list[dict[str, Any]]:
    path = util.find_nvidia_smi()
    if not path:
        return []
    rc, out = util.run([
        path, "--query-gpu=index,name,utilization.gpu,temperature.gpu,memory.used,"
               "memory.total,power.draw,display_active",
        "--format=csv,noheader,nounits"], timeout=6)
    if rc != 0:
        return []
    gpus = []
    for line in out.splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) < 8:
            continue
        def f(x, d=0.0):
            try:
                return float(x)
            except Exception:  # noqa: BLE001
                return d
        gpus.append({
            "index": p[0], "name": p[1], "load_pct": f(p[2]),
            "temp_c": f(p[3]), "mem_used_mb": f(p[4]), "mem_total_mb": f(p[5]),
            "power_w": f(p[6], 0.0), "display_active": p[7],
        })
    return gpus


def collect() -> tuple[list[Metric], dict[str, Any]]:
    gpus = nvidia_gpus()
    m: list[Metric] = []
    for g in gpus:
        idx = g["index"]
        m.append(mk(f"gpu.{idx}.name", None, "", source="nvidia-smi", note=g["name"]))
        m.append(mk(f"gpu.{idx}.load_pct", g["load_pct"], "%", source="nvidia-smi"))
        m.append(mk(f"gpu.{idx}.temp_c", g["temp_c"], "C", source="nvidia-smi"))
        m.append(mk(f"gpu.{idx}.mem_used_mb", g["mem_used_mb"], "MB", source="nvidia-smi"))
        m.append(mk(f"gpu.{idx}.mem_total_mb", g["mem_total_mb"], "MB", source="nvidia-smi"))
        m.append(mk(f"gpu.{idx}.power_w", g["power_w"], "W", source="nvidia-smi"))
    if not gpus:
        m.append(Metric("gpu.nvidia", None, source="nvidia-smi",
                        available=False, note="no NVIDIA GPU / nvidia-smi absent"))
    return m, {"gpus": gpus}