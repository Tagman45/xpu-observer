# XPU Observer

Universal **Windows CPU / GPU / NPU monitor** + **DLL hook manager** + **MCP server**,
designed for local AI runtime development. Portable, lightweight, open source, and
independent of any specific laptop (no Acer / Nitro / Radeon / RTX dependencies).

XPU Observer is an observability platform for XDNA NPUs (and other accelerators), not
just a system monitor. It powers deeper insight than typical monitors.

## Why

When developing local AI runtimes you need to correlate:
- CPU preparation work
- GPU / NPU declared load (WDDM)
- XRT dispatches and contexts
- kernel inventory, dispatch timings
- token/s from the runtime itself

Most tools show one slice. XPU Observer keeps a **single collection infrastructure**
and serves it to the UI, the local API, the MCP server and the exporters — with every
metric carrying its **source, unit, timestamp and validity**.

> Honesty rule: WDDM-declared activity is **not** physical XDNA2 occupancy; a function
> existing is **not** proof it runs. Every metric says what it is and what it is not.

## Install

```bash
cd xpu-observer
pip install -e .            # core (psutil + mcp)
pip install -e .[tray]      # optional system tray
```

Tested on Python 3.13, Windows 10/11. Works with and without an NPU.

## Usage

```bash
xpu-observer --once                    # collect one pass, print JSON (scripting)
xpu-observer --export snap.csv         # one pass -> CSV snapshot
xpu-observer --trace TRACE_DIR         # dispatch tracer: stats + per-kernel timing
xpu-observer --trace TRACE --trace-export out.chrome.json   # + Chrome trace export
xpu-observer --api                     # headless: local API on 127.0.0.1:8766
xpu-observer --api --mcp               # API + MCP stdio server
xpu-observer --ui                      # tkinter dashboard
```

### Dispatch tracer (V0.6)

Parses runtime traces (dispatch CSV, JSONL dispatch events, `runtime_trace`
TOKEN markers — auto-detected in a directory) and produces a per-dispatch timeline:
`pid, tid, hwctx_id, kernel, instruction_hash, bo_id, group_id, start_ns, end_ns,
sync_direction, status, token_id` + a µs breakdown `submit/wait/npu/sync/host`. It
counts instruction cache hits/misses and BO reallocations, correlates each dispatch
to its token, and returns a verdict (`HOST_BOUND | SYNC_WAIT_BOUND | NPU_BOUND`)
plus per-kernel cost — exactly what separates CPU prep + XRT sync from real XDNA2
compute when a K-split change tanks throughput.

No hardware needed to try it:

```bash
python scripts/make_demo_trace.py demo_trace          # 64 tokens synthetic
xpu-observer --trace demo_trace --trace-export demo.chrome.json
```

Instrumentation priority (red-team compliant): the runtime's **own** trace mechanism
is ingested first; DLL hooks are the fallback and feed the same normalized event stream.
Simulated runs are never presented as hardware measurements.

### Local API (read-only)

```
GET /health          {"ok": true}
GET /metrics         full snapshot (metrics + raw processes/gpus/npu)
GET /metrics/history?limit=100
GET /capabilities    GPU/NPU/tools/pdh detected on this machine
GET /processes       per-PID CPU/GPU/NPU/mem/DLLs
GET /npu/kernels     discovered .xclbin inventory
GET /drivers         NPU driver service status
GET /hooks           hook manager state
GET /export?format=csv|json|history.csv&limit=N
```

Bound to `127.0.0.1` only. No write endpoints.

## Feature status (V0.x)

| Version | Feature | Implemented | Tested | Hardware-validated |
|---|---|---|---|---|
| V0.1 | CPU/RAM/GPU/NPU collection | ✅ | ✅ unit | partial (this machine) |
| V0.1 | PDH WDDM loads | ✅ | ✅ | ✅ (this machine) |
| V0.1 | XRT contexts/dispatches | ✅ | ✅ parser | ✅ (this machine, idle) |
| V0.1 | Multi-GPU (nvidia-smi) | ✅ | ✅ | ✅ (RTX 5070) |
| V0.1 | tkinter 6-tab UI (Dashboard/Processes/NPU/Hooks/MCP/Settings) | ✅ | ✅ construct | manual |
| V0.2 | MCP stdio server | ✅ | ✅ e2e handshake | ✅ (real pipes) |
| V0.2 | Local HTTP API | ✅ | ✅ | ✅ |
| V0.2 | CSV/JSON export | ✅ | ✅ | ✅ |
| V0.3 | DLL/runtime discovery | ✅ | ⚠️ unit | needs a live LLM run |
| V0.3 | Hook catalog + compatibility | ✅ | ✅ unit | conservative by design |
| V0.4 | Confirmation-based hook manager | ✅ | ✅ | manual (never auto-injects) |
| V0.5 | AI profiler / dispatch analysis | 🔶 core | 🔶 | not hardware-validated |
| V0.6 | **Dispatch tracer** (XRT run/start/wait/sync) | ✅ | ✅ unit+CLI | synthetic demo only |
| V0.6 | Token↔kernel↔context correlation + Chrome/Perfetto export | ✅ | ✅ | synthetic demo only |
| V0.6 | Instruction cache hits/misses + BO realloc accounting | ✅ | ✅ | synthetic demo only |
| — | ETW provider | ⛔ stubbed | — | not implemented |
| — | PySide6 GUI | ⛔ | — | tkinter used (lighter, no dep) |

## Architecture

```
src/xpu_observer/
  core/        metrics, capabilities, collector, scheduler, event_bus, util
  providers/   cpu, ram, gpu, npu (composite), pdh (WDDM), xrt, processes, etw
  hooks/       registry, discovery, compatibility, manager, verifier, states
  diagnostics/ correlation (Timeline), dispatch, ctrlcode
  api/         local HTTP server (127.0.0.1)
  mcp/         MCP stdio server (official protocol)
  export/      csv, json
  ui/          tkinter dashboard
  runtime.py   App — single object wired to every consumer
  main.py      CLI
```

One collector pass → one `Snapshot` → UI, API, MCP and exporters all read the same data.

## Security

- **Read-only by default**, hooks disabled by default.
- `request_hook_activation` / `request_hook_deactivation` only create a **local
  confirmation request** — they never load a DLL. The GUI must display it; the user
  must approve. No arbitrary injection through MCP.
- No EC/MSR/driver-register modification in this edition.
- HTTP bound to 127.0.0.1, responses bounded.
- No proprietary drivers are bundled; hook catalog documents instrumentation that the
  user may bring and approve themselves.

## Tests

```bash
pip install -e .[dev]
pytest tests -q          # 20 tests: units, parsers, MCP e2e (real subprocess), API
python -m compileall src
```

Simulated tests are never presented as hardware validation.

## License

MIT (see `LICENSE`). psutil / mcp dependencies audit in `docs/AUDIT_SOURCE.md`.