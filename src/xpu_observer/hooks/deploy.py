"""Deploy hooks next to a target executable, with backup/rollback.

The hook binaries are USER-PROVIDED (never bundled): this module only wires them.
- `NpuHook.dll` / `npu_monitor.dll`: instrumentation DLLs to be loaded by/injected
  into the target process (MinHook on xrt_coreutil; logs under `<cwd>/logs/`).
- `xrt_proxy.dll`: an XRT proxy that must REPLACE `xrt_coreutil.dll` in the target's
  directory (DLL search order); it loads the real one as `xrt_coreutil_orig.dll`.

Governance: deployment is explicit and reversible; nothing is injected automatically.
"""
from __future__ import annotations

import os
import shutil
import time
from typing import Any, Optional

NPUHOOK = "NpuHook.dll"
MONITOR = "npu_monitor.dll"
XRT_PROXY = "xrt_proxy.dll"
XRT_REAL = "xrt_coreutil.dll"
XRT_ORIG = "xrt_coreutil_orig.dll"


def _manifest_path(target_dir: str) -> str:
    return os.path.join(target_dir, ".xpu_hooks_manifest.json")


def deploy_hooks(target_dir: str, hooks_dir: str, *, npuhook: bool = True,
                 monitor: bool = True, xrt_proxy: bool = False,
                 log_dir: Optional[str] = None) -> dict[str, Any]:
    """Copy requested hook artifacts into `target_dir`. Returns a manifest."""
    import json
    os.makedirs(target_dir, exist_ok=True)
    actions: list[dict[str, str]] = []

    def _copy(src_name: str, dst_name: Optional[str] = None) -> None:
        src = os.path.join(hooks_dir, src_name)
        dst = os.path.join(target_dir, dst_name or src_name)
        if not os.path.isfile(src):
            actions.append({"op": "missing", "src": src, "dst": dst})
            return
        backup = ""
        if os.path.isfile(dst):
            backup = dst + f".bak_{int(time.time())}"
            shutil.copy2(dst, backup)
        shutil.copy2(src, dst)
        actions.append({"op": "copied", "src": src, "dst": dst, "backup": backup})

    if npuhook:
        _copy(NPUHOOK)
    if monitor:
        _copy(MONITOR)
    if xrt_proxy:
        # proxy replaces the real DLL; back up the system/real one too
        sysroot = os.environ.get("SystemRoot", r"C:\Windows")
        real = os.path.join(sysroot, "System32", XRT_REAL)
        if os.path.isfile(real):
            _copy_src(real, os.path.join(target_dir, XRT_ORIG), actions)
        _copy(XRT_PROXY, XRT_REAL)   # xrt_proxy.dll -> xrt_coreutil.dll

    manifest = {"target_dir": target_dir, "hooks_dir": hooks_dir,
                "actions": actions, "ts": time.time(),
                "log_dir_hint": log_dir or os.path.join(target_dir, "logs")}
    with open(_manifest_path(target_dir), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return manifest


def _copy_src(src: str, dst: str, actions: list[dict[str, str]]) -> None:
    shutil.copy2(src, dst)
    actions.append({"op": "copied", "src": src, "dst": dst, "backup": ""})


def rollback(target_dir: str) -> dict[str, Any]:
    """Undo a deployment using its manifest: restore backups, remove copied files."""
    import json
    mp = _manifest_path(target_dir)
    if not os.path.isfile(mp):
        return {"ok": False, "error": "no manifest", "path": mp}
    with open(mp, encoding="utf-8") as fh:
        manifest = json.load(fh)
    undone = []
    for a in manifest.get("actions", []):
        if a.get("op") != "copied":
            continue
        dst = a["dst"]
        if a.get("backup") and os.path.isfile(a["backup"]):
            shutil.copy2(a["backup"], dst)
        elif os.path.isfile(dst):
            try:
                os.remove(dst)
            except Exception:  # noqa: BLE001
                pass
        undone.append(dst)
    os.remove(mp)
    return {"ok": True, "restored": undone}