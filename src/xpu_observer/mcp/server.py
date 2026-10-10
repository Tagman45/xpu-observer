"""MCP server over stdio — implements the official MCP transport directly.

Transport: JSON-RPC 2.0 framed with Content-Length headers over stdin/stdout (no SDK
dependency, fully deterministic and testable). Protocol: initialize -> notifications/
initialized -> tools/list -> tools/call.

Security contract:
  * read-only tools only;
  * activation/deactivation NEVER inject — they queue a local confirmation request
    that the GUI must display; MCP gets back a pending status + request id.
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from typing import Any, Callable, Optional

PROTOCOL_VERSION = "2025-06-18"


# --------------------------------------------------------------------------- framing

def _read_frame() -> Optional[str]:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        line = line.decode("latin-1").rstrip("\r\n")
        if not line:
            break
        if ":" in line:
            k, _, v = line.partition(":")
            headers[k.strip().lower()] = v.strip()
    n = int(headers.get("content-length", 0))
    if n <= 0:
        return None
    return sys.stdin.buffer.read(n).decode("utf-8")


def _write_frame(payload: str) -> None:
    body = payload.encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


# --------------------------------------------------------------------------- tools

def _schema(params: list[dict[str, Any]]) -> dict[str, Any]:
    props = {p["name"]: {"type": p.get("type", "string")} for p in params}
    req = [p["name"] for p in params if p.get("required")]
    s: dict[str, Any] = {"type": "object", "properties": props}
    if req:
        s["required"] = req
    return s


def _ok(data: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, indent=2, default=str)}],
            "isError": False}


def _err(msg: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps({"error": msg})}],
            "isError": True}


def _build_tools() -> list[dict[str, Any]]:
    tools: dict[str, tuple[str, list[dict[str, Any]]]] = {
        "get_system_status": ("Overall health: collector, capabilities, uptime", []),
        "get_cpu_metrics": ("CPU load/freq/temp/source", []),
        "get_ram_metrics": ("RAM used/total/percent", []),
        "get_gpu_metrics": ("GPU list with load/temp/mem/power", []),
        "get_npu_metrics": ("NPU composite: PDH load, XRT state, dispatches", []),
        "get_xrt_status": ("xrt-smi device, contexts, columns, platform report", []),
        "get_npu_processes": ("processes using NPU (ctx, tps est, mem, dlls)", []),
        "get_npu_kernels": ("inventaire des .xclbin decouverts", []),
        "get_driver_status": ("services driver NPU (amdxdna...) et status", []),
        "get_metrics_history": ("last N snapshots (metrics only)", [{"name": "limit", "type": "integer"}]),
        "get_capabilities": ("hardware/tools/PDH detectes sur cette machine", []),
        "get_monitor_health": ("health of collectors (errors, last ts)", []),
        "list_process_modules": ("DLL d'un PID (binaire uniquement)", [{"name": "pid", "type": "integer", "required": True}]),
        "detect_existing_hooks": ("scanne les processus pour hooks deja presents", []),
        "get_hook_status": ("etat des hooks du registre (actifs, inactifs)", []),
        "list_available_hooks": ("hooks compatibles candidats", []),
        "check_hook_compatibility": ("verifie compat d'un hook", [{"name": "hook", "type": "string", "required": True}]),
        "get_hook_events": ("evenements captes par un hook actif", [{"name": "hook", "type": "string"}]),
        "get_hook_diagnostics": ("diagnostique de sante d'un hook", [{"name": "hook", "type": "string"}]),
        "analyze_npu_activity": ("qui utilises le NPU + etat global", []),
        "analyze_dispatch_latency": ("analyse dispatches/s et contextes", []),
        "detect_cpu_fallback": ("indique si inference tourne sur CPU (pas NPU)", []),
        "compare_cpu_gpu_npu": ("charge relative CPU/GPU/NPU", []),
        "export_metrics": ("export snapshot", [{"name": "format", "type": "string", "enum": ["json", "csv"]}]),
        "request_hook_activation": ("DEMANDE activation (jamais auto): cree confirmation locale", [{"name": "hook", "type": "string", "required": True}, {"name": "pid", "type": "integer"}]),
        "request_hook_deactivation": ("DEMANDE desactivation (jamais auto)", [{"name": "hook", "type": "string", "required": True}]),
    }
    out = []
    for name, (desc, params) in tools.items():
        out.append({"name": name, "description": desc, "inputSchema": _schema(params)})
    return out


# --------------------------------------------------------------------------- handlers

def _metric_subset(snap: Any, prefix: str) -> dict[str, Any]:
    return {k: v.as_dict() for k, v in snap.metrics.items() if k.startswith(prefix)}


def _handle(app: Any, name: str, args: dict[str, Any]) -> dict[str, Any]:
    snap = app.collector.snap()
    if name == "get_system_status":
        return _ok({"ok": True, "ts": snap.ts,
                    "npu_present": app.caps.get("npu", {}).get("present"),
                    "gpus": [g["name"] for g in app.caps.get("gpus", [])],
                    "xrt": app.caps.get("tools", {}).get("xrt_smi"),
                    "pdh": app.caps.get("pdh"),
                    "collector": {"healthy": not any("error" in k for k in snap.metrics)}})
    if name == "get_cpu_metrics":
        return _ok(_metric_subset(snap, "cpu.") | {"source": "psutil"})
    if name == "get_ram_metrics":
        return _ok(_metric_subset(snap, "ram."))
    if name == "get_gpu_metrics":
        return _ok(_metric_subset(snap, "gpu.") | {"pgpu_load_wddm": _metric_subset(snap, "dgpu.")})
    if name == "get_npu_metrics":
        return _ok(_metric_subset(snap, "npu.") | {"igpu_load_pdh": snap.metrics.get("igpu.load_pct").as_dict() if "igpu.load_pct" in snap.metrics else None})
    if name == "get_xrt_status":
        return _ok((snap.raw.get("npu") or {}).get("xrt") or {})
    if name == "get_npu_processes":
        return _ok({"processes": snap.raw.get("processes", [])})
    if name == "get_npu_kernels":
        return _ok({"kernels": (snap.raw.get("npu") or {}).get("kernels", [])})
    if name == "get_driver_status":
        return _ok(app.caps.get("drivers", {}) | app.caps.get("npu", {}))
    if name == "get_metrics_history":
        n = int(args.get("limit") or 100)
        return _ok({"items": app.collector.history_list(max_items=max(1, min(2000, n)))})
    if name == "get_capabilities":
        return _ok(app.caps)
    if name == "get_monitor_health":
        return _ok({"last_ts": snap.ts, "metric_count": len(snap.metrics),
                    "errors": [k for k in snap.metrics if "error" in k]})
    if name == "list_process_modules":
        pid = int(args.get("pid") or 0)
        if pid <= 0:
            return _err("pid required")
        from .. import providers  # noqa: PLC0415
        from . import discovery as _d  # noqa: PLC0415
        return _ok({"pid": pid, "modules": list(_d.modules_of(pid))})
    if name == "detect_existing_hooks":
        h = app.hooks
        return _ok({"state": "hooks subsystem unavailable"} if h is None else h.detect())
    if name == "get_hook_status":
        h = app.hooks
        return _ok({"state": "hooks subsystem unavailable"} if h is None else h.status())
    if name == "list_available_hooks":
        h = app.hooks
        return _ok({"available": []} if h is None else h.available())
    if name == "check_hook_compatibility":
        h = app.hooks
        return _ok({"error": "hooks unavailable"} if h is None else h.compatibility(str(args.get("hook"))))
    if name == "get_hook_events":
        h = app.hooks
        return _ok({"events": []} if h is None else h.events(str(args.get("hook") or "")))
    if name == "get_hook_diagnostics":
        h = app.hooks
        return _ok({"diagnostics": {}} if h is None else h.diagnostics(str(args.get("hook") or "")))
    if name == "analyze_npu_activity":
        procs = [p for p in snap.raw.get("processes", []) if p.get("npu_ctx")]
        return _ok({"state": snap.metrics.get("npu.display", ).as_dict()["value"] if "npu.display" in snap.metrics else "?",
                    "users": procs})
    if name == "analyze_dispatch_latency":
        return _ok(_metric_subset(snap, "npu.") )
    if name == "detect_cpu_fallback":
        cpu = snap.metrics.get("cpu.load_pct")
        npu_state = snap.metrics.get("npu.display").as_dict().get("value") if "npu.display" in snap.metrics else "?"
        return _ok({"npu_state": npu_state,
                    "npu_active": npu_state != "IDLE" and npu_state != "?",
                    "cpu_load_pct": cpu.as_dict()["value"] if cpu else None,
                    "fallback_possible": npu_state in ("IDLE", "?")})
    if name == "compare_cpu_gpu_npu":
        return _ok({
            "cpu": snap.metrics.get("cpu.load_pct").as_dict() if "cpu.load_pct" in snap.metrics else None,
            "gpu": snap.metrics.get("gpu.0.load_pct").as_dict() if "gpu.0.load_pct" in snap.metrics else None,
            "npu": snap.metrics.get("npu.load_pct").as_dict() if "npu.load_pct" in snap.metrics else None,
        })
    if name == "export_metrics":
        from ..export import csv as _csv  # noqa: PLC0415
        from ..export import json as _json  # noqa: PLC0415
        fmt = args.get("format", "json")
        text = _csv.snapshot_to_csv(snap) if fmt == "csv" else _json.dump(snap.as_dict())
        return {"content": [{"type": "text", "text": text}], "isError": False}
    if name in ("request_hook_activation", "request_hook_deactivation"):
        h = app.hooks
        rid = uuid.uuid4().hex[:8]
        req = {"request_id": rid, "action": "activate" if name.endswith("activation") else "deactivate",
               "hook": args.get("hook"), "pid": args.get("pid"), "ts": time.time(),
               "status": "pending_confirmation"}
        if h is not None:
            h.pending.append(req)
        return _ok({"status": "pending_confirmation", "request_id": rid,
                    "note": "confirmation requise dans l interface; aucune injection automatique"})
    return _err(f"tool '{name}' not implemented")


# --------------------------------------------------------------------------- server

def _reply_ok(request_id: Any, result: Any) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result})


def _reply_err(request_id: Any, code: int, msg: str) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": request_id,
                       "error": {"code": code, "message": msg}})


def run(app: Any) -> None:
    tools = _build_tools()
    while True:
        msg = _read_frame()
        if msg is None:
            return
        try:
            req = json.loads(msg)
        except Exception:  # noqa: BLE001
            _write_frame(_reply_err(None, -32700, "parse error"))
            continue
        method = req.get("method")
        rid = req.get("id")
        params = req.get("params") or {}
        if method == "initialize":
            ver = params.get("protocolVersion") or PROTOCOL_VERSION
            _write_frame(_reply_ok(rid, {
                "protocolVersion": ver,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "xpu-observer", "version": "0.1.0"},
            }))
        elif method == "notifications/initialized":
            continue
        elif method == "ping":
            _write_frame(_reply_ok(rid, {}))
        elif method == "tools/list":
            _write_frame(_reply_ok(rid, {"tools": tools}))
        elif method == "tools/call":
            try:
                result = _handle(app, str(params.get("name")), params.get("arguments") or {})
                _write_frame(_reply_ok(rid, result))
            except Exception as exc:  # noqa: BLE001
                _write_frame(_reply_ok(rid, _err(f"handler error: {exc}")))
        else:
            _write_frame(_reply_err(rid, -32601, f"method not found: {method}"))