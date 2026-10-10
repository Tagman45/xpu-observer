# MCP Server Guide

XPU Observer implements the **official Model Context Protocol** over stdio (JSON-RPC 2.0
framed with `Content-Length`), with no SDK dependency.

## Connect a client

```bash
xpu-observer --api --mcp
```

Your MCP client launches the command:

```json
{
  "mcpServers": {
    "xpu-observer": {
      "command": "X:\\path\\to\\xpu-observer\\venv\\Scripts\\python.exe",
      "args": ["-m", "xpu_observer.main", "--mcp"]
    }
  }
}
```

(Add `--api` to also start `http://127.0.0.1:8766`.)

## Read tools

Implemented and hardware-validated where marked:

| Tool | Returns |
|---|---|
| `get_system_status` | collector health, NPU/GPU presence, xrt/pdh |
| `get_cpu_metrics` | load %, freq, temp, source=psutil |
| `get_ram_metrics` | used/total/percent |
| `get_gpu_metrics` | per-GPU load/temp/mem/power |
| `get_npu_metrics` | PDH WDDM load + XRT state/dispatches/kernels |
| `get_xrt_status` | device, contexts, columns, platform report |
| `get_npu_processes` | PID, ctx, est. tps, mem, dlls |
| `get_npu_kernels` | discovered `.xclbin` |
| `get_driver_status` | NPU driver service status |
| `get_metrics_history` | last N snapshots (`limit`) |
| `get_capabilities` | hardware/tools/pdh detected |
| `get_monitor_health` | last ts, error metrics |
| `list_process_modules` | DLLs of a PID (`pid` required) |
| `detect_existing_hooks` | runtime detection scan |
| `get_hook_status` | hook states + pending count |
| `list_available_hooks` | compatible candidates |
| `check_hook_compatibility` | per-hook verdict (`hook`) |
| `get_hook_events` | captured events if a hook is verified active |
| `get_hook_diagnostics` | state, reason, verifiable method |
| `analyze_npu_activity` | who uses the NPU + global state |
| `analyze_dispatch_latency` | snapshot NPU metrics, or `path`=trace → per-dispatch verdict |
| `get_dispatch_trace` | ingest trace (`path`), return stats + span timeline (`limit`) |
| `trace_cache_stats` | instruction cache hits/misses + BO realloc/reuse counts |
| `export_trace` | `path` + `format=chrome` → Chrome Trace / Perfetto JSON |
| `detect_cpu_fallback` | is NPU idle while inference may run on CPU |
| `compare_cpu_gpu_npu` | relative loads |
| `export_metrics` | snapshot as `json` or `csv` |

Every metric carries: `value, unit, source, ts, available, validity, note`.

## Controlled actions (never auto-inject)

| Tool | Effect |
|---|---|
| `request_hook_activation` | queues `{action, hook, pid}` in the GUI pending list → `status: pending_confirmation` |
| `request_hook_deactivation` | same, for deactivation |

No MCP tool loads an arbitrary DLL or injects into a non-authorized PID. Activation is
a documented workflow: the UI displays the request, the user approves, and only then a
user-supplied, approved DLL may be provided through the same flow.

## Example (hand-rolled client)

```python
import json, subprocess, sys

def frame(o):
    b = json.dumps(o).encode(); return b"Content-Length: %d\r\n\r\n%s" % (len(b), b)

p = subprocess.Popen([sys.executable, "-m", "xpu_observer.main", "--mcp"],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     env={**__import__("os").environ, "PYTHONPATH": "src"})
for req in [
    {"jsonrpc":"2.0","id":1,"method":"initialize",
     "params":{"protocolVersion":"2025-06-18","capabilities":{}}},
    {"jsonrpc":"2.0","method":"notifications/initialized","params":{}},
    {"jsonrpc":"2.0","id":2,"method":"tools/call",
     "params":{"name":"get_npu_metrics","arguments":{}}},
]:
    p.stdin.write(frame(req)); p.stdin.flush()
p.kill()
```

Protocol: `initialize` → `notifications/initialized` → `tools/list` / `tools/call`.
Unknown methods answer JSON-RPC `-32601`.