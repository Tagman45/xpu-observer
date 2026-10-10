"""Inject a user-provided hook DLL into a process (CreateRemoteThread + LoadLibraryA).

Governed: explicit call only, never automatic. Intended for the user's own hook DLLs
(e.g. NpuHook.dll) on a target the user started. Returns a status dict.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Any

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenProcess.restype = wintypes.HANDLE
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.VirtualAllocEx.restype = wintypes.LPVOID
_k32.VirtualAllocEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t,
                                wintypes.DWORD, wintypes.DWORD]
_k32.WriteProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.LPCVOID,
                                    ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
_k32.GetProcAddress.restype = wintypes.LPVOID
_k32.GetProcAddress.argtypes = [wintypes.HMODULE, wintypes.LPCSTR]
_k32.GetModuleHandleW.restype = wintypes.HMODULE
_k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_k32.CreateRemoteThread.restype = wintypes.HANDLE
_k32.CreateRemoteThread.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t,
                                    wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD,
                                    ctypes.POINTER(wintypes.DWORD)]
_k32.VirtualFreeEx.restype = wintypes.BOOL
_k32.VirtualFreeEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t,
                               wintypes.DWORD]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_k32.GetExitCodeThread.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]

PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT_RESERVE = 0x3000
PAGE_READWRITE = 0x40
MEM_RELEASE = 0x8000


def inject(pid: int, dll_path: str) -> dict[str, Any]:
    dll = os.path.abspath(dll_path)
    res: dict[str, Any] = {"ok": False, "pid": pid, "dll": dll}
    if not os.path.isfile(dll):
        res["error"] = f"DLL not found: {dll}"
        return res
    h = _k32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h:
        res["error"] = f"OpenProcess failed err={ctypes.get_last_error()} (elevation required?)"
        return res
    try:
        data = dll.encode("mbcs") + b"\x00"
        remote = _k32.VirtualAllocEx(h, None, len(data), MEM_COMMIT_RESERVE, PAGE_READWRITE)
        if not remote:
            res["error"] = f"VirtualAllocEx failed err={ctypes.get_last_error()}"
            return res
        written = ctypes.c_size_t(0)
        if not _k32.WriteProcessMemory(h, remote, data, len(data), ctypes.byref(written)):
            res["error"] = f"WriteProcessMemory failed err={ctypes.get_last_error()}"
            _k32.VirtualFreeEx(h, remote, 0, MEM_RELEASE)
            return res
        loadlib = _k32.GetProcAddress(_k32.GetModuleHandleW("kernel32.dll"), b"LoadLibraryA")
        if not loadlib:
            res["error"] = "LoadLibraryA not found"
            return res
        tid = wintypes.DWORD(0)
        t = _k32.CreateRemoteThread(h, None, 0, loadlib, remote, 0, ctypes.byref(tid))
        if not t:
            res["error"] = f"CreateRemoteThread failed err={ctypes.get_last_error()}"
            _k32.VirtualFreeEx(h, remote, 0, MEM_RELEASE)
            return res
        _k32.WaitForSingleObject(t, 10000)
        code = wintypes.DWORD(0)
        _k32.GetExitCodeThread(t, ctypes.byref(code))
        _k32.CloseHandle(t)
        _k32.VirtualFreeEx(h, remote, 0, MEM_RELEASE)
        res["module_base"] = hex(code.value)
        res["ok"] = bool(code.value)
        if not res["ok"]:
            res["error"] = f"LoadLibraryA returned 0x{code.value:X}"
        return res
    finally:
        _k32.CloseHandle(h)