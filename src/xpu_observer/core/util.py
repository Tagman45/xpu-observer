"""Portable OS helpers. No hardcoded machine paths; tools are discovered at runtime."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from typing import Optional


def is_windows() -> bool:
    return os.name == "nt"


def mono() -> float:
    """Monotonic clock used everywhere for correlation (never wall clock for deltas)."""
    return time.monotonic()


def run(cmd: list[str], timeout: float = 8.0) -> tuple[int, str]:
    """Run a command, return (returncode, stdout). Never raises on failure."""
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if is_windows() else 0,
        )
        return p.returncode, p.stdout or ""
    except Exception as e:  # noqa: BLE001
        return -1, "" if e else ""


def ps(script: str, timeout: float = 10.0) -> str:
    """Run a PowerShell snippet; returns stdout ('' on any failure). ASCII-only scripts."""
    if not is_windows():
        return ""
    rc, out = run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", script],
        timeout=timeout,
    )
    return out if rc == 0 else ""


def ps_json(script: str, timeout: float = 10.0):
    """Run PowerShell emitting JSON, parse it. Returns None on failure."""
    out = ps(script, timeout=timeout).strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except Exception:  # noqa: BLE001
        return None


def which(*names: str) -> Optional[str]:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def find_xrt_smi() -> Optional[str]:
    """Locate xrt-smi without hardcoding a drive. PATH first, then SystemRoot."""
    p = which("xrt-smi", "xrt-smi.exe")
    if p:
        return p
    if is_windows():
        root = os.environ.get("SystemRoot", r"C:\Windows")
        for cand in (
            os.path.join(root, "System32", "AMD", "xrt-smi.exe"),
            os.path.join(root, "System32", "xrt-smi.exe"),
        ):
            if os.path.isfile(cand):
                return cand
    return None


def find_nvidia_smi() -> Optional[str]:
    p = which("nvidia-smi", "nvidia-smi.exe")
    if p:
        return p
    if is_windows():
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramW6432", r"C:\Program Files")):
            cand = os.path.join(base, "NVIDIA Corporation", "NVSMI", "nvidia-smi.exe")
            if os.path.isfile(cand):
                return cand
    return None
