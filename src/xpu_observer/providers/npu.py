"""NPU provider — composite of PDH (WDDM load), XRT (contexts/dispatches) and kernel scan.

Aggregates the low-level providers into a single `npu.*` namespace plus a kernel
inventory. Ports the portable parts of `scan_npu_kernels` from the reference app
(no hardcoded paths; env + localappdata only).
"""
from __future__ import annotations

import os
from typing import Any

from ..core.metrics import Metric, mk
from . import pdh, xrt

NODE_KINDS = {"GDN", "flowkv", "gemv", "ffn", "decode_layer", "rms", "ssm", "swiglu"}


def _kernel_dirs() -> list[str]:
    dirs: list[str] = []
    env = os.environ.get("GGML_XDNA_CACHE_DIR", "")
    if env:
        dirs.append(env)
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    dirs += [
        os.path.join(base, "ggml-xdna", "xclbin"),
        os.path.join(base, "xdna2-runtime", "kernels", "npu_kernels_win_8col"),
    ]
    seen: list[str] = []
    for d in dirs:
        if d and os.path.isdir(d) and d not in seen:
            seen.append(d)
    return seen


def scan_kernels() -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for d in _kernel_dirs():
        try:
            for fn in os.listdir(d):
                if not fn.endswith(".xclbin"):
                    continue
                name = fn[:-7]
                found.append({"name": name, "kind": _guess_kind(name),
                              "path": os.path.join(d, fn),
                              "size": os.path.getsize(os.path.join(d, fn))})
        except Exception:  # noqa: BLE001
            continue
    found.sort(key=lambda k: (k["kind"], k["name"]))
    return found


def _guess_kind(name: str) -> str:
    low = name.lower()
    for k in NODE_KINDS:
        if k.lower() in low:
            return k
    if "gemm" in low:
        return "gemm"
    return "unknown"


def collect() -> tuple[list[Metric], dict[str, Any]]:
    pdh_m, pdh_raw = pdh.collect()
    xrt_m, xrt_raw = xrt.collect()
    kernels = scan_kernels()
    metrics = list(pdh_m) + list(xrt_m)
    metrics.append(Metric("npu.kernels", float(len(kernels)), unit="",
                          source="ggml-xdna cache scan"))
    metrics.append(Metric("npu.active", None, unit="", source="composite",
                          available=False,
                          note="activite de type: " + _describe(pdh_raw, xrt_raw)))
    raw = {"npu": {"kernels": kernels, "pdh": pdh_raw.get("pdh"),
                   "xrt": xrt_raw.get("xrt")}}
    return metrics, raw


def _describe(pdh_raw: dict, xrt_raw: dict) -> str:
    parts = []
    p = (pdh_raw.get("pdh") or {})
    if p.get("npu"):
        parts.append("pdh-npu")
    if (xrt_raw.get("xrt") or {}).get("available"):
        parts.append("xrt")
    return "+".join(parts) if parts else "none"